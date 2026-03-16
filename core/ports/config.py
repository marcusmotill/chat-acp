from typing import List, Dict, Optional, Protocol

class PlatformConfig(Protocol):
    """
    Protocol for a platform-specific configuration view.
    """
    def get_setting(self, key: str) -> Optional[str]:
        """Returns a generic setting for this platform."""
        ...

    def set_setting(self, key: str, value: str) -> None:
        """Saves a generic setting for this platform."""
        ...

    def get_workspaces(self) -> Dict[str, str]:
        """Returns a mapping of channel_id -> target_path for this platform."""
        ...

    def add_workspace(self, channel_id: str, target_path: str) -> None:
        """Adds or updates a workspace mapping for this platform."""
        ...

    def get_workspace_setting(self, channel_id: str, key: str) -> Optional[str]:
        """Returns a setting for a specific workspace on this platform."""
        ...

    def set_workspace_setting(self, channel_id: str, key: str, value: str) -> None:
        """Saves a setting for a specific workspace on this platform."""
        ...

class ConfigProtocol(Protocol):
    """
    Protocol for persistent configuration storage.
    """
    def for_platform(self, platform: str) -> PlatformConfig:
        """Returns a typed view for the specific platform."""
        ...

    def get_agent_command(self) -> Optional[List[str]]:
        """Returns the stored agent command list."""
        ...

    def set_agent_command(self, command: List[str]) -> None:
        """Saves the agent command list."""
        ...

    def get_agent_env(self) -> Optional[Dict[str, str]]:
        """Returns the stored agent environment variables."""
        ...

    def set_agent_env(self, env: Dict[str, str]) -> None:
        """Saves the agent environment variables."""
        ...

    def load(self) -> None:
        """Loads config from disk."""
        ...

    def save(self) -> None:
        """Saves config to disk."""
        ...
