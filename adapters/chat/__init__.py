from adapters.chat.registry import registry
from adapters.chat.discord.platform import DiscordPlatform

registry.register(DiscordPlatform)
