from typing import Optional, Dict
from core.ports.config import PlatformConfig


class DiscordConfig:
    """
    A typed wrapper for Discord-specific configuration stored in a PlatformConfig.
    """

    def __init__(self, platform_config: PlatformConfig):
        self._cfg = platform_config

    @property
    def token(self) -> Optional[str]:
        """Returns the Discord bot token."""
        return self._cfg.get_setting("token")

    @token.setter
    def token(self, value: str):
        """Saves the Discord bot token."""
        self._cfg.set_setting("token", value)

    def get_workspaces(self) -> Dict[str, str]:
        """Returns the standardized workspaces."""
        return self._cfg.get_workspaces()

    def add_workspace(self, channel_id: str, target_path: str) -> None:
        """Adds a standardized workspace."""
        self._cfg.add_workspace(channel_id, target_path)
