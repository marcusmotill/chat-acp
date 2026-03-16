import click
import logging
from typing import Optional

from cli.chat import chat_group
from cli.workspace import workspace_group
from adapters.config.file_config import FileConfig


@click.group()
@click.option(
    "--config",
    help="Path to config file",
    type=click.Path(exists=False, dir_okay=False, resolve_path=True),
)
@click.pass_context
def cli(ctx, config: Optional[str]):
    """Chat ACP - Bridge between AI agents and chat platforms."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Initialize config and store in context
    cfg = FileConfig(config_path=config) if config else FileConfig()
    cfg.load()
    ctx.obj = {"config": cfg}


@cli.command()
@click.pass_context
def config(ctx):
    """View current configuration."""
    cfg: FileConfig = ctx.obj["config"]
    click.echo(f"Config loaded from: {cfg.config_path}")
    import json

    click.echo(json.dumps(cfg.data, indent=4))


cli.add_command(chat_group, name="chat")
cli.add_command(workspace_group, name="workspace")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
