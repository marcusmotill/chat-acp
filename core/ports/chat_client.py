from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, List
from core.models import Session, Workspace, StreamChunk, ChatMessage


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

    async def send_error(self, session: Session, content: str) -> None:
        """Sends a formatted error message to the session context (thread).

        Used for out-of-band errors that occur outside a prompt stream,
        such as config failures or agent stderr errors.
        Multi-line content should be wrapped in code blocks by the implementation.
        """
        pass

    @abstractmethod
    async def trigger_typing(self, session: Session) -> None:
        """Triggers the 'typing...' indicator in the chat interface."""
        pass

    @abstractmethod
    async def stream_response(
        self, session: Session, stream: AsyncGenerator[StreamChunk, None]
    ) -> None:
        """
        Consumes an async generator of StreamChunk objects from the agent and
        streams them to the chat interface.

        Special handling for chunk types:
        - 'status': Should update a single, persistent status message in place.
        - 'thought': Should update a single, persistent thought message in place.
        - 'text': Should be streamed normally.
        - The final response (after the generator is exhausted) should replace
          both the status and thought messages if they exist.
        """
        pass

    @abstractmethod
    async def await_action_from_user(
        self, session: Session, prompt_turn_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Pauses execution and waits for the user to provide an action (text or tool call)
        in response to the agent's prompt_turn request.

        :param session: The current session object.
        :param prompt_turn_params: The content of the 'params' field from the agent's prompt_turn request.
        :returns: A dictionary conforming to the JSON-RPC result structure (e.g., {"action": {"type": "text", "content": "..."}})
        """
        pass

    @abstractmethod
    async def get_or_create_session(
        self, workspace: Workspace, context_id: str, title: str
    ) -> Session:
        """
        Retrieves or creates a session.
        (e.g., Ensures a thread exists for the given message/invocation).
        """
        pass

    @abstractmethod
    async def get_history(self, session: Session, limit: int = 20) -> List[ChatMessage]:
        """
        Retrieves the recent message history for a session.
        Useful for restoring context after a bridge restart.
        """
        pass

    @abstractmethod
    async def notify(self, session: Session, message: str) -> None:
        """
        Sends a notification message to the session.
        This is typically used by background processes to "wake up" the agent.
        """
        pass
