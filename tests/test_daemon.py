import pytest
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch
from cli.daemon import DaemonManager

@pytest.fixture
def temp_daemon_manager(tmp_path):
    return DaemonManager(base_dir=tmp_path / "pids")

def test_pid_file_handling(temp_daemon_manager, tmp_path):
    platform = "test_bot"
    pid_file = temp_daemon_manager._get_pid_file(platform)
    
    # Test internal helper
    assert pid_file.name == "test_bot.pid"
    
    # Test log file creation
    log_file = temp_daemon_manager._get_log_file(platform)
    assert log_file.exists() == False
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch()
    assert log_file.exists() == True

@patch("subprocess.Popen")
@patch("os.kill")
def test_daemon_start_already_running(mock_kill, mock_popen, temp_daemon_manager):
    platform = "running_bot"
    pid_file = temp_daemon_manager._get_pid_file(platform)
    pid_file.write_text("12345")
    
    # Mock os.kill(12345, 0) to return True (running)
    mock_kill.return_value = None 
    
    temp_daemon_manager.start(platform, ["arg1"])
    mock_popen.assert_not_called()

@patch("subprocess.Popen")
@patch("os.kill")
def test_daemon_stop(mock_kill, mock_popen, temp_daemon_manager):
    platform = "stop_bot"
    pid_file = temp_daemon_manager._get_pid_file(platform)
    pid_file.write_text("54321")
    
    temp_daemon_manager.stop(platform)
    mock_kill.assert_called_with(54321, signal.SIGTERM)
    assert not pid_file.exists()

def test_daemon_status_not_running(temp_daemon_manager):
    assert temp_daemon_manager.status("missing") == False

@patch("os.kill")
def test_is_running(mock_kill, temp_daemon_manager):
    platform = "alive_bot"
    pid_file = temp_daemon_manager._get_pid_file(platform)
    pid_file.write_text("999")
    
    # Success (process exists)
    mock_kill.return_value = None
    assert temp_daemon_manager.is_running(platform) == True
    
    # Failure (process doesn't exist)
    mock_kill.side_effect = ProcessLookupError()
    assert temp_daemon_manager.is_running(platform) == False
