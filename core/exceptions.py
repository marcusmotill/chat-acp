class AgentException(Exception):
    """Base exception for agent errors."""

    pass


class AgentInitializationError(AgentException):
    """Raised when the agent fails to initialize."""

    pass


class AgentExecutionError(AgentException):
    """Raised when the agent fails during execution."""

    pass
