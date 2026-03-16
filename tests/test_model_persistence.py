from adapters.config.file_config import FileConfig

def test_model_persistence(tmp_path):
    config_path = tmp_path / "persistence_config.json"
    cfg = FileConfig(config_path=str(config_path))
    
    platform_cfg = cfg.for_platform("discord")
    platform_cfg.add_workspace("channel_1", "/path/to/project")
    
    # Set model setting
    platform_cfg.set_workspace_setting("channel_1", "model", "claude-3-opus")
    
    # Reload config
    new_cfg = FileConfig(config_path=str(config_path))
    new_cfg.load()
    new_platform_cfg = new_cfg.for_platform("discord")
    
    # Verify setting persists
    assert new_platform_cfg.get_workspace_setting("channel_1", "model") == "claude-3-opus"
    
    # Verify path still works via flat getter
    workspaces = new_platform_cfg.get_workspaces()
    assert workspaces["channel_1"] == "/path/to/project"

def test_model_auto_migration_on_set(tmp_path):
    # Test that setting a setting on a legacy flat workspace entry migrates it
    config_path = tmp_path / "auto_migrate.json"
    with open(config_path, "w") as f:
        import json
        json.dump({"discord": {"workspaces": {"c1": "/old/path"}}}, f)
        
    cfg = FileConfig(config_path=str(config_path))
    cfg.load()
    platform_cfg = cfg.for_platform("discord")
    
    # This should trigger internal migration of "c1" to dict
    platform_cfg.set_workspace_setting("c1", "temp", "val")
    
    assert isinstance(cfg.data["discord"]["workspaces"]["c1"], dict)
    assert cfg.data["discord"]["workspaces"]["c1"]["path"] == "/old/path"
    assert cfg.data["discord"]["workspaces"]["c1"]["settings"]["temp"] == "val"
