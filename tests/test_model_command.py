import pytest
from unittest.mock import AsyncMock, MagicMock
from adapters.chat.discord.bot import WorkspaceCog, DiscordCommandBot


@pytest.mark.asyncio
async def test_model_command_sorting_and_search():
    # Setup mock bot and orchestrator
    bot = MagicMock(spec=DiscordCommandBot)
    bot.orchestrator = AsyncMock()
    bot.orchestrator_callback = AsyncMock()

    # Mock workspace and orchestrator
    bot.orchestrator.get_workspace.return_value = MagicMock()

    # Mock get_available_models to return a mix of models
    models_response = [
        {
            "id": "model",
            "name": "Model",
            "category": "model",
            "options": [
                {"value": "opencode/big-pickle", "name": "OpenCode Big Pickle"},
                {"value": "google-vertex/gemini-pro", "name": "Gemini Pro"},
                {"value": "opencode/gpt-5", "name": "OpenCode GPT-5"},
                {"value": "anthropic/claude", "name": "Claude"},
            ],
        }
    ]
    bot.orchestrator.get_available_models.return_value = models_response

    cog = WorkspaceCog(bot)

    # Mock discord context
    ctx = AsyncMock()
    ctx.channel_id = 12345
    ctx.channel = MagicMock()
    ctx.channel.parent_id = 12345
    ctx.channel.name = "Test Channel"
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.followup = AsyncMock()
    ctx.followup.send = AsyncMock()

    # Test without search
    await cog.model.callback(cog, ctx, search=None)

    # Check that model options were sorted properly (non-opencode first, then opencode)
    call_args = ctx.followup.send.call_args
    assert call_args is not None
    view_arg = call_args[1].get("view")
    assert view_arg is not None

    # Get the select component options from the view
    select_component = view_arg.children[0]
    sorted_values = [opt.value for opt in select_component.options]

    # Assert models are sorted alphabetically
    assert sorted_values[0] == "anthropic/claude"
    assert sorted_values[1] == "google-vertex/gemini-pro"
    assert sorted_values[2] == "opencode/big-pickle"
    assert sorted_values[3] == "opencode/gpt-5"


@pytest.mark.asyncio
async def test_model_command_search_filtering():
    # Setup mock bot and orchestrator
    bot = MagicMock(spec=DiscordCommandBot)
    bot.orchestrator = AsyncMock()
    bot.orchestrator_callback = AsyncMock()
    bot.orchestrator.get_workspace.return_value = MagicMock()

    models_response = [
        {
            "id": "model",
            "options": [
                {"value": "opencode/big-pickle", "name": "OpenCode Big Pickle"},
                {"value": "google-vertex/gemini-pro", "name": "Gemini Pro"},
                {"value": "opencode/gpt-5", "name": "OpenCode GPT-5"},
                {"value": "anthropic/claude", "name": "Claude"},
            ],
        }
    ]
    bot.orchestrator.get_available_models.return_value = models_response

    cog = WorkspaceCog(bot)

    ctx = AsyncMock()
    ctx.channel_id = 12345
    ctx.channel = MagicMock()
    ctx.channel.parent_id = 12345
    ctx.channel.name = "Test Channel"
    ctx.followup.send = AsyncMock()

    # Test with search
    await cog.model.callback(cog, ctx, search="gemini")

    call_args = ctx.followup.send.call_args
    view_arg = call_args[1].get("view")
    select_component = view_arg.children[0]
    filtered_values = [opt.value for opt in select_component.options]

    # Assert only the searched model is returned
    assert len(filtered_values) == 1
    assert filtered_values[0] == "google-vertex/gemini-pro"
