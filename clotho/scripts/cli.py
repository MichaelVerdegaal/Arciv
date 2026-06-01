"""Clotho CLI — archive management commands.

Usage:
    uv run python -m clotho.scripts.cli scrape [--refetch] [--reparse]
    uv run python -m clotho.scripts.cli update-agents
"""

import click

from .scrape_notes import scrape_all
from clotho.scrape import update_agents


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
    update_agents()
    scrape_all(refetch=refetch, reparse=reparse)


if __name__ == "__main__":
    cli()
