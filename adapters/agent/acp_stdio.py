import os
import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Any, Optional, List, Union

from core.models import Session, Workspace, StreamChunk
from core.ports.agent_client import AgentClientProtocol, PromptTurnCallback
from core.exceptions import AgentInitializationError, AgentExecutionError
from adapters.agent.jsonrpc import JsonRpcNotification, JsonRpcResponse

logger = logging.getLogger(__name__)

# JSON-RPC error code for "Method not found"
METHOD_NOT_FOUND_CODE = -32601


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
    PROMPT_TURN = "prompt_turn"


class AcpStdioAgent(AgentClientProtocol):
    """
    Spawns an agent CLI subprocess specified by `agent_command`.
    Communicates via JSON-RPC 2.0 over stdin/stdout lines.
    """

    def __init__(
        self,
        agent_command: list[str],
        agent_env: Optional[Dict[str, str]] = None,
        platform: str = "default",
    ):
        """
        :param agent_command: The executable and args to run, e.g. ["npx", "claude-code", "--acp"]
        :param agent_env: Optional environment variables for the agent subprocess.
        """
        self.agent_command = agent_command
        self.agent_env = agent_env or {}
        self.platform = platform
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._error_queue: asyncio.Queue = asyncio.Queue()
        self._agent_session_id: Optional[str] = None
        self._config_options: List[Dict[str, Any]] = []
        self._successful_config_method: Optional[str] = None
        self._prompt_turn_callback: Optional[PromptTurnCallback] = None
        self._session: Optional[Session] = None
        # State flag: set True when we're probing methods so stderr noise is expected
        self._suppress_stderr: bool = False

    def set_user_interaction_callback(self, callback: PromptTurnCallback) -> None:
        """Sets the function to call when the agent needs user action (e.g., prompt_turn)."""
        self._prompt_turn_callback = callback

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

    async def send_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}

        raw_req = json.dumps(payload) + "\n"
        logger.debug(f">>> SEND NOTIFICATION: {raw_req.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_req.encode())
            await self.process.stdin.drain()

    async def send_response(
        self,
        request_id: Union[str, int],
        result: Optional[Any] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result

        raw_resp = json.dumps(payload) + "\n"
        logger.debug(f">>> SEND RESPONSE: {raw_resp.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_resp.encode())
            await self.process.stdin.drain()

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        """Starts the CLI subprocess and initializes ACP."""
        logger.info(
            f"Starting agent with command: {' '.join(self.agent_command)} in {workspace.target_path}"
        )
        self._session = session

        # Prepare environment
        env = os.environ.copy()
        if self.agent_env:
            env.update(self.agent_env)

        # Inject session metadata for "wake up" notifications
        env["ACP_CHAT_SESSION_ID"] = str(session.id)
        env["ACP_CHAT_WORKSPACE_ID"] = str(workspace.id)
        env["ACP_CHAT_PLATFORM"] = self.platform

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
        logger.debug(f"Agent session ID: {self._agent_session_id}")

        self._config_options = sess_resp.result.get("configOptions", [])

        # Compatibility logic: build config options from legacy model/mode lists
        model_list = None
        models_root = sess_resp.result.get("models")
        if isinstance(models_root, dict):
            model_list = models_root.get("availableModels") or models_root.get("models")
        if not model_list:
            model_list = sess_resp.result.get("availableModels")
        if not model_list:
            modes_root = sess_resp.result.get("modes")
            if isinstance(modes_root, dict):
                model_list = modes_root.get("availableModes") or modes_root.get(
                    "models"
                )
            else:
                model_list = modes_root
        if not model_list:
            model_list = sess_resp.result.get("availableModes")

        if not self._config_options and model_list:
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

        logger.info(f"Agent session {self._agent_session_id} started successfully.")

    async def _listen_stdout(self):
        """Reads lines from the agent's stdout and routes them."""
        if not self.process or not self.process.stdout:
            return

        buffer = b""
        try:
            while True:
                # Read in large chunks to handle massive JSON lines (LimitOverrunError fix)
                chunk = await self.process.stdout.read(65536)
                if not chunk:
                    break

                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    raw_line = line.decode().strip()
                    if not raw_line:
                        continue

                    try:
                        data = json.loads(raw_line)
                    except json.JSONDecodeError:
                        logger.error(
                            f"Failed to decode JSON from agent: {raw_line[:100]}"
                        )
                        continue

                    # Handle Response
                    if "id" in data and ("result" in data or "error" in data):
                        resp = JsonRpcResponse(**data)
                        fut = self._pending_requests.pop(resp.id, None)
                        if fut:
                            fut.set_result(resp)
                        else:
                            logger.warning(
                                f"Received response for unknown request ID: {resp.id}"
                            )

                    # Handle Notification
                    elif "method" in data and "id" not in data:
                        notif = JsonRpcNotification(**data)
                        await self._update_queue.put(notif)

                    # Handle Request (Agent calling us)
                    elif "method" in data and "id" in data:
                        method = data["method"]
                        req_id = data["id"]
                        params = data.get("params", {})

                        if (
                            method == JsonRpcMethods.PROMPT_TURN
                            and self._prompt_turn_callback
                            and self._session
                        ):
                            try:
                                result = await self._prompt_turn_callback(
                                    self._session, params
                                )
                                await self.send_response(req_id, result=result)
                            except Exception as e:
                                logger.exception("Error handling prompt_turn request")
                                await self.send_response(
                                    req_id, error={"code": -32603, "message": str(e)}
                                )
                        else:
                            logger.warning(
                                f"Received unknown request method from agent: {method}"
                            )
                            await self.send_response(
                                req_id,
                                error={"code": -32601, "message": "Method not found"},
                            )

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in stdout listener")

    async def _listen_stderr(self):
        """Reads from agent stderr with debounce grouping.

        Groups rapid multi-line stderr output (like JSON-RPC error blobs or
        tracebacks) into single error messages using a 200ms debounce window.
        Lines arriving while _suppress_stderr is True are discarded at read
        time (not at flush time) to avoid race conditions with the debounce.
        """
        if not self.process or not self.process.stderr:
            return

        stderr_buffer: list[str] = []
        debounce_seconds = 0.2

        async def flush_buffer():
            """Flush accumulated stderr lines as a single error."""
            if not stderr_buffer:
                return
            combined = "\n".join(stderr_buffer)
            stderr_buffer.clear()

            logger.warning(f"[AGENT STDERR] {combined}")
            await self._error_queue.put(StreamChunk(type="error", content=combined))

        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        self.process.stderr.readline(), timeout=debounce_seconds
                    )
                    if not line:
                        # EOF — flush remaining
                        await flush_buffer()
                        break
                    decoded = line.decode().strip()
                    if decoded:
                        # Check suppression at READ time, not flush time.
                        # This avoids the race where the flag turns off before
                        # the debounce timer fires.
                        if self._suppress_stderr:
                            logger.debug(f"[AGENT STDERR] (suppressed) {decoded}")
                        else:
                            stderr_buffer.append(decoded)
                except asyncio.TimeoutError:
                    # Debounce window elapsed — flush what we have
                    await flush_buffer()
        except asyncio.CancelledError:
            await flush_buffer()
        except Exception:
            logger.exception("Error in stderr listener")

    async def prompt(
        self, session: Session, message: str
    ) -> AsyncGenerator[StreamChunk, None]:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Agent process not started.")

        if not self._agent_session_id:
            raise AgentExecutionError("Agent session not initialized.")

        prompt_params = {
            "sessionId": self._agent_session_id,
            "prompt": [{"type": "text", "text": message}],
        }
        prompt_task = asyncio.create_task(
            self.send_request(JsonRpcMethods.SESSION_PROMPT, prompt_params)
        )

        while not prompt_task.done():
            try:
                # Drain any stderr errors that arrived
                while not self._error_queue.empty():
                    try:
                        error_chunk = self._error_queue.get_nowait()
                        yield error_chunk
                    except asyncio.QueueEmpty:
                        break

                notif_task = asyncio.create_task(self._update_queue.get())
                done, _ = await asyncio.wait(
                    [prompt_task, notif_task], return_when=asyncio.FIRST_COMPLETED
                )

                if notif_task in done:
                    notif: JsonRpcNotification = notif_task.result()
                    update_obj = notif.params.get("update", {})
                    update_type = update_obj.get("sessionUpdate")
                    content_obj = update_obj.get("content", {})
                    text = (
                        content_obj.get("text", "")
                        if isinstance(content_obj, dict)
                        else ""
                    )

                    if update_type == "agent_message_chunk":
                        if text:
                            yield StreamChunk(type="text", content=text)
                    elif update_type == "tool_call_start":
                        tool_name = content_obj.get("name", "unknown tool")
                        yield StreamChunk(
                            type="text", content=f"\n[Status: Using tool: {tool_name}]"
                        )
                    elif update_type == "agent_plan":
                        plan_text = content_obj.get("text", "")
                        if plan_text:
                            yield StreamChunk(
                                type="text", content=f"\n[Thought: Plan: {plan_text}]"
                            )
                    elif update_type == "agent_status":
                        if text:
                            yield StreamChunk(
                                type="text", content=f"\n[Status: {text}]"
                            )
                    elif update_type == "agent_thought":
                        if text:
                            yield StreamChunk(
                                type="text", content=f"\n[Thought: {text}]"
                            )
                    elif update_type == "config_option_update":
                        self._config_options = update_obj.get("configOptions", [])
                        yield StreamChunk(
                            type="status", content="Configuration Updated"
                        )
                else:
                    notif_task.cancel()
            except Exception as e:
                logger.error(f"Error during prompt loop: {e}")
                break

        while not self._update_queue.empty():
            try:
                notif = self._update_queue.get_nowait()
                update_obj = notif.params.get("update", {})
                if update_obj.get("sessionUpdate") == "agent_message_chunk":
                    content_obj = update_obj.get("content", {})
                    text = (
                        content_obj.get("text", "")
                        if isinstance(content_obj, dict)
                        else ""
                    )
                    if text:
                        yield StreamChunk(type="text", content=text)
            except asyncio.QueueEmpty:
                break

        # Drain any remaining stderr errors
        while not self._error_queue.empty():
            try:
                error_chunk = self._error_queue.get_nowait()
                yield error_chunk
            except asyncio.QueueEmpty:
                break

        final_resp = prompt_task.result()
        if final_resp.error:
            yield StreamChunk(
                type="text", content=f"\n❌ Error: {final_resp.error.get('message')}"
            )
        elif final_resp.result:
            yield StreamChunk(
                type="text",
                content=f"\n✅ Done: {final_resp.result.get('stopReason', 'success')}",
            )

    async def cancel_prompt(self, session: Session) -> None:
        if not self._agent_session_id:
            return
        await self.send_notification(
            JsonRpcMethods.SESSION_CANCEL, {"sessionId": self._agent_session_id}
        )

    async def stop_session(self, session: Session) -> None:
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

    async def get_config_options(self, session: Session) -> List[Dict[str, Any]]:
        return self._config_options

    def _get_config_category(self, config_id: str) -> Optional[str]:
        """Looks up the category for a config option by its ID."""
        for opt in self._config_options:
            if opt.get("id") == config_id:
                return opt.get("category")
        return None

    async def set_config_option(
        self, session: Session, config_id: str, value: Any
    ) -> bool:
        """
        Sets a configuration option for the session.
        Uses a robust fallback strategy to try different ACP methods in order of preference.
        """
        if not self._agent_session_id:
            return False

        category = self._get_config_category(config_id)
        is_model = category in ("mode", "model") or config_id in ("model", "mode")

        # Define methods to try. Standard ACP first, then common legacy/extension methods for models.
        methods = [JsonRpcMethods.SESSION_SET_CONFIG]
        if is_model:
            methods += [
                JsonRpcMethods.SESSION_SET_MODE,
                JsonRpcMethods.SESSION_SET_MODEL,
                JsonRpcMethods.SESSION_SET_DASH_MODEL,
            ]

        last_error = None
        self._suppress_stderr = True
        try:
            for method in methods:
                resp = await self._send_config_request(method, config_id, value)
                if not resp.error:
                    # Success: update local config options if the agent returned them
                    if resp.result and "configOptions" in resp.result:
                        self._config_options = resp.result["configOptions"]
                    return True

                last_error = resp.error
                if is_model:
                    logger.debug(
                        f"Attempt with {method} failed for {config_id}: {resp.error.get('message')}. "
                        "Trying next fallback..."
                    )
                else:
                    # Non-model settings are specialized; if the primary method fails, we don't guess.
                    break

            if last_error:
                self._raise_from_error(methods[0], last_error)
            return False
        finally:
            self._suppress_stderr = False
            self._drain_error_queue()

    async def _send_config_request(
        self, method: str, config_id: str, value: Any
    ) -> JsonRpcResponse:
        """Builds params and sends the JSON-RPC request for a config method."""
        params: Dict[str, Any] = {"sessionId": self._agent_session_id}

        # Map methods to their specific parameter keys
        key_map = {
            JsonRpcMethods.SESSION_SET_CONFIG: ("configId", config_id),
            JsonRpcMethods.SESSION_SET_MODE: ("modeId", value),
            JsonRpcMethods.SESSION_SET_MODEL: ("modelId", value),
            JsonRpcMethods.SESSION_SET_DASH_MODEL: ("modelId", value),
        }

        if method in key_map:
            key, val = key_map[method]
            params[key] = val
            if method == JsonRpcMethods.SESSION_SET_CONFIG:
                params["value"] = value

        return await self.send_request(method, params)

    def _raise_from_error(self, method: str, error: Dict[str, Any]) -> None:
        """Raises AgentExecutionError from a JSON-RPC error dict."""
        message = error.get("message", "Unknown error")
        details = error.get("data", {}).get("details", "")
        full = f"{message}: {details}" if details else message
        logger.error(f"Config method {method} failed: {full}")
        raise AgentExecutionError(full)

    def _drain_error_queue(self) -> None:
        """Discards all items currently in the error queue."""
        while not self._error_queue.empty():
            try:
                self._error_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
