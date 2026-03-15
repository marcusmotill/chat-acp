# 🌉 Chat ACP Bridge
> **A universal bridge connecting generic chat platform adapters with ACP-compliant CLI agents.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

---

**Chat ACP Bridge** is a highly modular, protocol-compliant proxy built on the [Agent Client Protocol (ACP)](https://agentclientprotocol.com/). It allows you to wrap existing CLI-based agents (like `claude-code`) and expose them through rich chat interfaces (like Discord).

## 🚀 Quick Start

### 1. Installation
Install globally using `uvx` (recommended) or clone the repo:
```bash
# Via UVX
uvx --from git+https://github.com/marcusmotill/chat-apc.git chat-acp --help

# Or via Source
git clone https://github.com/marcusmotill/chat-apc.git
cd chat-apc
uv sync
```

### 2. Configuration
The bridge reads from `~/.chat-acp/config.json`. You can view or set config via the CLI:
```bash
uv run chat-acp config
```

Example `config.json`:
```json
{
    "agent_command": ["npx", "-y", "@anthropic-ai/claude-code", "--acp"],
    "discord": {
        "token": "your_token",
        "workspaces": {}
    }
}
```

### 3. Usage
Start the Discord bot in the background:
```bash
uv run chat-acp chat start discord -d
```

Check status:
```bash
uv run chat-acp chat status discord
```

Stop the bot:
```bash
uv run chat-acp chat stop discord
```

---

## 🏛️ Core Architecture

The bridge is designed using clean architecture (Hexagonal):

- **Registry**: Dynamically loads chat platform adapters (Discord, etc.).
- **Core Orchestrator**: Handles session management and JSON-RPC protocol logic.
- **CLI**: Docker-like interface for process management and configuration.

---

## 🪐 Discord Implementation
The Discord adapter provide:
- **Slash Commands**: `/add-workspace`, `/ask`, `/abort`, `/clear`.
- **Real-time Streaming**: Edits messages as the agent thinks.
- **Threading**: Uses Discord Threads for isolated sessions.

---
*Built with ❤️ for the AI developer ecosystem.*
