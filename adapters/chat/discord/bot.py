import logging
import discord
import asyncio
from discord.ext import commands
from typing import AsyncGenerator
from core.models import Session, Workspace, ChatMessage
from core.ports.chat_client import ChatClientProtocol

logger = logging.getLogger(__name__)

class DiscordCommandBot(commands.Bot, ChatClientProtocol):
    """
    Discord implementation of the ChatClientProtocol using pycord.
    """
    
    @property
    def config_key(self) -> str:
        return "discord"

    def __init__(self, token: str, orchestrator_callback):
        """
        orchestrator_callback: async func(message: ChatMessage, chat_workspace_id: str, chat_session_id: str, chat_session_name: str)
        """
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        commands.Bot.__init__(self, command_prefix="!", intents=intents)
        self.discord_token = token
        self.orchestrator_callback = orchestrator_callback
        self.orchestrator = None  # Wired from main.py
        
        # Add cogs
        self.add_cog(WorkspaceCog(self))

    async def on_ready(self):
        logger.info(f"Discord Bot logged in as {self.user}")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Context mapping
        # 1. Server mapping (Environment)
        # 2. Channel mapping (Workspace)
        # 3. Thread mapping (Session)
        
        chat_workspace_id = str(message.channel.id)
        chat_session_id = str(message.channel.id) # Fallback to channel if not in thread
        chat_session_name = "Agent Session"
        
        # If we are in a thread, the parent channel is the workspace
        if isinstance(message.channel, discord.Thread):
            chat_workspace_id = str(message.channel.parent_id)
            chat_session_id = str(message.channel.id)
            chat_session_name = message.channel.name
        elif self.user in message.mentions:
            # If pinged in a normal channel, the orchestrator/adapter 
            # will create a thread during get_or_create_session.
            pass
        else:
            # Not a thread, not a mention. Ignore.
            return

        chat_msg = ChatMessage(
            id=str(message.id),
            session_id=chat_session_id,
            content=message.clean_content,
            author_id=str(message.author.id),
            author_name=message.author.display_name
        )

        # Send it to the orchestrator layer
        await self.orchestrator_callback(
            chat_msg, 
            chat_workspace_id, 
            chat_session_id, 
            chat_session_name
        )

    async def get_or_create_session(self, workspace: Workspace, context_id: str, title: str) -> Session:
        """
        If the message was in a standard channel, we create a thread to act as the session.
        If it was already in a thread, we return that.
        """
        workspace_channel = self.get_channel(int(workspace.id))
        if not workspace_channel:
            # Fallback if cache miss
            workspace_channel = await self.fetch_channel(int(workspace.id))

        new_session_id = context_id
        
        # If the context is the workspace channel itself, create a thread
        if context_id == workspace.id and isinstance(workspace_channel, discord.TextChannel):
            thread = await workspace_channel.create_thread(
                name=title,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440
            )
            new_session_id = str(thread.id)

        return Session(
            id=new_session_id,
            workspace_id=workspace.id
        )

    async def send_message(self, session: Session, content: str) -> None:
        """Sends a simple message to the session thread."""
        channel_or_thread = self.get_channel(int(session.id)) or await self.fetch_channel(int(session.id))
        if channel_or_thread:
            await channel_or_thread.send(content)

    async def trigger_typing(self, session: Session) -> None:
        """Triggers the 'typing...' indicator in the chat interface."""
        channel_or_thread = self.get_channel(int(session.id)) or await self.fetch_channel(int(session.id))
        if channel_or_thread:
            await channel_or_thread.trigger_typing()

    async def stream_response(self, session: Session, stream: AsyncGenerator[str, None]) -> None:
        """
        Consumes chunks from the agent and sends them as Discord messages.
        Handles the 2000 character limit by chunking/buffering safely.
        """
        channel_or_thread = self.get_channel(int(session.id)) or await self.fetch_channel(int(session.id))
        if not channel_or_thread:
            logger.error(f"Cannot stream response: Channel/Thread {session.id} not found.")
            return

        current_msg = ""
        last_message_obj = None
        
        # Keep typing indicator alive
        async def keep_typing():
            try:
                while True:
                    await channel_or_thread.trigger_typing()
                    await asyncio.sleep(8)
            except asyncio.CancelledError:
                pass
        
        typing_task = asyncio.create_task(keep_typing())

        try:
            async for chunk in stream:
                if not chunk:
                    continue
                current_msg += chunk
                
                # Simple Discord buffer limit: Every time we get near 2k chars, send a message.
                if len(current_msg) > 1900:
                    if last_message_obj:
                        await last_message_obj.edit(content=current_msg[:1900])
                    else:
                        last_message_obj = await channel_or_thread.send(current_msg[:1900])
                    
                    current_msg = current_msg[1900:]
                    last_message_obj = None # Start new message
                    continue

                if not last_message_obj:
                    # Only send if non-empty to avoid triggering on meta-chunks
                    if current_msg.strip():
                        last_message_obj = await channel_or_thread.send(current_msg)
                else:
                    # Progressively edit
                    await last_message_obj.edit(content=current_msg)
                    
            if current_msg and not last_message_obj:
                await channel_or_thread.send(current_msg)
        finally:
            typing_task.cancel()

    async def start(self) -> None:
        """Starts the discord bot."""
        await commands.Bot.start(self, self.discord_token)

class WorkspaceCog(commands.Cog):
    def __init__(self, bot: DiscordCommandBot):
        self.bot = bot
        
    @commands.slash_command(name="add-workspace", description="Map this channel to a local project directory.")
    async def add_workspace(
        self, 
        ctx: discord.ApplicationContext, 
        target_path: discord.Option(str, "Absolute path to the project directory")
    ):
        channel_id = str(ctx.channel_id)
        if not self.bot.orchestrator:
            await ctx.respond("Error: Orchestrator not yet wired.", ephemeral=True)
            return
            
        workspace = Workspace(
            id=channel_id,
            environment_id=str(ctx.guild_id) if ctx.guild_id else "default_env", 
            name=f"Workspace_{channel_id}",
            target_path=target_path
        )
        self.bot.orchestrator.register_workspace(channel_id, workspace)
        await ctx.respond(f"✅ Successfully mapped this channel to `{target_path}`.")

    @commands.slash_command(name="ask", description="Send a specific prompt to the agent.")
    async def ask(self, ctx: discord.ApplicationContext, question: str):
        # Create a ChatMessage and route it
        chat_msg = ChatMessage(
            id=str(ctx.interaction.id),
            session_id=str(ctx.channel_id),
            content=question,
            author_id=str(ctx.author.id),
            author_name=ctx.author.display_name
        )
        await ctx.respond(f"📨 **Question sent**: {question}")
        await self.bot.orchestrator_callback(
            chat_msg, 
            str(ctx.channel_id if not isinstance(ctx.channel, discord.Thread) else ctx.channel.parent_id), 
            str(ctx.channel_id), 
            ctx.channel.name if hasattr(ctx.channel, 'name') else "Agent Session"
        )

    @commands.slash_command(name="abort", description="Forcefully stop the current agent session and clear queues.")
    async def abort(self, ctx: discord.ApplicationContext):
        session_id = str(ctx.channel_id)
        await self.bot.orchestrator.abort_session(session_id)
        await ctx.respond("⏹️ **Session aborted and queue cleared**.")

    @commands.slash_command(name="queue", description="Queue a message to be sent after the current turn.")
    async def queue(self, ctx: discord.ApplicationContext, message: str):
        # The orchestrator handle_chat_message already handles queuing if busy.
        # So we just route it.
        chat_msg = ChatMessage(
            id=str(ctx.interaction.id),
            session_id=str(ctx.channel_id),
            content=message,
            author_id=str(ctx.author.id),
            author_name=ctx.author.display_name
        )
        await self.bot.orchestrator_callback(
            chat_msg, 
            str(ctx.channel_id if not isinstance(ctx.channel, discord.Thread) else ctx.channel.parent_id), 
            str(ctx.channel_id), 
            ctx.channel.name if hasattr(ctx.channel, 'name') else "Agent Session"
        )
        await ctx.respond("📝 **Message added to queue**.")

    @commands.slash_command(name="clear-queue", description="Clear all pending messages in the queue.")
    async def clear_queue(self, ctx: discord.ApplicationContext):
        count = await self.bot.orchestrator.clear_queue(str(ctx.channel_id))
        await ctx.respond(f"🗑️ **Queue cleared**: {count} messages removed.")

    @commands.slash_command(name="model", description="Set the model mode (if supported by agent).")
    async def model(self, ctx: discord.ApplicationContext, name: str):
        # This would ideally map to session/set-mode or similar in ACP
        # For now, we'll send it as a hidden instruction or just notify.
        await ctx.respond(f"⚠️ **Model switching** via slash command is not yet fully implemented in generic ACP, but I've noted `{name}`.")

    @commands.slash_command(name="clear", description="Clear the conversation context by restarting the agent session.")
    async def clear(self, ctx: discord.ApplicationContext):
        session_id = str(ctx.channel_id)
        await self.bot.orchestrator.cleanup_session(session_id)
        await ctx.respond("🧹 **Conversation context cleared**. The agent will start fresh on the next message.")

