"""Clotho CLI — archive management commands.

Usage:
    clotho fetch                      # index notes, fetch + parse new URLs
    clotho fetch https://example.com  # fetch specific URLs directly
    clotho fetch --dir ~/notes        # index a different notes directory
    clotho parse                      # re-parse archived HTML into markdown
"""

from pathlib import Path

import click

from config import NOTES_PATH

from .pipeline import fetch_urls, reparse_archive, run_pipeline


@click.group()
def cli() -> None:
    """Clotho — personal knowledge archive."""


@cli.command()
@click.argument("urls", nargs=-1)
@click.option(
    "--dir",
    "notes_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Notes directory to index (defaults to CLOTHO_NOTES_PATH).",
)
@click.option(
    "--refetch",
    is_flag=True,
    default=False,
    help="Re-download pages even if already fetched.",
)
def fetch(urls: tuple[str, ...], notes_dir: Path | None, refetch: bool) -> None:
    """Fetch URLs into the archive.

    With URLS, fetches those directly. Without, indexes the notes directory
    and fetches every new URL found in it.
    """
    if urls and notes_dir:
        raise click.UsageError("Pass URLs or --dir, not both.")

    if urls:
        fetch_urls(list(urls), refetch=refetch)
        return

    target = notes_dir or NOTES_PATH
    if not target.is_dir():
        raise click.ClickException(
            f"Notes directory not found: {target}\n"
            "Set CLOTHO_NOTES_PATH in .env or pass --dir."
        )
    run_pipeline(target, refetch=refetch)


@cli.command()
def parse() -> None:
    """Re-parse archived HTML into markdown (no fetching)."""
    reparse_archive()


if __name__ == "__main__":
    cli()
