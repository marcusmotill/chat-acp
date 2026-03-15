from typing import List, Dict, Optional, Protocol

class ConfigProtocol(Protocol):
    """
    Protocol for persistent configuration storage.
    """
    def get_agent_command(self) -> Optional[List[str]]:
        """Returns the stored agent command list."""
        ...

    def set_agent_command(self, command: List[str]) -> None:
        """Saves the agent command list."""
        ...

    def get_workspaces(self, platform: str) -> Dict[str, str]:
        """Returns a mapping of channel_id -> target_path for a platform."""
        ...

    def add_workspace(self, platform: str, channel_id: str, target_path: str) -> None:
        """Adds or updates a workspace mapping for a platform."""
        ...

    def load(self) -> None:
        """Loads config from disk."""
        ...

    def save(self) -> None:
        """Saves config to disk."""
        ...
