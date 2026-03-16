import asyncio
import logging
from typing import Optional, Callable, Dict, Any

from core.models import Session, Workspace, ChatMessage
from core.ports.agent_client import AgentClientProtocol
from core.ports.chat_client import ChatClientProtocol
from core.exceptions import AgentException

logger = logging.getLogger(__name__)


class SessionContext:
    """
    Encapsulates the runtime state and execution logic for a single Agent Session.
    """

    def __init__(
        self,
        session: Session,
        workspace: Workspace,
        agent_factory: Callable[[Workspace], AgentClientProtocol],
        chat_adapter: ChatClientProtocol,
        initial_model: Optional[str] = None,
    ):
        self.session = session
        self.workspace = workspace
        self.agent_factory = agent_factory
        self.chat_adapter = chat_adapter

        self.agent: Optional[AgentClientProtocol] = None
        self.queue: asyncio.Queue = asyncio.Queue()
        self.busy: bool = False
        self.initial_model = initial_model

    async def process_message(
        self,
        message: ChatMessage,
        chat_workspace_id: str,
        chat_session_id: str,
        chat_session_name: str,
    ) -> None:
        """
        Enqueues the message and triggers processing if not busy.
        """
        if self.busy:
            await self.queue.put(
                (message, chat_workspace_id, chat_session_id, chat_session_name)
            )
            await self.chat_adapter.send_message(
                self.session, "⏳ Agent is busy. Message queued."
            )
            return

        self.busy = True
        try:
            await self._execute_turn(message)

            # Process queue
            while not self.queue.empty():
                next_msg_data = await self.queue.get()
                msg, _, _, _ = next_msg_data
                await self._execute_turn(msg)
        finally:
            self.busy = False

    async def _execute_turn(self, message: ChatMessage) -> None:
        """
        Executes a single turn: Start agent -> Prompt -> Stream -> End
        """
        try:
            is_new_session = self.agent is None
            await self._ensure_agent_started()

            if not message:
                logger.info(f"Session {self.session.id} initialized/warmed up.")
                return

            if not self.agent:
                raise AgentException("Failed to start agent.")

            prompt_content = message.content
            if is_new_session and hasattr(self, "_pending_context"):
                prompt_content = self._pending_context + prompt_content
                del self._pending_context

            await self.chat_adapter.trigger_typing(self.session)
            response_stream = self.agent.prompt(self.session, prompt_content)
            await self.chat_adapter.stream_response(self.session, response_stream)

        except AgentException as e:
            logger.error(f"Agent error in session {self.session.id}: {e}")
            await self.chat_adapter.send_message(self.session, f"❌ Agent Error: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in session {self.session.id}")
            await self.chat_adapter.send_message(
                self.session, f"❌ Unexpected Error: {e}"
            )

    async def _ensure_agent_started(self) -> None:
        if self.agent:
            return

        logger.debug(f"Starting new agent for session {self.session.id}")
        self.agent = self.agent_factory(self.workspace)
        # Set the callback for agent-initiated requests (e.g., prompt_turn)
        self.agent.set_user_interaction_callback(self._handle_agent_prompt_turn)
        await self.agent.start_session(self.session, self.workspace)

        # Persistence: If this is an existing thread, fetch history and inject context
        try:
            history = await self.chat_adapter.get_history(self.session, limit=10)
            if history and len(history) > 1:
                # Exclude the very last message if it's the one we're about to process
                # But history() usually returns messages sent *before* now if called right
                # Actually history() might include the trigger message.
                # We'll just build a "Session Restore" block.

                context_lines = []
                for m in history:
                    # Skip empty or meta messages
                    if not m.content.strip():
                        continue
                    context_lines.append(f"{m.author_name}: {m.content}")

                if context_lines:
                    logger.info(
                        f"Restoring context for session {self.session.id} from {len(context_lines)} historical messages."
                    )
                    self._pending_context = (
                        "--- SESSION RESTORED ---\n"
                        "The following is a summary of the previous conversation in this thread. "
                        "Please use this context for future turns:\n\n"
                        + "\n".join(context_lines)
                        + "\n--- END OF RESTORED SESSION ---\n\n"
                    )
        except Exception as e:
            logger.warning(f"Failed to fetch history for restoration: {e}")

        if self.initial_model:
            logger.info(
                f"Auto-applying saved model {self.initial_model} to session {self.session.id}"
            )
            try:
                await self.agent.set_config_option(
                    self.session, "model", self.initial_model
                )
            except Exception as e:
                logger.warning(f"Failed to auto-apply model {self.initial_model}: {e}")

    async def _handle_agent_prompt_turn(
        self, session: Session, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handles an incoming prompt_turn request from the Agent.
        This blocks and delegates to the chat adapter to get user input.
        """
        if session.id != self.session.id:
            logger.error("Mismatched session IDs in prompt_turn callback.")
            # Return an error response that the agent can handle
            return {
                "action": {"type": "text", "content": "Error: Session ID mismatch."}
            }

        try:
            return await self.chat_adapter.await_action_from_user(self.session, params)
        except Exception as e:
            logger.exception(
                f"Error handling prompt_turn for session {self.session.id}"
            )
            # Return an error response that the agent can handle
            return {"action": {"type": "text", "content": f"Error: {e}"}}

    async def abort(self) -> None:
        """Aborts the current action and stops the agent."""
        if self.agent:
            await self.agent.cancel_prompt(self.session)
            # Short delay to allow cancellation to propagate
            await asyncio.sleep(0.5)
            await self.agent.stop_session(self.session)
            self.agent = None

        # Clear queue
        while not self.queue.empty():
            self.queue.get_nowait()

        self.busy = False
        logger.info(f"Aborted session context for {self.session.id}")

    async def cleanup(self) -> None:
        """Fully stops the agent."""
        if self.agent:
            await self.agent.stop_session(self.session)
            self.agent = None
