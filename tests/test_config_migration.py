import pytest
import json
import os
from pathlib import Path
from adapters.config.file_config import FileConfig

@pytest.fixture
def temp_config(tmp_path):
    config_path = tmp_path / "config.json"
    return FileConfig(config_path=str(config_path))

def test_config_migration_legacy_token(tmp_path):
    config_path = tmp_path / "legacy_config.json"
    legacy_data = {
        "discord_bot_token": "secret_token_123",
        "agent_command": ["claude", "acp"]
    }
    config_path.write_text(json.dumps(legacy_data))
    
    cfg = FileConfig(config_path=str(config_path))
    cfg.load()
    
    assert "discord_bot_token" not in cfg.data
    assert cfg.data["discord"]["token"] == "secret_token_123"
    assert cfg.data["agent_command"] == ["claude", "acp"]

def test_config_migration_workspaces(tmp_path):
    config_path = tmp_path / "ws_config.json"
    legacy_data = {
        "workspaces": {
            "channel_1": "/path/to/ws1"
        }
    }
    config_path.write_text(json.dumps(legacy_data))
    
    cfg = FileConfig(config_path=str(config_path))
    cfg.load()
    
    assert "workspaces" not in cfg.data
    assert cfg.data["discord"]["workspaces"]["channel_1"] == "/path/to/ws1"

def test_nested_workspaces_migration(tmp_path):
    config_path = tmp_path / "nested_ws.json"
    legacy_data = {
        "workspaces": {
            "discord": {
                "c1": "/p1"
            }
        }
    }
    config_path.write_text(json.dumps(legacy_data))
    
    cfg = FileConfig(config_path=str(config_path))
    cfg.load()
    
    assert cfg.data["discord"]["workspaces"]["c1"] == "/p1"

def test_config_save_load(temp_config):
    temp_config.data["discord"] = {"token": "test", "workspaces": {}}
    temp_config.save()
    
    new_cfg = FileConfig(config_path=temp_config.config_path)
    new_cfg.load()
    assert new_cfg.data["discord"]["token"] == "test"
