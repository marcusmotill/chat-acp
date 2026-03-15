# 🌉 Chat ACP Bridge
> **Bridge your favorite chat platforms with Agent Client Protocol (ACP) CLI agents.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

---

**Chat ACP Bridge** is a robust, protocol-compliant bridge that connects high-fidelity chat interfaces (like Discord) directly to Agent Client Protocol (ACP) compliant CLI agents (such as `claude-code`, linting agents, or custom ACP implementations).

It acts as a **stateless proxy**, managing the lifecycle of agent processes, routing prompts, and streaming intermediate thoughts and tool calls natively back to your chat platform.

## ✨ Key Features

- **🚀 Protocol Compliant**: Full implementation of the ACP JSON-RPC 2.0 specification.
- **⚡ Real-time Streaming**: Native Discord streaming with "typing..." indicators and status hooks for tool calls and internal planning.
- **📁 Workspace Persistence**: Remembers your channel-to-local-directory mappings automatically in `~/.chat-acp/config.json`.
- **🧵 Thread-Isolated Sessions**: Each Discord thread is mapped to a unique, isolated agent session.
- **🔧 Agent Agnostic**: Works with *any* CLI that supports the standard ACP stdio interface.
- **📦 Modern Stack**: Built with `Python 3.13`, `pycord`, and managed by `uv`.

## 🛠️ Prerequisites

- **Python**: 3.13 or higher.
- **[uv](https://github.com/astral-sh/uv)**: Sub-second Python package management.
- **Discord Bot**: A token for a bot with `Message Content` and `Server Members` intents enabled.
- **ACP Agent**: An installed ACP CLI (e.g., `npm install -g @anthropic-ai/claude-code`).

## 🚀 Quick Start

### 1. Installation
Clone the repository and sync the environment:
```bash
git clone https://github.com/marcusmotill/chat-apc.git
cd chat-apc
uv sync
```

### 2. Configuration
Create a `.env` file for your secret tokens:
```env
DISCORD_TOKEN=your_bot_token_here
AGENT_COMMAND="opencode acp"  # Or "npx claude-code --acp"
```

### 3. Execution
Launch the bridge daemon:
```bash
uv run main.py
```

## 🎮 Usage in Discord

Once the bot is online, use the native slash commands to manage your developer environment:

- `/add-workspace <path>` — Map the current channel to a local project directory. **Saved permanently.**
- `/ask <question>` — Send a dedicated prompt to the agent.
- `/abort` — Forcefully stop the current agent turn and clear the execution queue.
- `/clear` — Wipe the agent's context and restart the session.

## 📁 Persistence Specification

The bridge maintains a lightweight configuration at `~/.chat-acp/config.json`. This path is resolved automatically using the user's home directory on all platforms (Mac, Windows, and Linux).

```json
{
    "agent_command": ["opencode", "acp"],
    "workspaces": {
        "discord": {
            "123456789012345678": "/Users/dev/projects/ai-bridge"
        }
    }
}
```

---

## 🏗️ Architecture

The system follows a clean "Hexagonal" architecture:
- **Core**: Protocol handling, orchestrator, and session lifecycle logic.
- **Adapters (Chat)**: Discord message mapping to ACP events.
- **Adapters (Agent)**: Subprocess management and JSON-RPC stdio parsing.
- **Persistence**: File-based storage for workspace mappings.

---
*Built with ❤️ for the AI developer ecosystem.*
