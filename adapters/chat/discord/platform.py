import os
import click
from dotenv import load_dotenv

from core.ports.platform import ChatPlatform
from core.ports.config import ConfigProtocol
from core.models import Workspace
from core.orchestrator import SessionManager
from adapters.agent.acp_stdio import AcpStdioAgent
from adapters.chat.discord.bot import DiscordCommandBot
from adapters.chat.discord.config import DiscordConfig


class DiscordPlatform(ChatPlatform):
    @property
    def name(self) -> str:
        return "discord"

    async def start(self, config: ConfigProtocol) -> None:
        load_dotenv()

        # We need to use the concrete platform config
        discord_config = DiscordConfig(config.for_platform("discord"))

        # Priority: Env > Config
        discord_token = (
            os.environ.get("DISCORD_BOT_TOKEN")
            or os.environ.get("DISCORD_TOKEN")
            or discord_config.token
        )

        if not discord_token:
            click.echo(
                "Error: Missing DISCORD_BOT_TOKEN in environment or config", err=True
            )
            return

        agent_command = os.environ.get("AGENT_COMMAND")
        if agent_command:
            agent_command = agent_command.split()
            config.set_agent_command(agent_command)
        else:
            agent_command = config.get_agent_command() or [
                "npx",
                "@anthropic-ai/claude-code",
                "--acp",
            ]

        agent_env = config.get_agent_env() or {}

        def create_agent(workspace: Workspace) -> AcpStdioAgent:
            return AcpStdioAgent(
                agent_command=agent_command, agent_env=agent_env, platform="discord"
            )

        bot = DiscordCommandBot(token=discord_token, orchestrator_callback=None)

        orchestrator = SessionManager(
            chat_adapter=bot,
            agent_factory=create_agent,
            config_registry=config,
            on_workspace_registered=lambda cid, path: discord_config.add_workspace(
                cid, path
            ),
        )

        bot.orchestrator_callback = orchestrator.handle_chat_message
        bot.orchestrator = orchestrator

        # Register existing workspaces
        persisted_workspaces = discord_config.get_workspaces()
        for cid, target_path in persisted_workspaces.items():
            workspace = Workspace(
                id=cid,
                environment_id="default_env",
                name=f"Workspace_{cid}",
                target_path=target_path,
            )
            orchestrator.register_workspace(cid, workspace)

        click.echo("Starting Discord ACP Bridge...")
        await bot.start()

    async def notify(
        self, config: ConfigProtocol, session_id: str, message: str
    ) -> None:
        from adapters.chat.discord.config import DiscordConfig
        import aiohttp

        discord_config = DiscordConfig(config.for_platform("discord"))
        token = discord_config.token

        if not token:
            click.echo("Error: Missing Discord token in config", err=True)
            return

        url = f"https://discord.com/api/v10/channels/{session_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {"content": f"🔔 **Notification**: {message}"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    click.echo(f"✅ Notification sent to Discord session {session_id}")
                else:
                    txt = await resp.text()
                    click.echo(
                        f"❌ Failed to send notification: {resp.status} {txt}", err=True
                    )
