import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from core.ports.config import PlatformConfig, ConfigProtocol

logger = logging.getLogger(__name__)

class FilePlatformConfig(PlatformConfig):
    """
    Implementation of PlatformConfig that proxies to a FileConfig instance.
    """
    def __init__(self, owner: 'FileConfig', platform: str):
        self.owner = owner
        self.platform = platform

    def get_setting(self, key: str) -> Optional[str]:
        platform_data = self.owner.data.get(self.platform)
        if isinstance(platform_data, dict):
            return platform_data.get(key)
        return None

    def set_setting(self, key: str, value: str) -> None:
        if self.platform not in self.owner.data:
            self.owner.data[self.platform] = {}
        if not isinstance(self.owner.data[self.platform], dict):
            self.owner.data[self.platform] = {}
            
        self.owner.data[self.platform][key] = value
        self.owner.save()

    def get_workspaces(self) -> Dict[str, str]:
        platform_data = self.owner.data.get(self.platform)
        if isinstance(platform_data, dict):
            workspaces = platform_data.get("workspaces", {})
            # Return channel_id -> path mapping
            result = {}
            for cid, data in workspaces.items():
                if isinstance(data, dict):
                    result[cid] = data.get("path", "")
                else:
                    result[cid] = data
            return result
        return {}

    def get_workspace_setting(self, channel_id: str, key: str) -> Optional[str]:
        platform_data = self.owner.data.get(self.platform)
        if isinstance(platform_data, dict):
            workspaces = platform_data.get("workspaces", {})
            ws_data = workspaces.get(channel_id)
            if isinstance(ws_data, dict):
                return ws_data.get("settings", {}).get(key)
        return None

    def set_workspace_setting(self, channel_id: str, key: str, value: str) -> None:
        if self.platform not in self.owner.data:
            self.owner.data[self.platform] = {}
        if not isinstance(self.owner.data[self.platform], dict):
            self.owner.data[self.platform] = {}
            
        if "workspaces" not in self.owner.data[self.platform]:
            self.owner.data[self.platform]["workspaces"] = {}
            
        workspaces = self.owner.data[self.platform]["workspaces"]
        if channel_id not in workspaces:
            # We don't have a path yet, but we can still store a setting if needed
            # though usually workspace is added first.
            workspaces[channel_id] = {"path": "", "settings": {}}
            
        ws_data = workspaces[channel_id]
        if not isinstance(ws_data, dict):
            # Migrate flat path to dict
            workspaces[channel_id] = {"path": ws_data, "settings": {}}
            ws_data = workspaces[channel_id]
            
        if "settings" not in ws_data:
            ws_data["settings"] = {}
            
        ws_data["settings"][key] = value
        self.owner.save()

    def add_workspace(self, channel_id: str, target_path: str) -> None:
        if self.platform not in self.owner.data:
            self.owner.data[self.platform] = {}
        if not isinstance(self.owner.data[self.platform], dict):
            self.owner.data[self.platform] = {}
            
        if "workspaces" not in self.owner.data[self.platform]:
            self.owner.data[self.platform]["workspaces"] = {}
            
        workspaces = self.owner.data[self.platform]["workspaces"]
        if channel_id in workspaces and isinstance(workspaces[channel_id], dict):
            workspaces[channel_id]["path"] = target_path
        else:
            workspaces[channel_id] = {"path": target_path, "settings": {}}
            
        self.owner.save()

class FileConfig(ConfigProtocol):
    """
    JSON file implementation of ConfigProtocol.
    Default path is ~/.chat-acp/config.json
    """
    def __init__(self, config_path: str = None):
        if config_path:
            self.config_path = str(Path(config_path).absolute())
            self.config_dir = os.path.dirname(self.config_path)
        else:
            self.home_dir = Path.home()
            self.config_dir = str(self.home_dir / ".chat-acp")
            self.config_path = str(Path(self.config_dir) / "config.json")

        # Start with generic structure; platforms like 'discord' are added dynamically
        self.data: Dict = {
            "agent_command": [],
            "agent_env": {}
        }

    def merge_defaults(self, defaults: Dict) -> None:
        """Merges default values into the data if they don't already exist."""
        def deep_merge(target, source):
            for key, value in source.items():
                if key not in target:
                    target[key] = value
                elif isinstance(value, dict) and isinstance(target[key], dict):
                    deep_merge(target[key], value)
        
        deep_merge(self.data, defaults)
        self.save()

    def load(self) -> None:
        if not os.path.exists(self.config_path):
            logger.info(f"No config found at {self.config_path}, using defaults.")
            return

        try:
            with open(self.config_path, "r") as f:
                loaded_data = json.load(f)
                
                # Migration: 
                # 1. discord_bot_token (legacy root) -> discord.token (new namespaced)
                if "discord_bot_token" in loaded_data:
                    logger.info("Migrating root 'discord_bot_token' to 'discord.token'")
                    if "discord" not in loaded_data:
                        loaded_data["discord"] = {}
                    loaded_data["discord"]["token"] = loaded_data.pop("discord_bot_token")

                # 2. bot_token (platform subkey) -> token (generic namespaced key)
                # Universal migration for all platforms
                for platform, p_data in loaded_data.items():
                    if isinstance(p_data, dict) and "bot_token" in p_data:
                        logger.info(f"Migrating '{platform}.bot_token' to '{platform}.token'")
                        p_data["token"] = p_data.pop("bot_token")

                # 3. workspaces (root) -> discord.workspaces
                if "workspaces" in loaded_data:
                    ws_root = loaded_data.pop("workspaces")
                    if isinstance(ws_root, dict):
                        # If it was already namespaced by platform (like the last implementation)
                        if "discord" in ws_root:
                            logger.info("Migrating 'workspaces.discord' to 'discord.workspaces'")
                            if "discord" not in loaded_data:
                                loaded_data["discord"] = {}
                            loaded_data["discord"]["workspaces"] = ws_root["discord"]
                        else:
                            # It was a flat dict channel_id -> path
                            logger.info("Migrating flat 'workspaces' to 'discord.workspaces'")
                            if "discord" not in loaded_data:
                                loaded_data["discord"] = {}
                            loaded_data["discord"]["workspaces"] = ws_root

                # 4. Migrate flat workspace paths to nested dicts
                for platform, p_data in loaded_data.items():
                    if isinstance(p_data, dict) and "workspaces" in p_data:
                        workspaces = p_data["workspaces"]
                        if isinstance(workspaces, dict):
                            for cid, target in workspaces.items():
                                if not isinstance(target, dict):
                                    workspaces[cid] = {"path": target, "settings": {}}

                self.data.update(loaded_data)
                logger.info(f"Loaded config from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load config from {self.config_path}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.data, f, indent=4)
                logger.info(f"Saved config to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config to {self.config_path}: {e}")

    def for_platform(self, platform: str) -> FilePlatformConfig:
        return FilePlatformConfig(self, platform)

    def get_agent_command(self) -> Optional[List[str]]:
        return self.data.get("agent_command")

    def set_agent_command(self, command: List[str]) -> None:
        self.data["agent_command"] = command
        self.save()

    def get_agent_env(self) -> Optional[Dict[str, str]]:
        return self.data.get("agent_env")

    def set_agent_env(self, env: Dict[str, str]) -> None:
        self.data["agent_env"] = env
        self.save()
