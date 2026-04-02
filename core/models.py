from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Dict, Any, Literal


class Environment(BaseModel):
    """
    Represents a host or deployment environment.
    (e.g., A Discord Server, a Slack Workspace)
    """

    id: str
    name: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Workspace(BaseModel):
    """
    Represents a specific project directory on the host.
    (e.g., A Discord Channel, a Slack Channel)
    """

    id: str
    environment_id: str
    name: str
    target_path: str  # The physical path on disk for this workspace
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    """
    Represents an ephemeral agent execution context.
    (e.g., A Discord Thread)
    """

    id: str
    workspace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StreamChunk(BaseModel):
    """
    A unified, structured representation of streaming output from the agent.
    """

    type: Literal["text", "status", "thought", "error"]
    content: str


class ChatMessage(BaseModel):
    """
    A unified representation of a message from the user.
    """

    id: str
    session_id: str
    content: str
    author_id: str
    author_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
