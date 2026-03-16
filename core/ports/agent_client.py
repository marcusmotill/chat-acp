from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, List, Callable, Awaitable
from core.models import Session, Workspace, StreamChunk

# Define a type for the callback function that the agent uses to request user action
PromptTurnCallback = Callable[[Session, Dict[str, Any]], Awaitable[Dict[str, Any]]]


class AgentClientProtocol(ABC):
    """
    Abstract Base Class for Agent Client Adapter.
    Defines the contract for communicating with an ACP agent.
    """

    @abstractmethod
    def set_user_interaction_callback(self, callback: PromptTurnCallback) -> None:
        """Sets the function to call when the agent needs user action (e.g., prompt_turn)."""
        pass

    @abstractmethod
    async def start_session(self, session: Session, workspace: Workspace) -> None:
        """
        Initializes the agent process for an ephemeral session context.
        Sends protocol initialize and session/new commands.
        """
        pass

    @abstractmethod
    async def prompt(
        self, session: Session, message: str
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Sends a session/prompt to the agent and yields a stream of structured StreamChunk objects
        based on the agent's session/update notifications until the turn concludes.
        """
        pass

    @abstractmethod
    async def cancel_prompt(self, session: Session) -> None:
        """Forcefully stops the current agent thinking/output process."""
        pass

    @abstractmethod
    async def get_config_options(self, session: Session) -> List[Dict[str, Any]]:
        """Returns the available configuration options (e.g. models) for the session."""
        pass

    @abstractmethod
    async def set_config_option(
        self, session: Session, config_id: str, value: Any
    ) -> bool:
        """Sets a configuration option for the session."""
        pass

    @abstractmethod
    async def stop_session(self, session: Session) -> None:
        """
        Gracefully terminates the agent process for the given session.
        """
        pass
