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
- The bot runs as a background *daemon*, holding onto the active sessions. 
- A message in a thread routes into the agent session via JSON-RPC `session/prompt`.
- The agent's `session/update` JSON-RPC notifications stream back as Discord messages or edits.
- Use `pycord` for discord bot implementations with slash commands for things like `/add-workspace`.
- **Persistence**: Workspace mappings and settings are stored in `~/.chat-acp/config.json`.

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

## Development
- Managed via `uv`. Use `uv add <dependency>` to manage requirements.
