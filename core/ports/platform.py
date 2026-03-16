from abc import ABC, abstractmethod
from typing import Any, Dict
from core.ports.config import ConfigProtocol


class ChatPlatform(ABC):
    """
    Interface for a chat platform bridge.
    Handles platform-specific initialization and bot execution.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name of the platform (e.g., 'discord')."""
        pass

    @abstractmethod
    async def start(self, config: ConfigProtocol) -> None:
        """Initialize and start the platform's bot/bridge."""
        pass

    def get_config_schema(self) -> Dict[str, Any]:
        """Optional: returns a schema for required configuration."""
        return {}
