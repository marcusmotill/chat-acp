import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from adapters.agent.acp_stdio import AcpStdioAgent
from core.models import Session, Workspace


class TestAgentEnv(unittest.IsolatedAsyncioTestCase):
    async def test_agent_env_passing(self):
        agent_command = ["echo", "hello"]
        agent_env = {"TEST_VAR": "test_value"}
        workspace = Workspace(
            id="1", environment_id="env1", name="ws1", target_path="/tmp"
        )
        session = Session(id="sess1", workspace_id="1")

        agent = AcpStdioAgent(agent_command, agent_env)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock the process return
            mock_process = MagicMock()
            # Use AsyncMock for readline to avoid TypeError
            mock_process.stdout.readline = AsyncMock(return_value=b"")
            mock_process.stderr.readline = AsyncMock(return_value=b"")
            mock_exec.return_value = mock_process

            # We need to mock send_request because start_session calls it and awaits it
            with patch.object(
                AcpStdioAgent, "send_request", new_callable=AsyncMock
            ) as mock_send:
                mock_send.return_value = MagicMock(
                    error=None, result={"sessionId": "test-agent-session"}
                )

                try:
                    await agent.start_session(session, workspace)
                except Exception:
                    pass

            # Verify environment variables
            args, kwargs = mock_exec.call_args
            passed_env = kwargs.get("env")
            self.assertIsNotNone(passed_env)
            self.assertEqual(passed_env["TEST_VAR"], "test_value")
            self.assertIn("PATH", passed_env)


if __name__ == "__main__":
    unittest.main()
