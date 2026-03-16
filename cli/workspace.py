import click
from adapters.config.file_config import FileConfig


@click.group(name="workspace")
def workspace_group():
    """Manage workspace mappings."""
    pass


@workspace_group.command(name="ls")
@click.option("--platform", default="discord", help="Platform to list workspaces for")
@click.pass_context
def list_workspaces(ctx, platform: str):
    """List configured workspace mappings."""
    config: FileConfig = ctx.obj["config"]
    platform_config = config.for_platform(platform)
    workspaces = platform_config.get_workspaces()

    if not workspaces:
        click.echo(f"No workspaces configured for {platform}.")
        return

    click.echo(f"Workspaces for {platform}:")
    for cid, path in workspaces.items():
        click.echo(f"  {cid}: {path}")


@workspace_group.command(name="add")
@click.argument("cid")
@click.argument("target_path")
@click.option("--platform", default="discord", help="Platform to add workspace to")
@click.pass_context
def add_workspace(ctx, cid: str, target_path: str, platform: str):
    """Add a new workspace mapping."""
    config: FileConfig = ctx.obj["config"]
    platform_config = config.for_platform(platform)
    platform_config.add_workspace(cid, target_path)
    click.echo(f"Added workspace mapping: {cid} -> {target_path} ({platform})")


@workspace_group.command(name="rm")
@click.argument("cid")
@click.option("--platform", default="discord", help="Platform to remove workspace from")
@click.pass_context
def remove_workspace(ctx, cid: str, platform: str):
    """Remove a workspace mapping (unimplemented in core, but CLI is ready)."""
    # Note: the core PlatformConfig doesn't have a remove_workspace yet,
    # but we can implement the CLI part or add it to core.
    click.echo(
        "Remove workspace mapping is not yet implemented in the core config provider."
    )
