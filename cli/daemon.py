import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


class DaemonManager:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path.home() / ".chat-acp" / "pids"
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_pid_file(self, platform: str) -> Path:
        return self.base_dir / f"{platform}.pid"

    def _get_log_file(self, platform: str) -> Path:
        log_dir = self.base_dir.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{platform}.log"

    def start(self, platform: str, args: list) -> None:
        """Spawn the process in the background and save its PID."""
        pid_file = self._get_pid_file(platform)
        if pid_file.exists():
            if self.is_running(platform):
                pid = int(pid_file.read_text())
                print(f"Platform '{platform}' is already running (PID: {pid}).")
                return
            else:
                pid_file.unlink()

        log_file = self._get_log_file(platform)

        # Wrapped in a simple restart loop for resiliency
        # We spawn a 'watcher' process or just let the process self-restart?
        # A simple way is to spawn a shell script or a python script that loops.
        # But for now, let's keep it simple and just ensure it starts.

        cmd = [sys.executable] + args

        env = os.environ.copy()
        # Set an environment variable to indicate it's a daemon child to avoid infinite recursion
        env["CHAT_ACP_DAEMON"] = "1"

        with open(log_file, "a") as log:
            log.write(f"\n--- Starting daemon at {time.ctime()} ---\n")
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )

        pid_file.write_text(str(process.pid))
        print(f"Started '{platform}' in background (PID: {process.pid}).")
        print(f"Logs: {log_file}")

    def stop(self, platform: str) -> None:
        """Stop the background process."""
        pid_file = self._get_pid_file(platform)
        if not pid_file.exists():
            print(f"No PID file found for '{platform}'. Is it running?")
            return

        pid = int(pid_file.read_text())
        try:
            # Terminate the process and its children
            os.kill(pid, signal.SIGTERM)
            print(f"Stopped '{platform}' (PID: {pid}).")
        except ProcessLookupError:
            print(f"Process {pid} not found. Cleaning up stale PID file.")
        except Exception as e:
            print(f"Error stopping '{platform}': {e}")
        finally:
            if pid_file.exists():
                pid_file.unlink()

    def status(self, platform: str) -> bool:
        """Check if the platform is running."""
        pid_file = self._get_pid_file(platform)
        if not pid_file.exists():
            print(f"'{platform}' is NOT running.")
            return False

        pid = int(pid_file.read_text())
        if self.is_running(platform):
            print(f"'{platform}' is running (PID: {pid}).")
            return True
        else:
            print(f"'{platform}' is NOT running (stale PID: {pid}).")
            pid_file.unlink()
            return False

    def is_running(self, platform: str) -> bool:
        pid_file = self._get_pid_file(platform)
        if not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text())
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, ValueError):
            return False
