import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.ports.config import ConfigProtocol
from core.models import Session
from adapters.chat.discord.platform import DiscordPlatform
from adapters.chat.discord.bot import DiscordCommandBot


@pytest.mark.asyncio
async def test_discord_bot_notify():
    # Setup
    mock_orchestrator = AsyncMock()
    bot = DiscordCommandBot(token="test_token", orchestrator_callback=mock_orchestrator)

    mock_channel = AsyncMock()
    with patch.object(bot, "get_channel", return_value=mock_channel):
        session = Session(id="12345", workspace_id="ws1")

        # Execute
        await bot.notify(session, "Test Message")

        # Verify
        mock_channel.send.assert_called_once_with("🔔 **Notification**: Test Message")


@pytest.mark.asyncio
async def test_discord_platform_notify():
    # Setup
    mock_config = MagicMock(spec=ConfigProtocol)
    mock_platform_config = MagicMock()
    mock_config.for_platform.return_value = mock_platform_config
    mock_platform_config.get_setting.return_value = "test_token"

    platform = DiscordPlatform()

    # Mock aiohttp
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.__aenter__.return_value = mock_response

    mock_session = MagicMock()  # Use MagicMock here so post() returns directly
    mock_session.post.return_value = mock_response
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # Execute
        await platform.notify(mock_config, "12345", "Test Message")

        # Verify
        mock_session.post.assert_called_once()
        args, kwargs = mock_session.post.call_args
        assert args[0] == "https://discord.com/api/v10/channels/12345/messages"
        assert kwargs["json"] == {"content": "🔔 **Notification**: Test Message"}
        assert kwargs["headers"]["Authorization"] == "Bot test_token"


def test_cli_notify_routes_to_platform():
    from click.testing import CliRunner
    from cli.main import cli

    runner = CliRunner()

    with patch("adapters.chat.registry.registry.get_platform") as mock_get_platform:
        mock_platform = MagicMock()
        mock_get_platform.return_value = mock_platform

        # Mocking asyncio.run since we are in a sync test calling a sync CLI command that calls asyncio.run
        with patch("asyncio.run") as mock_run:
            result = runner.invoke(
                cli, ["chat", "notify", "discord", "12345", "Test Message"]
            )

            # Verify
            assert result.exit_code == 0
            mock_get_platform.assert_called_once_with("discord")
            # The coroutine passed to asyncio.run should be the one from platform.notify
            mock_run.assert_called_once()
