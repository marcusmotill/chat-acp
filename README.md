# 🌉 Chat ACP Bridge
> **A universal bridge connecting generic chat platform adapters with ACP-compliant CLI agents.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

---

**Chat ACP Bridge** is a highly modular, protocol-compliant proxy built on the [Agent Client Protocol (ACP)](https://agentclientprotocol.com/). It allows you to wrap existing CLI-based agents (like `claude-code`) and expose them through rich chat interfaces (like Discord), handling process lifecycle, streaming, and workspace mapping automatically.

## 🏛️ Core Architecture

The bridge is designed using clean architecture (Hexagonal) to ensure the core orchestrator remains agnostic of both the chat platform and the specific AI model:

- **Core**: Handles session management, process execution, and JSON-RPC 2.0 protocol logic.
- **Chat Adapters**: Platform-specific implementations (e.g., Discord) that map chat events to ACP prompts.
- **Agent Adapters**: Subprocess managers that communicate with CLI agents via standard I/O.
- **Config Store**: A shared, file-based persistence layer for tokens and workspace mappings.

---

## 🚀 Setup & Configuration

The bridge prioritizes a **Configuration-First** approach. Most settings should be defined in the central configuration file.

### 1. Installation
Clone the repository and sync dependencies using `uv`:
```bash
git clone https://github.com/marcusmotill/chat-apc.git
cd chat-apc
uv sync
```

### 2. Primary Configuration
The bridge reads from `~/.chat-acp/config.json`. This file is automatically created and migrated on first run.

**Standardized Schema:**
```json
{
    "agent_command": ["npx", "-y", "@anthropic-ai/claude-code", "--acp"],
    "discord": {
        "token": "your_discord_bot_token",
        "workspaces": {
            "channel_id": "/absolute/path/to/project"
        }
    }
}
```

- **`agent_command`**: The CLI command to spawn the ACP agent.
- **`any-platform.token`**: The authentication token for the specific adapter.
- **`any-platform.workspaces`**: Standardized mapping of Chat ID -> Local File Path.

### 3. Environment Variables (Secret Overrides)
For security, tokens can be supplied via environment variables or a `.env` file:
- `DISCORD_TOKEN` or `DISCORD_BOT_TOKEN`
- `AGENT_COMMAND`

---

## 🎭 Chat Platform Adapters

### 🪐 Discord Implementation
The Discord adapter (`adapters/chat/discord/`) provides a full-featured interface:

**Slash Commands:**
- `/add-workspace <path>` — Map a channel to a local project directory. **Saved to config.**
- `/ask <question>` — Send a specific prompt to the agent.
- `/abort` — Stop the current agent process and clear the queue.
- `/clear` — Wipe session history and restart the agent process.

**Rich Features:**
- **Real-time Streaming**: Edits messages in real-time as the agent thinks.
- **Typing Indicators**: Stays active while the agent is processing or calling tools.
- **Threading**: Uses Discord Threads for isolated, per-conversation agent sessions.

---

## 🔧 Infrastructure
- **Python**: 3.13+
- **Process Management**: `subprocess.Popen` for persistent stdio streams.
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

---
*Built with ❤️ for the AI developer ecosystem.*
