from __future__ import annotations
import logging
from typing import Dict, Optional, Callable, List, Any
from core.models import Workspace, ChatMessage
from core.ports.agent_client import AgentClientProtocol
from core.ports.chat_client import ChatClientProtocol
from core.ports.config import ConfigProtocol
from core.session_context import SessionContext

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Orchestrates the lifecycle of Sessions and routes messages
    between the Chat Client Adapter and the corresponding Agent Client Adapter.
    """

    def __init__(
        self,
        chat_adapter: ChatClientProtocol,
        agent_factory: Callable[[Workspace], AgentClientProtocol],
        config_registry: Optional["ConfigProtocol"] = None,
        on_workspace_registered: Optional[Callable[[str, str], None]] = None,
    ):
        self.chat_adapter = chat_adapter
        self.agent_factory = agent_factory
        self.config_registry = config_registry
        self.on_workspace_registered = on_workspace_registered

        # Registry of active workspaces by chat source mapping
        self.workspaces: Dict[str, Workspace] = {}

        # Registry of active session contexts
        self.session_contexts: Dict[str, SessionContext] = {}

    def register_workspace(self, chat_workspace_id: str, workspace: Workspace) -> None:
        """Registers a chat's workspace identifier to a specific local project directory Workspace."""
        self.workspaces[chat_workspace_id] = workspace
        logger.info(
            f"Registered Workspace '{workspace.name}' to chat workspace {chat_workspace_id}"
        )
        if self.on_workspace_registered:
            self.on_workspace_registered(chat_workspace_id, workspace.target_path)

    def get_workspace(self, chat_workspace_id: str) -> Optional[Workspace]:
        return self.workspaces.get(chat_workspace_id)

    async def handle_chat_message(
        self,
        message: ChatMessage,
        chat_workspace_id: str,
        chat_session_id: str,
        chat_session_name: str,
    ) -> None:
        """
        Entry pipeline from the Chat Client Adapter.
        """
        workspace = self.get_workspace(chat_workspace_id)
        if not workspace:
            logger.debug(
                f"Message in unmapped chat workspace {chat_workspace_id}, ignoring."
            )
            return

        # Get or create session context
        context = await self._get_or_create_context(
            workspace, chat_session_id, chat_session_name
        )

        # Process message
        await context.process_message(
            message, chat_workspace_id, chat_session_id, chat_session_name
        )

    async def _get_or_create_context(
        self, workspace: Workspace, chat_session_id: str, chat_session_name: str
    ) -> SessionContext:
        # Let the Chat Adapter give us the Session ID (usually thread ID)
        session = await self.chat_adapter.get_or_create_session(
            workspace=workspace, context_id=chat_session_id, title=chat_session_name
        )

        if session.id not in self.session_contexts:
            # Determine initial model from config
            initial_model = None
            if self.config_registry:
                platform = getattr(self.chat_adapter, "config_key", "default")
                p_config = self.config_registry.for_platform(platform)
                initial_model = p_config.get_workspace_setting(workspace.id, "model")

            self.session_contexts[session.id] = SessionContext(
                session=session,
                workspace=workspace,
                agent_factory=self.agent_factory,
                chat_adapter=self.chat_adapter,
                initial_model=initial_model,
            )

        return self.session_contexts[session.id]

    async def abort_session(self, chat_session_id: str) -> None:
        """Cancels any current prompt and stops the agent."""
        if chat_session_id in self.session_contexts:
            await self.session_contexts[chat_session_id].abort()
            del self.session_contexts[chat_session_id]

    async def clear_queue(self, chat_session_id: str) -> int:
        """Clears the queue for a session."""
        if chat_session_id in self.session_contexts:
            size = self.session_contexts[chat_session_id].queue.qsize()
            while not self.session_contexts[chat_session_id].queue.empty():
                self.session_contexts[chat_session_id].queue.get_nowait()
            return size
        return 0

    async def cleanup_session(self, session_id: str) -> None:
        """Kills the subprocess and cleans up memory."""
        if session_id in self.session_contexts:
            await self.session_contexts[session_id].cleanup()
            del self.session_contexts[session_id]
            logger.info(f"Cleaned up agent session {session_id}")

    async def get_available_models(
        self, chat_workspace_id: str, chat_session_id: str
    ) -> List[Dict[str, Any]]:
        """Returns available models for the given session."""
        if chat_session_id not in self.session_contexts:
            return []

        context = self.session_contexts[chat_session_id]
        if not context.agent:
            return []

        options = await context.agent.get_config_options(context.session)
        # Filter for 'model' category or specifically 'model' id
        models = [
            opt
            for opt in options
            if opt.get("category") == "model" or opt.get("id") == "model"
        ]
        return models

    async def set_model(
        self, chat_workspace_id: str, chat_session_id: str, model_id: str
    ) -> bool:
        """Sets the model for the session and persists it for the workspace."""
        if chat_session_id not in self.session_contexts:
            return False

        context = self.session_contexts[chat_session_id]
        if not context.agent:
            return False

        # 1. Update active agent
        await context.agent.set_config_option(context.session, "model", model_id)

        # 2. Persist in config
        if self.config_registry:
            workspace = context.workspace
            platform = getattr(self.chat_adapter, "config_key", "default")
            p_config = self.config_registry.for_platform(platform)
            p_config.set_workspace_setting(workspace.id, "model", model_id)

        return True
