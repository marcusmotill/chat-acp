import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Any, Optional

from core.models import Session, Workspace
from core.ports.agent_client import AgentClientProtocol
from adapters.agent.jsonrpc import JsonRpcNotification, JsonRpcResponse

logger = logging.getLogger(__name__)

class AcpStdioAgent(AgentClientProtocol):
    """
    Spawns an agent CLI subprocess specified by `agent_command`.
    Communicates via JSON-RPC 2.0 over stdin/stdout lines.
    """
    
    def __init__(self, agent_command: list[str]):
        """
        :param agent_command: The executable and args to run, e.g. ["npx", "claude-code", "--acp"]
        """
        self.agent_command = agent_command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._agent_session_id: Optional[str] = None

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
                    if notif.method == "session/update":
                        # The update itself is nested in params['update']
                        await self._update_queue.put(notif)
                else:
                    logger.info(f"Agent Notification/Request: {data}")
            except json.JSONDecodeError:
                # If it's not JSON, route to normal logger
                text = line.decode().strip()
                if text:
                    logger.info(f"AGENT STDOUT: {text}")
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
                    id=req_id, 
                    error={"code": -32000, "message": reason}
                )
                fut.set_result(resp)
        self._pending_requests.clear()

    async def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        raw_req = json.dumps(payload) + "\n"
        logger.info(f">>> SEND NOTIFICATION: {raw_req.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_req.encode())
            await self.process.stdin.drain()

    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> JsonRpcResponse:
        self._request_id += 1
        req_id = self._request_id
        
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut
        
        raw_req = json.dumps(payload) + "\n"
        logger.info(f">>> SEND REQUEST: {raw_req.strip()}")
        if self.process and self.process.stdin:
            self.process.stdin.write(raw_req.encode())
            await self.process.stdin.drain()
            
        return await fut

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        """Starts the CLI subprocess and initializes ACP."""
        logger.info(f"Starting agent with command: {' '.join(self.agent_command)} in {workspace.target_path}")
        
        self.process = await asyncio.create_subprocess_exec(
            *self.agent_command,
            cwd=workspace.target_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        self._listen_task = asyncio.create_task(self._listen_stdout())
        self._stderr_task = asyncio.create_task(self._listen_stderr())
        
        # ACP initialization sequence
        logger.info("Sending initialize request")
        init_resp = await self.send_request("initialize", {
            "protocolVersion": 1,
            "clientInfo": {"name": "chat-acp", "version": "0.1.0"},
            "capabilities": {}
        })
        if init_resp.error:
            logger.error(f"Agent failed to initialize: {init_resp.error}")
            raise RuntimeError(f"Agent failed to initialize: {init_resp.error.get('message')}")
        
        logger.info("Sending session/new request")
        # According to docs: sessionId is generated by the agent.
        sess_resp = await self.send_request("session/new", {
            "cwd": workspace.target_path,
            "mcpServers": []
        })
        if sess_resp.error:
            logger.error(f"Agent failed to create session: {sess_resp.error}")
            raise RuntimeError(f"Agent failed to create session: {sess_resp.error.get('message')}")

        if not sess_resp.result or "sessionId" not in sess_resp.result:
            logger.error(f"Agent session/new did not return a sessionId: {sess_resp.result}")
            raise RuntimeError("Agent failed to return a sessionId")

        self._agent_session_id = sess_resp.result["sessionId"]
        logger.info(f"Agent session {self._agent_session_id} (Internal: {session.id}) started successfully.")

    async def prompt(self, session: Session, message: str) -> AsyncGenerator[str, None]:
        """
        Sends the session/prompt and yields formatted strings 
        by consuming session/update notifications from the queue until the prompt returns.
        """
        if not self.process or not self.process.stdin:
            raise RuntimeError("Agent process not started.")

        if not self._agent_session_id:
            raise RuntimeError("Agent session not initialized.")

        logger.info(f"User sending prompt: {message}")
        prompt_params = {
            "sessionId": self._agent_session_id,
            "prompt": [
                {
                    "type": "text",
                    "text": message
                }
            ]
        }
        prompt_task = asyncio.create_task(self.send_request("session/prompt", prompt_params))
        
        # We continually read from the update queue until the prompt_task completes
        # Note: in real ACP, the prompt_task waits until the turn completes
        while not prompt_task.done():
            try:
                # Wait for an update or prompt to finish
                notif_task = asyncio.create_task(self._update_queue.get())
                done, pending = await asyncio.wait(
                    [prompt_task, notif_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                if notif_task in done:
                    notif: JsonRpcNotification = notif_task.result()
                    # According to docs: params['update'] = { sessionUpdate: 'agent_message_chunk', content: {type: 'text', text: '...'} }
                    update_obj = notif.params.get("update", {})
                    update_type = update_obj.get("sessionUpdate")
                    
                    if update_type == "agent_message_chunk":
                        content_obj = update_obj.get("content", {})
                        if isinstance(content_obj, dict):
                            text = content_obj.get("text", "")
                            yield str(text)
                    elif update_type == "tool_call_start":
                        tool_name = update_obj.get("content", {}).get("name", "unknown tool")
                        yield f"\n🛠️ **Using tool**: `{tool_name}`...\n"
                    elif update_type == "agent_plan":
                        plan_text = update_obj.get("content", {}).get("text", "")
                        yield f"\n📝 **Agent Plan**: {plan_text}\n"
                    elif "content" in notif.params:
                        # Fallback for simpler implementations
                        yield str(notif.params["content"])
                else:
                    notif_task.cancel()
                    
            except Exception as e:
                logger.error(f"Error during prompt loop: {e}")
                break
                
        # Final result of prompt
        final_resp = prompt_task.result()
        if final_resp.error:
            yield f"\n❌ **Agent Error**: {final_resp.error.get('message', 'Unknown error')}"
        elif final_resp.result:
            yield f"\n✅ **Turn Complete**: {final_resp.result.get('stopReason', 'success')}"

    async def cancel_prompt(self, session: Session) -> None:
        """Sends session/cancel notification."""
        if not self._agent_session_id:
            return
        logger.info(f"Cancelling prompt for agent session {self._agent_session_id}")
        await self.send_notification("session/cancel", {"sessionId": self._agent_session_id})

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
