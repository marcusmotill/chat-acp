# ACP Chat Bridge - Agent Documentation

## Purpose
This project is an **Agent Client Protocol (ACP)** implementation designed to bridge generic chat interfaces (e.g. Discord) with generic AI agents (e.g. Claude Code, Cursor, Copilot).

**Important Architecture Principle:**
This Python framework acts strictly as an **ACP Client**. We use `subprocess.Popen` to wrap *existing* ACP-compatible agent CLIs that communicate over standard I/O (stdin/stdout) via JSON-RPC 2.0. We do **not** implement our own AI agent routing or model inference logic. We parse the standard I/O stream according to the ACP spec and proxy it to/from the Chat interface.

## Core Concepts & Mapping
1. **Environment**: Represents the deployment or host. In Discord, this is mapped to a **Discord Server (Guild)**.
2. **Workspace**: Represents a project directory on the host. In Discord, this is mapped to a **Discord Channel**.
3. **Session**: An ephemeral agent execution context. When a user asks a question in a workspace (Channel), a **Discord Thread** is created to represent the Session. The subprocess for the agent is launched, and its stdio is kept alive for the duration of the thread.

## Discord Implementation (`pycord`)
## CLI & Daemon (`chat-acp`)
- The bot can be run as a background daemon using the CLI.
- Commands: 
  - `chat-acp chat start <platform> [-d]` - Start a bot (use `-d` to detach).
  - `chat-acp chat stop <platform>` - Stop a background bot.
  - `chat-acp chat status <platform>` - Check if a bot is running.
  - `chat-acp chat notify <platform> <session_id> <message>` - Send a "wake up" notification to a session.
  - `chat-acp workspace ls/add` - Manage project mappings.
- **Persistence**: Workspace mappings and settings are stored in `~/.chat-acp/config.json`.
- **PIDs**: Background process PIDs are tracked in `~/.chat-acp/pids/`.

## Configuration Specification
The bot maintains a local configuration in `~/.chat-acp/config.json`. This path is resolved using the universal home directory for cross-platform support (Mac, Windows, and Linux), allowing the bot to "remember" its state across restarts.

```json
{
    "discord": {
        "token": "your_token",
        "workspaces": {
            "123456789012345678": "/Users/user/projects/my-app"
        }
    },
    "agent_command": ["opencode", "acp"]
}
```

- `agent_command`: A list of strings representing the CLI command used to spawn the ACP agent.
- `workspaces`: A nested mapping where the first key is the platform (e.g., `discord`) and the inner key-value pair is the **Channel ID** and the **Absolute Path** to the local workspace. Standardized across all platforms.
- `token`: The authentication token for the specific platform.

## Agent Metadata & Notifications
The bridge injects metadata into the agent's environment to enable advanced workflows:

- `ACP_CHAT_SESSION_ID`: The unique identifier for the current chat session (e.g., Discord thread ID).
- `ACP_CHAT_WORKSPACE_ID`: The identifier for the current workspace.
- `ACP_CHAT_PLATFORM`: The name of the chat platform (e.g., "discord").

### The "Wake Up" Mechanism
Agents can use these variables to trigger notifications from background processes. When `chat-acp chat notify` is called:
1. The bridge posts a message to the chat platform prefixed with `🔔 **Notification**:`.
2. The bridge bot recognizes this prefix and **refeeds the message back to the agent as a prompt**.
3. This effectively "wakes up" the agent once a long-running background task is complete.

## Development
- Managed via `uv`. Use `uv add <dependency>` to manage requirements.
- **CI Requirements**: ALWAYS run linting (`uv run ruff check .` and `uv run ruff format .`) and tests (`uv run pytest`) to ensure all checks pass before creating a Pull Request.
