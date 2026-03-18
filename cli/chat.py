import click
import asyncio
from adapters.config.file_config import FileConfig
from adapters.chat.registry import registry


@click.group(name="chat")
def chat_group():
    """Manage chat platforms."""
    pass


@chat_group.command(name="start")
@click.argument("platform_name")
@click.option("-d", "--detach", is_flag=True, help="Run in background (daemon mode)")
@click.pass_context
def start_chat(ctx, platform_name: str, detach: bool):
    """Start the chat bot for a specific platform."""
    config: FileConfig = ctx.obj["config"]
    from cli.daemon import DaemonManager

    dm = DaemonManager()

    if detach:
        # Re-invoke the same command without -d
        import sys

        # We want to re-execute as a module to be safe: python -m cli.main ...
        # First, find the relative command: ['chat', 'start', 'discord']
        # We look for 'chat' in sys.argv to find the start of the command
        try:
            chat_index = sys.argv.index("chat")
            cmd_args = sys.argv[chat_index:]
            # Remove -d/--detach from cmd_args
            cmd_args = [arg for arg in cmd_args if arg not in ("-d", "--detach")]
        except ValueError:
            # Fallback if 'chat' is not found
            cmd_args = ["chat", "start", platform_name]

        # Final command for re-invocation: python -m cli.main [args...]
        # We include the --config if it was passed to the main group
        config_args = []
        if config.config_path:
            config_args = ["--config", config.config_path]

        full_args = ["-m", "cli.main"] + config_args + cmd_args
        dm.start(platform_name, full_args)
        return

    try:
        import setproctitle

        setproctitle.setproctitle(f"chat-acp: {platform_name}")
    except ImportError:
        pass

    try:
        platform = registry.get_platform(platform_name)
        click.echo(f"Initializing {platform_name}...")
        asyncio.run(platform.start(config))
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
    except KeyboardInterrupt:
        click.echo("\nShutting down...")


@chat_group.command(name="stop")
@click.argument("platform_name")
def stop_chat(platform_name: str):
    """Stop a background chat bot."""
    from cli.daemon import DaemonManager

    DaemonManager().stop(platform_name)


@chat_group.command(name="status")
@click.argument("platform_name")
def status_chat(platform_name: str):
    """Check the status of a chat bot."""
    from cli.daemon import DaemonManager

    DaemonManager().status(platform_name)


@chat_group.command(name="ls")
def list_chats():
    """List available chat platforms."""
    platforms = registry.list_platforms()
    if not platforms:
        click.echo("No chat platforms registered.")
        return

    click.echo("Available platforms:")
    for p in platforms:
        click.echo(f"- {p}")


@chat_group.command(name="notify")
@click.argument("platform")
@click.argument("session_id")
@click.argument("message")
@click.pass_context
def notify(ctx, platform: str, session_id: str, message: str):
    """Send a notification message to a session."""
    config: FileConfig = ctx.obj["config"]
    try:
        p = registry.get_platform(platform)
        asyncio.run(p.notify(config, session_id, message))
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
