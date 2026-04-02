"""
Tests for error reporting: stderr detection, error chunks in prompts,
ACP-spec-correct set_config_option, and error surfacing to chat.
"""

import pytest
from unittest.mock import MagicMock
from typing import AsyncGenerator, Dict, Any, List

from core.models import Workspace, Session, ChatMessage, StreamChunk
from core.orchestrator import SessionManager
from core.ports.chat_client import ChatClientProtocol
from core.ports.agent_client import AgentClientProtocol, PromptTurnCallback
from core.exceptions import AgentExecutionError
from adapters.agent.acp_stdio import (
    AcpStdioAgent,
    JsonRpcMethods,
    METHOD_NOT_FOUND_CODE,
)
from adapters.agent.jsonrpc import JsonRpcResponse


# ──────────────────────────────────────────────────────────────────────
# Mock Helpers
# ──────────────────────────────────────────────────────────────────────


class MockChatClient(ChatClientProtocol):
    def __init__(self):
        self.sent_messages = []
        self.sent_errors = []
        self.streamed_chunks = []

    @property
    def config_key(self) -> str:
        return "mock"

    async def start(self) -> None:
        pass

    async def send_message(self, session: Session, content: str) -> None:
        self.sent_messages.append((session.id, content))

    async def send_error(self, session: Session, content: str) -> None:
        self.sent_errors.append((session.id, content))

    async def trigger_typing(self, session: Session) -> None:
        pass

    async def stream_response(
        self, session: Session, stream: AsyncGenerator[StreamChunk, None]
    ) -> None:
        async for chunk in stream:
            self.streamed_chunks.append((session.id, chunk))

    async def get_history(self, session: Session, limit: int = 20) -> List[ChatMessage]:
        return []

    async def await_action_from_user(
        self, session: Session, prompt_turn_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"action": {"type": "text", "content": "ok"}}

    async def get_or_create_session(
        self, workspace: Workspace, context_id: str, title: str
    ) -> Session:
        return Session(id=context_id, workspace_id=workspace.id)

    async def notify(self, session: Session, message: str) -> None:
        self.sent_messages.append(("NOTIFICATION", session.id, message))


class MockAgentClientWithConfigError(AgentClientProtocol):
    """Agent mock that raises AgentExecutionError on set_config_option."""

    def __init__(self, error_message: str = "Agent not found: bad-model"):
        self.started = False
        self.error_message = error_message

    def set_user_interaction_callback(self, callback: PromptTurnCallback) -> None:
        pass

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        self.started = True

    async def cancel_prompt(self, session: Session) -> None:
        pass

    async def prompt(
        self, session: Session, message: str
    ) -> AsyncGenerator[StreamChunk, None]:
        yield StreamChunk(type="text", content="response")

    async def stop_session(self, session: Session) -> None:
        pass

    async def get_config_options(self, session: Session) -> List[Dict[str, Any]]:
        return []

    async def set_config_option(
        self, session: Session, config_id: str, value: Any
    ) -> bool:
        raise AgentExecutionError(self.error_message)


# ──────────────────────────────────────────────────────────────────────
# Stderr Suppression Tests
# ──────────────────────────────────────────────────────────────────────


class TestStderrSuppression:
    def test_flag_defaults_to_false(self):
        agent = AcpStdioAgent(["echo"])
        assert agent._suppress_stderr is False

    @pytest.mark.asyncio
    async def test_probing_sets_and_clears_flag(self):
        """set_config_option sets _suppress_stderr during probing, clears after."""
        agent = AcpStdioAgent(["echo"])
        agent._agent_session_id = "ses_test"
        agent._config_options = [
            {"id": "model", "name": "Model", "category": "model"},
        ]

        flag_values_during_probe = []

        async def mock_send_request(method, params=None):
            # Capture the flag value when the request is sent
            flag_values_during_probe.append(agent._suppress_stderr)
            return JsonRpcResponse(
                id=1,
                error={"code": METHOD_NOT_FOUND_CODE, "message": "Method not found"},
            )

        agent.send_request = mock_send_request

        await agent.set_config_option(
            Session(id="s1", workspace_id="w1"), "model", "gpt-4"
        )

        # Flag should have been True during probing
        assert all(v is True for v in flag_values_during_probe)
        # Flag should be False after probing completes
        assert agent._suppress_stderr is False


# ──────────────────────────────────────────────────────────────────────
# set_config_option ACP Spec Compliance Tests
# ──────────────────────────────────────────────────────────────────────


class TestSetConfigOptionSpec:
    """Tests that set_config_option follows the ACP spec correctly."""

    @pytest.fixture
    def agent(self):
        a = AcpStdioAgent(["echo"])
        a._agent_session_id = "ses_test123"
        a._config_options = [
            {"id": "model", "name": "Model", "category": "model", "options": []},
        ]
        return a

    @pytest.mark.asyncio
    async def test_uses_set_config_option_first(self, agent):
        """Primary method should be session/set_config_option per ACP spec."""
        calls = []

        async def mock_send_request(method, params=None):
            calls.append(method)
            return JsonRpcResponse(id=1, result={"configOptions": []})

        agent.send_request = mock_send_request

        result = await agent.set_config_option(
            Session(id="s1", workspace_id="w1"), "model", "gpt-4"
        )

        assert result is True
        assert calls == [JsonRpcMethods.SESSION_SET_CONFIG]

    @pytest.mark.asyncio
    async def test_falls_back_to_set_mode_on_method_not_found(self, agent):
        """If set_config_option returns -32601, fall back to session/set_mode."""
        calls = []

        async def mock_send_request(method, params=None):
            calls.append(method)
            if method == JsonRpcMethods.SESSION_SET_CONFIG:
                return JsonRpcResponse(
                    id=1,
                    error={
                        "code": METHOD_NOT_FOUND_CODE,
                        "message": "Method not found",
                    },
                )
            # set_mode succeeds
            return JsonRpcResponse(id=2, result={"configOptions": []})

        agent.send_request = mock_send_request

        result = await agent.set_config_option(
            Session(id="s1", workspace_id="w1"), "model", "gpt-4"
        )

        assert result is True
        assert JsonRpcMethods.SESSION_SET_CONFIG in calls
        assert JsonRpcMethods.SESSION_SET_MODE in calls

    @pytest.mark.asyncio
    async def test_caches_successful_method(self, agent):
        """Once a method works, it should be cached and used directly."""
        calls = []

        async def mock_send_request(method, params=None):
            calls.append(method)
            return JsonRpcResponse(id=1, result={"configOptions": []})

        agent.send_request = mock_send_request
        session = Session(id="s1", workspace_id="w1")

        await agent.set_config_option(session, "model", "gpt-4")
        calls.clear()

        await agent.set_config_option(session, "model", "gpt-3.5")

        # Second call should go straight to cached method
        assert len(calls) == 1
        assert calls[0] == JsonRpcMethods.SESSION_SET_CONFIG

    @pytest.mark.asyncio
    async def test_raises_on_real_error(self, agent):
        """Real errors (not Method not found) should raise AgentExecutionError."""

        async def mock_send_request(method, params=None):
            return JsonRpcResponse(
                id=1,
                error={
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"details": "Agent not found: bad-model"},
                },
            )

        agent.send_request = mock_send_request

        with pytest.raises(AgentExecutionError, match="Agent not found"):
            await agent.set_config_option(
                Session(id="s1", workspace_id="w1"), "model", "bad-model"
            )

    @pytest.mark.asyncio
    async def test_does_not_try_invented_methods(self, agent):
        """Should NOT try session/set_model or session/set-model (not in ACP spec)."""
        calls = []

        async def mock_send_request(method, params=None):
            calls.append(method)
            return JsonRpcResponse(
                id=1,
                error={"code": METHOD_NOT_FOUND_CODE, "message": "Method not found"},
            )

        agent.send_request = mock_send_request

        result = await agent.set_config_option(
            Session(id="s1", workspace_id="w1"), "model", "gpt-4"
        )

        assert result is False
        # Only spec methods should be tried
        for method_called in calls:
            assert method_called in (
                JsonRpcMethods.SESSION_SET_CONFIG,
                JsonRpcMethods.SESSION_SET_MODE,
            ), f"Unexpected method called: {method_called}"

    @pytest.mark.asyncio
    async def test_no_session_returns_false(self, agent):
        """Returns False when no agent session is active."""
        agent._agent_session_id = None
        result = await agent.set_config_option(
            Session(id="s1", workspace_id="w1"), "model", "gpt-4"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_cached_path_skips_suppression(self, agent):
        """Cached method path should not toggle suppress/drain."""

        async def mock_send_request(method, params=None):
            return JsonRpcResponse(id=1, result={"configOptions": []})

        agent.send_request = mock_send_request
        session = Session(id="s1", workspace_id="w1")

        # First call probes (sets _suppress_stderr)
        await agent.set_config_option(session, "model", "gpt-4")

        # Now it's cached — second call should NOT touch _suppress_stderr
        suppress_was_set = False
        original_drain = agent._drain_error_queue

        def spy_drain():
            nonlocal suppress_was_set
            suppress_was_set = True
            original_drain()

        agent._drain_error_queue = spy_drain
        await agent.set_config_option(session, "model", "gpt-3.5")

        assert not suppress_was_set, "Cached path should not drain error queue"


# ──────────────────────────────────────────────────────────────────────
# Orchestrator Error Surfacing Tests
# ──────────────────────────────────────────────────────────────────────


class TestOrchestratorErrorSurfacing:
    @pytest.mark.asyncio
    async def test_set_model_surfaces_error_to_chat(self):
        """When agent raises on set_config_option, orchestrator should send_error."""
        chat_mock = MockChatClient()
        error_agent = MockAgentClientWithConfigError("Agent not found: bad-model")

        manager = SessionManager(chat_mock, lambda ws: error_agent)
        workspace = Workspace(
            id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
        )
        manager.register_workspace("ws_1", workspace)

        # Start a session by sending a message
        msg = ChatMessage(
            id="m1", session_id="s1", content="hi", author_id="u", author_name="A"
        )
        await manager.handle_chat_message(msg, "ws_1", "s1", "S1")

        # Now try to set a bad model
        result = await manager.set_model("ws_1", "s1", "bad-model")

        assert result is False
        assert len(chat_mock.sent_errors) == 1
        assert "bad-model" in chat_mock.sent_errors[0][1]

    @pytest.mark.asyncio
    async def test_set_model_returns_false_no_session(self):
        """set_model returns False when no session exists."""
        chat_mock = MockChatClient()
        manager = SessionManager(chat_mock, lambda ws: MockAgentClientWithConfigError())
        result = await manager.set_model("ws_1", "nonexistent", "gpt-4")
        assert result is False


# ──────────────────────────────────────────────────────────────────────
# Session Context Error Surfacing Tests
# ──────────────────────────────────────────────────────────────────────


class TestSessionContextErrorSurfacing:
    @pytest.mark.asyncio
    async def test_auto_apply_model_failure_surfaces_to_chat(self):
        """When auto-applying a saved model fails, error should be sent to chat."""
        from core.session_context import SessionContext

        chat_mock = MockChatClient()
        error_agent = MockAgentClientWithConfigError("Agent not found: bad-model")

        # Make the agent's start_session a no-op
        async def noop_start(session, workspace):
            pass

        error_agent.start_session = noop_start

        session = Session(id="s1", workspace_id="ws_1")
        workspace = Workspace(
            id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
        )

        context = SessionContext(
            session=session,
            workspace=workspace,
            agent_factory=lambda ws: error_agent,
            chat_adapter=chat_mock,
            initial_model="bad-model",
        )

        # _ensure_agent_started will create the agent and try to auto-apply model
        await context._ensure_agent_started()

        # Should have surfaced the error
        assert len(chat_mock.sent_errors) == 1
        assert "bad-model" in chat_mock.sent_errors[0][1]


# ──────────────────────────────────────────────────────────────────────
# Error Chunk in Stream Tests
# ──────────────────────────────────────────────────────────────────────


class TestErrorChunks:
    def test_error_stream_chunk_type(self):
        """StreamChunk should accept 'error' type."""
        chunk = StreamChunk(type="error", content="Something went wrong")
        assert chunk.type == "error"
        assert chunk.content == "Something went wrong"

    @pytest.mark.asyncio
    async def test_error_queue_drained_during_prompt(self):
        """Error queue items should be yielded during prompt streaming."""
        agent = AcpStdioAgent(["echo"])
        agent._agent_session_id = "ses_test"

        # Pre-populate the error queue
        await agent._error_queue.put(
            StreamChunk(type="error", content="stderr error message")
        )

        # Mock the process and send_request
        agent.process = MagicMock()
        agent.process.stdin = MagicMock()

        prompt_response = JsonRpcResponse(id=1, result={"stopReason": "success"})

        async def mock_send_request(method, params=None):
            return prompt_response

        agent.send_request = mock_send_request

        chunks = []
        async for chunk in agent.prompt(Session(id="s1", workspace_id="w1"), "test"):
            chunks.append(chunk)

        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1
        assert error_chunks[0].content == "stderr error message"
