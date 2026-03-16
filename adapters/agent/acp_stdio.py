import os
import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Any, Optional, List

from core.models import Session, Workspace
from core.ports.agent_client import AgentClientProtocol
from core.exceptions import AgentInitializationError, AgentExecutionError
from adapters.agent.jsonrpc import JsonRpcNotification, JsonRpcResponse

logger = logging.getLogger(__name__)


class JsonRpcMethods:
    INITIALIZE = "initialize"
    SESSION_NEW = "session/new"
    SESSION_PROMPT = "session/prompt"
    SESSION_UPDATE = "session/update"
    SESSION_CANCEL = "session/cancel"
    SESSION_SET_CONFIG = "session/set_config_option"
    SESSION_SET_MODE = "session/set_mode"
    SESSION_SET_MODEL = "session/set_model"
    SESSION_SET_DASH_MODEL = "session/set-model"


class AcpStdioAgent(AgentClientProtocol):
    """
    Spawns an agent CLI subprocess specified by `agent_command`.
    Communicates via JSON-RPC 2.0 over stdin/stdout lines.
    """

    def __init__(
        self, agent_command: list[str], agent_env: Optional[Dict[str, str]] = None
    ):
        """
        :param agent_command: The executable and args to run, e.g. ["npx", "claude-code", "--acp"]
        :param agent_env: Optional environment variables for the agent subprocess.
        """
        self.agent_command = agent_command
        self.agent_env = agent_env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._agent_session_id: Optional[str] = None
        self._config_options: List[Dict[str, Any]] = []
        self._successful_model_method: Optional[str] = None

    async def _listen_stdout(self):
        """Reads stdout line by line, parsing Json RPC."""
        if not self.process or not self.process.stdout:
            return

        while True:
            line = await self.process.stdout.readline()
            if not line:
                break

            try:
                data = json.loads(line.decode().strip())
                # Handle Response
                if "id" in data and ("result" in data or "error" in data):
                    resp = JsonRpcResponse(**data)
                    fut = self._pending_requests.pop(resp.id, None)
                    if fut and not fut.done():
                        fut.set_result(resp)
                # Handle Notification
                elif "method" in data and "id" not in data:
                    notif = JsonRpcNotification(**data)
                    if notif.method == JsonRpcMethods.SESSION_UPDATE:
                        # The update itself is nested in params['update']
                        await self._update_queue.put(notif)
                else:
                    logger.debug(f"Agent Notification/Request: {data}")
            except json.JSONDecodeError:
                # If it's not JSON, route to normal logger
                text = line.decode().strip()
                if text:
                    logger.debug(f"AGENT STDOUT: {text}")
            except Exception as e:
                logger.error(f"Error parsing agent output: {e}\nLine: {line.decode()}")

        logger.info("Agent stdout closed.")
        self._cleanup_pending_requests("Agent process terminated.")

    async def _listen_stderr(self):
        """Reads stderr line by line and logs it."""
        if not self.process or not self.process.stderr:
            return

        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                logger.info(f"AGENT STDERR: {text}")

    def _cleanup_pending_requests(self, reason: str):
        """Resolves all pending requests with an error."""
        for req_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                resp = JsonRpcResponse(
                    id=req_id, error={"code": -32000, "message": reason}
                )
                fut.set_result(resp)
        self._pending_requests.clear()

    async def send_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        raw_req = json.dumps(payload) + "\n"
        logger.debug(f">>> SEND NOTIFICATION: {raw_req.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_req.encode())
            await self.process.stdin.drain()

    async def send_request(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> JsonRpcResponse:
        self._request_id += 1
        req_id = self._request_id

        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        raw_req = json.dumps(payload) + "\n"
        logger.debug(f">>> SEND REQUEST: {raw_req.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_req.encode())
            await self.process.stdin.drain()

        return await fut

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        """Starts the CLI subprocess and initializes ACP."""
        logger.info(
            f"Starting agent with command: {' '.join(self.agent_command)} in {workspace.target_path}"
        )

        # Prepare environment
        env = os.environ.copy()
        if self.agent_env:
            env.update(self.agent_env)

        self.process = await asyncio.create_subprocess_exec(
            *self.agent_command,
            cwd=workspace.target_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        self._listen_task = asyncio.create_task(self._listen_stdout())
        self._stderr_task = asyncio.create_task(self._listen_stderr())

        # ACP initialization sequence
        logger.debug("Sending initialize request")
        init_resp = await self.send_request(
            JsonRpcMethods.INITIALIZE,
            {
                "protocolVersion": 1,
                "clientInfo": {"name": "chat-acp", "version": "0.1.0"},
                "capabilities": {"configOptions": {}},
            },
        )
        if init_resp.error:
            logger.error(f"Agent failed to initialize: {init_resp.error}")
            raise AgentInitializationError(
                f"Agent failed to initialize: {init_resp.error.get('message')}"
            )

        logger.debug("Sending session/new request")
        # According to docs: sessionId is generated by the agent.
        sess_resp = await self.send_request(
            JsonRpcMethods.SESSION_NEW, {"cwd": workspace.target_path, "mcpServers": []}
        )
        if sess_resp.error:
            logger.error(f"Agent failed to create session: {sess_resp.error}")
            raise AgentInitializationError(
                f"Agent failed to create session: {sess_resp.error.get('message')}"
            )

        if not sess_resp.result or "sessionId" not in sess_resp.result:
            logger.error(
                f"Agent session/new did not return a sessionId: {sess_resp.result}"
            )
            raise AgentInitializationError("Agent failed to return a sessionId")

        self._agent_session_id = sess_resp.result["sessionId"]
        logger.debug(
            f"FULL session/new response: {json.dumps(sess_resp.result, indent=2)}"
        )

        # Store config options if provided
        self._config_options = sess_resp.result.get("configOptions", [])
        self._is_legacy_mode_api = False

        # Compatibility: Map various agent responses to configOptions
        # We prioritize 'models' over 'modes'
        model_list = None

        # 1. Check for 'models' field (OpenCode style)
        models_root = sess_resp.result.get("models")
        if isinstance(models_root, dict):
            model_list = models_root.get("availableModels") or models_root.get("models")

        # 2. Check for 'availableModels' at root
        if not model_list:
            model_list = sess_resp.result.get("availableModels")

        # 3. Check for 'modes' field (Legacy ACP)
        if not model_list:
            modes_root = sess_resp.result.get("modes")
            if isinstance(modes_root, dict):
                model_list = modes_root.get("availableModes") or modes_root.get("modes")
            else:
                model_list = modes_root

        # 4. Check for 'availableModes' at root
        if not model_list:
            model_list = sess_resp.result.get("availableModes")

        # Legacy Mode API Compatibility:
        # If the agent returned models/modes but not the standard 'configOptions',
        # we map the legacy fields into a 'model' config option for compatibility.
        if not self._config_options and model_list:
            logger.info(
                f"Agent provided legacy models/modes. Mapping for compatibility: {model_list}"
            )
            self._is_legacy_mode_api = True  # Treat as legacy if we had to map it

            # Ensure model_list is a list
            if not isinstance(model_list, list):
                model_list = [model_list]

            self._config_options = [
                {
                    "id": "model",
                    "name": "Model",
                    "category": "model",
                    "options": [
                        {
                            "value": str(
                                m.get("modelId") or m.get("id") or m
                                if isinstance(m, dict)
                                else m
                            ),
                            "name": str(
                                m.get("name") or m.get("modelId") or m.get("id") or m
                                if isinstance(m, dict)
                                else m
                            ),
                        }
                        for m in model_list
                    ],
                }
            ]

        logger.info(
            f"Agent session {self._agent_session_id} (Internal: {session.id}) started successfully with {len(self._config_options)} config options."
        )

    async def prompt(self, session: Session, message: str) -> AsyncGenerator[str, None]:
        """
        Sends the session/prompt and yields formatted strings
        by consuming session/update notifications from the queue until the prompt returns.
        """
        if not self.process or not self.process.stdin:
            raise RuntimeError("Agent process not started.")

        if not self._agent_session_id:
            raise AgentExecutionError("Agent session not initialized.")

        logger.info(f"User sending prompt: {message}")
        prompt_params = {
            "sessionId": self._agent_session_id,
            "prompt": [{"type": "text", "text": message}],
        }
        prompt_task = asyncio.create_task(
            self.send_request(JsonRpcMethods.SESSION_PROMPT, prompt_params)
        )

        # We continually read from the update queue until the prompt_task completes
        # Note: in real ACP, the prompt_task waits until the turn completes
        while not prompt_task.done():
            try:
                # Wait for an update or prompt to finish
                notif_task = asyncio.create_task(self._update_queue.get())
                done, pending = await asyncio.wait(
                    [prompt_task, notif_task], return_when=asyncio.FIRST_COMPLETED
                )

                if notif_task in done:
                    notif: JsonRpcNotification = notif_task.result()
                    logger.debug(f"Received notification: {notif.method}")
                    # According to docs: params['update'] = { sessionUpdate: 'agent_message_chunk', content: {type: 'text', text: '...'} }
                    update_obj = notif.params.get("update", {})
                    update_type = update_obj.get("sessionUpdate")

                    if update_type == "agent_message_chunk":
                        content_obj = update_obj.get("content", {})
                        if isinstance(content_obj, dict):
                            text = content_obj.get("text", "")
                            yield str(text)
                    elif update_type == "tool_call_start":
                        tool_name = update_obj.get("content", {}).get(
                            "name", "unknown tool"
                        )
                        yield f"\n🛠️ **Using tool**: `{tool_name}`...\n"
                    elif update_type == "agent_plan":
                        plan_text = update_obj.get("content", {}).get("text", "")
                        yield f"\n📝 **Agent Plan**: {plan_text}\n"
                    elif update_type == "config_option_update":
                        self._config_options = update_obj.get("configOptions", [])
                        yield "\n⚙️ **Agent Configuration Updated**\n"
                    elif "content" in notif.params:
                        # Fallback for simpler implementations
                        yield str(notif.params["content"])
                else:
                    notif_task.cancel()

            except Exception as e:
                logger.error(f"Error during prompt loop: {e}")
                break

        # FINAL DRAIN: Ensure we process any chunks that arrived
        # just before or with the prompt response.
        while not self._update_queue.empty():
            try:
                notif = self._update_queue.get_nowait()
                update_obj = notif.params.get("update", {})
                if update_obj.get("sessionUpdate") == "agent_message_chunk":
                    content_obj = update_obj.get("content", {})
                    if isinstance(content_obj, dict):
                        text = content_obj.get("text", "")
                        yield str(text)
            except asyncio.QueueEmpty:
                break

        # Final result of prompt
        final_resp = prompt_task.result()
        logger.info(
            f"Prompt task finished. Result: {json.dumps(final_resp.result, indent=2) if final_resp.result else 'No Result'}, Error: {final_resp.error}"
        )
        if final_resp.error:
            yield f"\n❌ **Agent Error**: {final_resp.error.get('message', 'Unknown error')}"
        elif final_resp.result:
            yield f"\n✅ **Turn Complete**: {final_resp.result.get('stopReason', 'success')}"

    async def cancel_prompt(self, session: Session) -> None:
        """Sends session/cancel notification."""
        if not self._agent_session_id:
            return
        logger.info(f"Cancelling prompt for agent session {self._agent_session_id}")
        await self.send_notification(
            JsonRpcMethods.SESSION_CANCEL, {"sessionId": self._agent_session_id}
        )

    async def stop_session(self, session: Session) -> None:
        """Kills the process."""
        if self._listen_task:
            self._listen_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()

        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except ProcessLookupError:
                pass
            self.process = None
        logger.info(f"Terminated agent process for {session.id}")

    async def get_config_options(self, session: Session) -> List[Dict[str, Any]]:
        return self._config_options

    async def set_config_option(
        self, session: Session, config_id: str, value: Any
    ) -> bool:
        """Sends session/set_config_option request with fallbacks for legacy agents."""
        if not self._agent_session_id:
            logger.error("Cannot set config option: Agent session not initialized.")
            return False

        # Methods to try if it's a model setting
        methods_to_try = []
        if config_id == "model":
            # If we already found a method that works for this session, try it first
            if self._successful_model_method:
                methods_to_try.append(self._successful_model_method)

            # Fallback list (excluding the successful one if already added)
            potential_methods = [
                JsonRpcMethods.SESSION_SET_CONFIG,
                JsonRpcMethods.SESSION_SET_MODE,
                JsonRpcMethods.SESSION_SET_MODEL,
                JsonRpcMethods.SESSION_SET_DASH_MODEL,
            ]
            for m in potential_methods:
                if m not in methods_to_try:
                    methods_to_try.append(m)
        else:
            methods_to_try = [JsonRpcMethods.SESSION_SET_CONFIG]

        last_error = None
        for method in methods_to_try:
            params = {"sessionId": self._agent_session_id}
            if method == JsonRpcMethods.SESSION_SET_CONFIG:
                params.update({"configId": config_id, "value": value})
            elif method == JsonRpcMethods.SESSION_SET_MODE:
                params.update({"modeId": value})
            elif method in (
                JsonRpcMethods.SESSION_SET_MODEL,
                JsonRpcMethods.SESSION_SET_DASH_MODEL,
            ):
                params.update({"modelId": value})

            logger.debug(f"Attempting to set model using {method}...")
            resp = await self.send_request(method, params)

            if not resp.error:
                logger.info(f"Successfully set {config_id} to {value} using {method}")
                if config_id == "model":
                    self._successful_model_method = method
                # Update cached options if returned
                if resp.result and "configOptions" in resp.result:
                    self._config_options = resp.result["configOptions"]
                return True

            last_error = resp.error
            # If not a "Method not found" error, maybe stop here?
            # Actually, let's try the next fallback anyway if it's not a session error.
            if resp.error.get("code") != -32601:
                logger.debug(
                    f"{method} failed with error other than MethodNotFound: {resp.error}"
                )

        logger.error(
            f"Failed to set config option {config_id} after trying all methods. Last error: {last_error}"
        )
        return False
