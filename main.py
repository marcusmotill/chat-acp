import os
import asyncio
import logging
from dotenv import load_dotenv

from core.models import Workspace
from core.orchestrator import SessionManager
from adapters.agent.acp_stdio import AcpStdioAgent
from adapters.chat.discord_bot import DiscordCommandBot
from adapters.config.file_config import FileConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run():
    load_dotenv()
    
    discord_token = os.environ.get("DISCORD_TOKEN")
    if not discord_token:
        logger.error("Missing DISCORD_TOKEN in environment")
        return

    logger.info("Initializing configuration...")
    config = FileConfig()
    config.load()

    # Priority: Env > Config > Default
    env_command = os.environ.get("AGENT_COMMAND")
    if env_command:
        agent_command = env_command.split()
        config.set_agent_command(agent_command)
    else:
        agent_command = config.get_agent_command() or ["npx", "claude-code", "--acp"]

    # Create the agent factory
    def create_agent(workspace: Workspace) -> AcpStdioAgent:
        return AcpStdioAgent(agent_command=agent_command)

    # Initialize Bot (Chat Adapter)
    # We pass a placeholder callback first, then wire it up properly
    bot = DiscordCommandBot(token=discord_token, orchestrator_callback=None)

    # Initialize Core Orchestrator
    orchestrator = SessionManager(
        chat_adapter=bot,
        agent_factory=create_agent,
        on_workspace_registered=lambda cid, path: config.add_workspace("discord", cid, path)
    )

    # Wire the callbacks
    bot.orchestrator_callback = orchestrator.handle_chat_message
    bot.orchestrator = orchestrator

    # Register Workspaces from Config
    persisted_workspaces = config.get_workspaces("discord")
    for cid, target_path in persisted_workspaces.items():
        workspace = Workspace(
            id=cid,
            environment_id="default_env", 
            name=f"Workspace_{cid}",
            target_path=target_path
        )
        orchestrator.register_workspace(cid, workspace)

    logger.info("Starting Chat ACP Daemon...")
    await bot.start()

def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down daemon.")

if __name__ == "__main__":
    main()
