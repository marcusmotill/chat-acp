from abc import ABC, abstractmethod
from typing import AsyncGenerator
from core.models import Session, Workspace

class AgentClientProtocol(ABC):
    """
    Interface for communicating with an ACP compatible agent via a subprocess.
    """
    
    @abstractmethod
    async def start_session(self, session: Session, workspace: Workspace) -> None:
        """
        Initializes the agent process for an ephemeral session context.
        Sends protocol initialize and session/new commands.
        """
        pass

    @abstractmethod
    async def prompt(self, session: Session, message: str) -> AsyncGenerator[str, None]:
        """
        Sends a session/prompt to the agent and yields a stream of formatted response strings
        based on the agent's session/update notifications until the turn concludes.
        """
        pass

    @abstractmethod
    async def cancel_prompt(self, session: Session) -> None:
        """
        Sends a session/cancel notification to the agent to interrupt the current prompt turn.
        """
        pass
        
    @abstractmethod
    async def stop_session(self, session: Session) -> None:
        """
        Gracefully terminates the agent process for the given session.
        """
        pass
