import pytest
import asyncio
from typing import AsyncGenerator, Dict, Any, Optional, List

from core.models import Workspace, Session, ChatMessage, StreamChunk
from core.orchestrator import SessionManager
from core.ports.chat_client import ChatClientProtocol
from core.ports.agent_client import AgentClientProtocol, PromptTurnCallback


class MockChatClient(ChatClientProtocol):
    def __init__(self):
        self.sent_messages = []
        self.sent_errors = []
        self.streamed_chunks = []
        self.action_to_return = {
            "action": {"type": "text", "content": "This is the user's action"}
        }

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
        self.sent_messages.append(("PROMPT_TURN", session.id, prompt_turn_params))
        # Simulate user response
        return self.action_to_return

    async def get_or_create_session(
        self, workspace: Workspace, context_id: str, title: str
    ) -> Session:
        return Session(id=context_id, workspace_id=workspace.id)

    async def notify(self, session: Session, message: str) -> None:
        self.sent_messages.append(("NOTIFICATION", session.id, message))


class MockAgentClient(AgentClientProtocol):
    def __init__(self):
        self.started = False
        self.stopped = False
        self.prompts_received = []
        self.prompt_turn_callback: Optional[PromptTurnCallback] = None

    def set_user_interaction_callback(self, callback: PromptTurnCallback) -> None:
        self.prompt_turn_callback = callback

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        self.started = True

    async def cancel_prompt(self, session: Session) -> None:
        self.prompts_received.append("CANCELLED")

    async def prompt(
        self, session: Session, message: str
    ) -> AsyncGenerator[StreamChunk, None]:
        self.prompts_received.append(message)
        yield StreamChunk(type="text", content="Chunk 1: ")
        await asyncio.sleep(0.01)

        # Simulate agent needing user input (prompt_turn)
        if self.prompt_turn_callback:
            # The callback handles the blocking until the user responds
            user_action_result = await self.prompt_turn_callback(
                session, {"prompt": "What should I do next?"}
            )

            # The agent would typically process this result and continue, but we'll yield a confirmation
            action_content = user_action_result.get("action", {}).get(
                "content", "NO ACTION"
            )
            yield StreamChunk(type="text", content=f"Action received: {action_content}")

        yield StreamChunk(type="text", content=f"Processed {message}")

    async def stop_session(self, session: Session) -> None:
        self.stopped = True

    async def get_config_options(self, session: Session) -> List[Dict[str, Any]]:
        return []

    async def set_config_option(
        self, session: Session, config_id: str, value: Any
    ) -> bool:
        return True


@pytest.mark.asyncio
async def test_session_manager_routing():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()

    def agent_factory(ws: Workspace) -> AgentClientProtocol:
        return agent_mock

    manager = SessionManager(chat_mock, agent_factory)

    workspace = Workspace(
        id="ws_1", environment_id="env_1", name="Test WS", target_path="/tmp"
    )
    manager.register_workspace("ws_1", workspace)

    msg = ChatMessage(
        id="msg_1",
        session_id="thread_1",
        content="Hello agent",
        author_id="user_1",
        author_name="Alice",
    )

    # Send message into the orchestrator
    await manager.handle_chat_message(
        msg,
        chat_workspace_id="ws_1",
        chat_session_id="thread_1",
        chat_session_name="Test Thread",
    )

    # Verify Agent was started and prompted
    assert agent_mock.started is True
    assert "Hello agent" in agent_mock.prompts_received

    # Verify Chat Client streamed the response chunks
    assert len(chat_mock.streamed_chunks) == 3
    assert chat_mock.streamed_chunks[0] == (
        "thread_1",
        StreamChunk(type="text", content="Chunk 1: "),
    )
    assert chat_mock.streamed_chunks[1][1].content.startswith("Action received:")
    assert chat_mock.streamed_chunks[2] == (
        "thread_1",
        StreamChunk(type="text", content="Processed Hello agent"),
    )

    # Verify Cleanup
    await manager.cleanup_session("thread_1")
    assert agent_mock.stopped is True
    assert "thread_1" not in manager.session_contexts


@pytest.mark.asyncio
async def test_session_manager_queuing():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()

    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(
        id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
    )
    manager.register_workspace("ws_1", workspace)

    # Sending two messages rapidly
    task1 = asyncio.create_task(
        manager.handle_chat_message(
            ChatMessage(
                id="m1",
                session_id="s1",
                content="Msg 1",
                author_id="u",
                author_name="A",
            ),
            "ws_1",
            "s1",
            "S1",
        )
    )
    # Give it a tiny bit of time to start task 1 and set busy=True
    await asyncio.sleep(0.001)

    task2 = asyncio.create_task(
        manager.handle_chat_message(
            ChatMessage(
                id="m2",
                session_id="s1",
                content="Msg 2",
                author_id="u",
                author_name="A",
            ),
            "ws_1",
            "s1",
            "S1",
        )
    )

    await asyncio.gather(task1, task2)

    # Both messages should be processed sequentially
    assert "Msg 1" in agent_mock.prompts_received
    assert "Msg 2" in agent_mock.prompts_received
    # Total chunks should be 6 (3 per msg)
    assert len(chat_mock.streamed_chunks) == 6
    # Check that a "busy" notification was sent
    assert any("busy" in msg for _, msg in chat_mock.sent_messages)


@pytest.mark.asyncio
async def test_session_manager_abort():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()

    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(
        id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
    )
    manager.register_workspace("ws_1", workspace)

    # Start a prompt
    asyncio.create_task(
        manager.handle_chat_message(
            ChatMessage(
                id="m1",
                session_id="s1",
                content="Long task",
                author_id="u",
                author_name="A",
            ),
            "ws_1",
            "s1",
            "S1",
        )
    )
    await asyncio.sleep(0.001)

    # Abort it
    await manager.abort_session("s1")

    # Agent should see cancel
    assert "CANCELLED" in agent_mock.prompts_received
    assert agent_mock.stopped is True
    assert "s1" not in manager.session_contexts


@pytest.mark.asyncio
async def test_prompt_turn_interaction():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()

    # The action that the chat client will return to the agent (simulating user input)
    expected_user_action = {"action": {"type": "text", "content": "run_test_suite"}}
    chat_mock.action_to_return = expected_user_action

    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(
        id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
    )
    manager.register_workspace("ws_1", workspace)

    msg = ChatMessage(
        id="msg_1",
        session_id="s1",
        content="Test prompt turn",
        author_id="u",
        author_name="A",
    )

    await manager.handle_chat_message(
        msg,
        "ws_1",
        "s1",
        "S1",
    )

    # 1. Verify that the agent received the prompt
    assert "Test prompt turn" in agent_mock.prompts_received

    # 2. Verify that the chat client was asked to await an action from the user
    # The message should contain the prompt_turn request content
    assert len(chat_mock.sent_messages) == 1
    prompt_turn_req = chat_mock.sent_messages[0]
    assert prompt_turn_req[0] == "PROMPT_TURN"
    assert prompt_turn_req[2]["prompt"] == "What should I do next?"

    # 3. Verify that the final streamed output contains the simulated action result
    # It should have 3 chunks: "Chunk 1: ", "Action received: run_test_suite", and "Processed Test prompt turn"
    assert len(chat_mock.streamed_chunks) == 3
    assert (
        chat_mock.streamed_chunks[1][1].content
        == f"Action received: {expected_user_action['action']['content']}"
    )

    await manager.cleanup_session("s1")


@pytest.mark.asyncio
async def test_session_manager_queuing_notification_silence():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()

    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(
        id="ws_1", environment_id="env_1", name="Test", target_path="/tmp"
    )
    manager.register_workspace("ws_1", workspace)

    # 1. Start a long-running turn
    task1 = asyncio.create_task(
        manager.handle_chat_message(
            ChatMessage(
                id="m1",
                session_id="s1",
                content="Msg 1",
                author_id="u",
                author_name="A",
            ),
            "ws_1",
            "s1",
            "S1",
        )
    )
    await asyncio.sleep(0.001)

    # 2. While Turn 1 is busy, send a NOTIFICATION
    task2 = asyncio.create_task(
        manager.handle_chat_message(
            ChatMessage(
                id="m2",
                session_id="s1",
                content="🔔 Notification: Wake up",
                author_id="u",
                author_name="A",
            ),
            "ws_1",
            "s1",
            "S1",
        )
    )

    await asyncio.gather(task1, task2)

    # Both messages should be processed
    assert "Msg 1" in agent_mock.prompts_received
    assert "🔔 Notification: Wake up" in agent_mock.prompts_received

    # CRITICAL: Verify that NO "busy" notification was sent for the notification message
    # Filter sent_messages safely regardless of tuple length
    busy_messages = []
    for m in chat_mock.sent_messages:
        if len(m) >= 2 and isinstance(m[1], str) and "busy" in m[1]:
            busy_messages.append(m)
    assert len(busy_messages) == 0


@pytest.mark.asyncio
async def test_session_manager_unregistered_workspace():
    chat_mock = MockChatClient()
    manager = SessionManager(chat_mock, lambda ws: MockAgentClient())

    msg = ChatMessage(
        id="msg_1",
        session_id="thread_1",
        content="Hello",
        author_id="u1",
        author_name="A",
    )

    # Should ignore message and not crash
    await manager.handle_chat_message(msg, "unknown_ws", "thread_1", "Test")
    assert len(manager.session_contexts) == 0
