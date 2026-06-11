"""Clotho CLI — archive management commands.

Usage:
    uv run python -m clotho.scripts.cli scrape [--refetch] [--reparse]
    uv run python -m clotho.scripts.cli update-agents
"""

import click

from clotho.scrape import update_user_agents

from .scrape_notes import scrape_all


@click.group()
def cli() -> None:
    """Clotho — personal knowledge archive."""


@cli.command()
@click.option(
    "--refetch",
    is_flag=True,
    default=False,
    help="Re-download all pages, even already fetched ones.",
)
@click.option(
    "--reparse",
    is_flag=True,
    default=False,
    help="Re-parse already fetched HTML into markdown.",
)
def scrape(refetch: bool, reparse: bool) -> None:
    """Scrape all URLs from Obsidian daily notes into the archive."""
    scrape_all(refetch=refetch, reparse=reparse)


@cli.command(name="update-agents")
def update_agents() -> None:
    """Fetch the latest browser user-agent strings into data/user_agents.txt."""
    count = update_user_agents()
    click.echo(f"Saved {count} user-agent strings.")


if __name__ == "__main__":
    cli()
