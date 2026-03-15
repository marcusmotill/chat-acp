import pytest
import asyncio
from typing import AsyncGenerator

from core.models import Workspace, Session, ChatMessage
from core.orchestrator import SessionManager
from core.ports.chat_client import ChatClientProtocol
from core.ports.agent_client import AgentClientProtocol


class MockChatClient(ChatClientProtocol):
    def __init__(self):
        self.sent_messages = []
        self.streamed_chunks = []
        
    async def start(self) -> None:
        pass
        
    async def send_message(self, session: Session, content: str) -> None:
        self.sent_messages.append((session.id, content))

    async def trigger_typing(self, session: Session) -> None:
        pass
        
    async def stream_response(self, session: Session, stream: AsyncGenerator[str, None]) -> None:
        async for chunk in stream:
            self.streamed_chunks.append((session.id, chunk))

    async def get_or_create_session(self, workspace: Workspace, context_id: str, title: str) -> Session:
        return Session(id=context_id, workspace_id=workspace.id)


class MockAgentClient(AgentClientProtocol):
    def __init__(self):
        self.started = False
        self.stopped = False
        self.prompts_received = []

    async def start_session(self, session: Session, workspace: Workspace) -> None:
        self.started = True

    async def cancel_prompt(self, session: Session) -> None:
        self.prompts_received.append("CANCELLED")

    async def prompt(self, session: Session, message: str) -> AsyncGenerator[str, None]:
        self.prompts_received.append(message)
        yield "Chunk 1: "
        await asyncio.sleep(0.01)
        yield f"Processed {message}"

    async def stop_session(self, session: Session) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_session_manager_routing():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()
    
    def agent_factory(ws: Workspace) -> AgentClientProtocol:
        return agent_mock

    manager = SessionManager(chat_mock, agent_factory)
    
    workspace = Workspace(id="ws_1", environment_id="env_1", name="Test WS", target_path="/tmp")
    manager.register_workspace("ws_1", workspace)
    
    msg = ChatMessage(
        id="msg_1", 
        session_id="thread_1", 
        content="Hello agent", 
        author_id="user_1", 
        author_name="Alice"
    )
    
    # Send message into the orchestrator
    await manager.handle_chat_message(msg, chat_workspace_id="ws_1", chat_session_id="thread_1", chat_session_name="Test Thread")
    
    # Verify Agent was started and prompted
    assert agent_mock.started is True
    assert "Hello agent" in agent_mock.prompts_received
    
    # Verify Chat Client streamed the response chunks
    assert len(chat_mock.streamed_chunks) == 2
    assert chat_mock.streamed_chunks[0] == ("thread_1", "Chunk 1: ")
    assert chat_mock.streamed_chunks[1] == ("thread_1", "Processed Hello agent")
    
    # Verify Cleanup
    await manager.cleanup_session("thread_1")
    assert agent_mock.stopped is True
    assert "thread_1" not in manager.active_agents

@pytest.mark.asyncio
async def test_session_manager_queuing():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()
    
    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(id="ws_1", environment_id="env_1", name="Test", target_path="/tmp")
    manager.register_workspace("ws_1", workspace)
    
    # Sending two messages rapidly
    task1 = asyncio.create_task(manager.handle_chat_message(
        ChatMessage(id="m1", session_id="s1", content="Msg 1", author_id="u", author_name="A"),
        "ws_1", "s1", "S1"
    ))
    # Give it a tiny bit of time to start task 1 and set busy=True
    await asyncio.sleep(0.001)
    
    task2 = asyncio.create_task(manager.handle_chat_message(
        ChatMessage(id="m2", session_id="s1", content="Msg 2", author_id="u", author_name="A"),
        "ws_1", "s1", "S1"
    ))
    
    await asyncio.gather(task1, task2)
    
    # Both messages should be processed sequentially
    assert "Msg 1" in agent_mock.prompts_received
    assert "Msg 2" in agent_mock.prompts_received
    # Total chunks should be 4 (2 per msg)
    assert len(chat_mock.streamed_chunks) == 4
    # Check that a "busy" notification was sent
    assert any("busy" in msg for _, msg in chat_mock.sent_messages)

@pytest.mark.asyncio
async def test_session_manager_abort():
    chat_mock = MockChatClient()
    agent_mock = MockAgentClient()
    
    manager = SessionManager(chat_mock, lambda ws: agent_mock)
    workspace = Workspace(id="ws_1", environment_id="env_1", name="Test", target_path="/tmp")
    manager.register_workspace("ws_1", workspace)
    
    # Start a prompt
    task = asyncio.create_task(manager.handle_chat_message(
        ChatMessage(id="m1", session_id="s1", content="Long task", author_id="u", author_name="A"),
        "ws_1", "s1", "S1"
    ))
    await asyncio.sleep(0.001)
    
    # Abort it
    await manager.abort_session("s1")
    
    # Agent should see cancel
    assert "CANCELLED" in agent_mock.prompts_received
    assert agent_mock.stopped is True
    assert manager.busy.get("s1") is False

@pytest.mark.asyncio
async def test_session_manager_unregistered_workspace():
    chat_mock = MockChatClient()
    manager = SessionManager(chat_mock, lambda ws: MockAgentClient())
    
    msg = ChatMessage(
        id="msg_1", session_id="thread_1", content="Hello", author_id="u1", author_name="A"
    )
    
    # Should ignore message and not crash
    await manager.handle_chat_message(msg, "unknown_ws", "thread_1", "Test")
    assert len(manager.active_agents) == 0
