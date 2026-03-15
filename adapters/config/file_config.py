import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from core.ports.config import ConfigProtocol

logger = logging.getLogger(__name__)

class FileConfig(ConfigProtocol):
    """
    JSON file implementation of ConfigProtocol.
    Default path is ~/.chat-acp/config.json
    """
    def __init__(self, config_path: str = None):
        if config_path is None:
            self.home_dir = Path.home()
            self.config_dir = str(self.home_dir / ".chat-acp")
            self.config_path = str(Path(self.config_dir) / "config.json")
        else:
            self.config_path = config_path
            self.config_dir = os.path.dirname(self.config_path)

        self.data: Dict = {
            "agent_command": [],
            "workspaces": {}
        }

    def load(self) -> None:
        if not os.path.exists(self.config_path):
            logger.info(f"No config found at {self.config_path}, using defaults.")
            return

        try:
            with open(self.config_path, "r") as f:
                loaded_data = json.load(f)
                
                # Migration: If workspaces is a flat dict, move it under "discord"
                workspaces = loaded_data.get("workspaces", {})
                if workspaces and not any(isinstance(v, dict) for v in workspaces.values()):
                    logger.info("Migrating legacy flat workspace config to namespaced 'discord' key.")
                    loaded_data["workspaces"] = {"discord": workspaces}
                
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

    def get_agent_command(self) -> Optional[List[str]]:
        return self.data.get("agent_command")

    def set_agent_command(self, command: List[str]) -> None:
        self.data["agent_command"] = command
        self.save()

    def get_workspaces(self, platform: str) -> Dict[str, str]:
        all_workspaces = self.data.get("workspaces", {})
        return all_workspaces.get(platform, {})

    def add_workspace(self, platform: str, channel_id: str, target_path: str) -> None:
        if "workspaces" not in self.data:
            self.data["workspaces"] = {}
        if platform not in self.data["workspaces"]:
            self.data["workspaces"][platform] = {}
            
        self.data["workspaces"][platform][channel_id] = target_path
        self.save()
