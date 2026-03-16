import asyncio
import logging
from typing import Optional, Callable

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
            await self._ensure_agent_started()

            if not message:
                logger.info(f"Session {self.session.id} initialized/warmed up.")
                return

            if not self.agent:
                raise AgentException("Failed to start agent.")

            await self.chat_adapter.trigger_typing(self.session)
            response_stream = self.agent.prompt(self.session, message.content)
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
        await self.agent.start_session(self.session, self.workspace)

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
