from abc import ABC, abstractmethod
from typing import AsyncGenerator
from core.models import Session, Workspace

class ChatClientProtocol(ABC):
    """
    Interface for any chat client (e.g., Discord) connecting to the bridge.
    """
    
    @property
    @abstractmethod
    def config_key(self) -> str:
        """The configuration key used by this client (e.g., 'discord')."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Starts the chat bot daemon."""
        pass
        
    async def send_message(self, session: Session, content: str) -> None:
        """Sends a plain message back to the session context (thread)."""
        pass

    @abstractmethod
    async def trigger_typing(self, session: Session) -> None:
        """Triggers the 'typing...' indicator in the chat interface."""
        pass
        
    @abstractmethod
    async def stream_response(self, session: Session, stream: AsyncGenerator[str, None]) -> None:
        """
        Consumes an async generator of response text chunks from the agent and 
        streams them to the chat interface (handling limits like Discord's 2000 chars).
        """
        pass

    @abstractmethod
    async def get_or_create_session(self, workspace: Workspace, context_id: str, title: str) -> Session:
        """
        Retrieves or creates a session. 
        (e.g., Ensures a thread exists for the given message/invocation).
        """
        pass
