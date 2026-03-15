import asyncio
import logging
from typing import Dict, Optional, Callable
from core.models import Session, Workspace, ChatMessage
from core.ports.agent_client import AgentClientProtocol
from core.ports.chat_client import ChatClientProtocol

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
        on_workspace_registered: Optional[Callable[[str, str], None]] = None
    ):
        self.chat_adapter = chat_adapter
        self.agent_factory = agent_factory
        self.on_workspace_registered = on_workspace_registered
        
        # Registry of active workspaces by chat source mapping
        self.workspaces: Dict[str, Workspace] = {}
        
        # Registry of active session/threads mapped to their Agent adapters
        self.active_agents: Dict[str, AgentClientProtocol] = {}
        # Registry of active Sessions
        self.sessions: Dict[str, Session] = {}
        # Message queues per session: session_id -> List[tuple(message, workspace_id, session_id, session_name)]
        self.queues: Dict[str, asyncio.Queue] = {}
        # Locking/Busy state per session
        self.busy: Dict[str, bool] = {}

    def register_workspace(self, chat_workspace_id: str, workspace: Workspace) -> None:
        """Registers a chat's workspace identifier to a specific local project directory Workspace."""
        self.workspaces[chat_workspace_id] = workspace
        logger.info(f"Registered Workspace '{workspace.name}' to chat workspace {chat_workspace_id}")
        if self.on_workspace_registered:
            self.on_workspace_registered(chat_workspace_id, workspace.target_path)

    def get_workspace(self, chat_workspace_id: str) -> Optional[Workspace]:
        return self.workspaces.get(chat_workspace_id)

    async def handle_chat_message(self, message: ChatMessage, chat_workspace_id: str, chat_session_id: str, chat_session_name: str) -> None:
        """
        Entry pipeline from the Chat Client Adapter.
        1. Validates the channel has a workspace
        2. Gets or creates the Session (Thread)
        3. Initializes the Agent Client if not already running for this Session
        4. Sends the prompt to the Agent
        5. Streams the response back to the Chat Adapter
        """
        workspace = self.get_workspace(chat_workspace_id)
        if not workspace:
            logger.debug(f"Message in unmapped chat workspace {chat_workspace_id}, ignoring.")
            return

        # Let the Chat Adapter give us the Session context
        session = await self.chat_adapter.get_or_create_session(
            workspace=workspace, 
            context_id=chat_session_id, 
            title=chat_session_name
        )
        self.sessions[session.id] = session

        # If already busy, add to queue
        if self.busy.get(session.id):
            if session.id not in self.queues:
                self.queues[session.id] = asyncio.Queue()
            await self.queues[session.id].put((message, chat_workspace_id, chat_session_id, chat_session_name))
            await self.chat_adapter.send_message(session, "⏳ Agent is busy. Message queued.")
            return

        self.busy[session.id] = True
        try:
            await self._execute_prompt(session, workspace, message)
            # Process queue if any
            while session.id in self.queues and not self.queues[session.id].empty():
                next_msg_data = await self.queues[session.id].get()
                m, ws_id, s_id, s_name = next_msg_data
                await self._execute_prompt(session, workspace, m)
        finally:
            self.busy[session.id] = False

    async def _execute_prompt(self, session: Session, workspace: Workspace, message: ChatMessage):
        """Internal execution of a prompt."""
        # Start agent if not active
        if session.id not in self.active_agents:
            agent = self.agent_factory(workspace)
            await agent.start_session(session, workspace)
            self.active_agents[session.id] = agent
        
        agent = self.active_agents[session.id]
        
        # Route prompt and pipe response stream back
        try:
            await self.chat_adapter.trigger_typing(session)
            response_stream = agent.prompt(session, message.content)
            await self.chat_adapter.stream_response(session, response_stream)
        except Exception as e:
            logger.error(f"Error handling agent prompt: {e}")
            await self.chat_adapter.send_message(session, f"❌ Agent encountered an error: {e}")

    async def abort_session(self, chat_session_id: str) -> None:
        """Cancels any current prompt and stops the agent."""
        if chat_session_id in self.active_agents:
            agent = self.active_agents[chat_session_id]
            session = self.sessions.get(chat_session_id)
            if session:
                await agent.cancel_prompt(session)
                await asyncio.sleep(0.5) # Give it a moment to stop
                await agent.stop_session(session)
            del self.active_agents[chat_session_id]
            if chat_session_id in self.busy:
                self.busy[chat_session_id] = False
            if chat_session_id in self.queues:
                del self.queues[chat_session_id]
            logger.info(f"Aborted session {chat_session_id}")

    async def clear_queue(self, chat_session_id: str) -> int:
        """Clears the queue for a session."""
        if chat_session_id in self.queues:
            size = self.queues[chat_session_id].qsize()
            del self.queues[chat_session_id]
            return size
        return 0

    async def cleanup_session(self, session_id: str) -> None:
        """Kills the subprocess and cleans up memory."""
        if session_id in self.active_agents:
            agent = self.active_agents[session_id]
            session = self.sessions.get(session_id)
            if session:
                await agent.stop_session(session)
            del self.active_agents[session_id]
            logger.info(f"Cleaned up agent session {session_id}")
