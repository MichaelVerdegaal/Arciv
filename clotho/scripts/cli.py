"""Clotho CLI — archive management commands.

Layered archiving with ``get`` (index → fetch → parse in one go):

    clotho get https://example.com   # archive a single URL
    clotho get --file note.md        # archive all links in one file
    clotho get --dir ~/notes         # archive all links in a directory

Sources (named directories that can be re-indexed any time):

    clotho add ~/vault/notes notes   # register directory as source "notes"
    clotho remove notes              # unregister it
    clotho sources                   # list registered sources

Individual pipeline stages, mainly for development:

    clotho index notes               # index one source
    clotho index --all               # index every source
    clotho fetch                     # download pending indexed URLs
    clotho parse                     # convert fetched pages to markdown
"""

from datetime import datetime, timezone
from pathlib import Path

import click
from loguru import logger

from clotho.config import DB_PATH, configure_logger
from clotho.db import PageDatabase, Source
from clotho.pipeline import (
    fetch_pending,
    fetch_urls,
    index_all,
    index_directory,
    index_file,
    index_source,
    parse_pending,
    register_urls,
    report,
)


@click.group()
def cli() -> None:
    """Clotho — personal knowledge archive."""
    configure_logger()


@cli.command()
@click.argument("url", required=False)
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Archive all links within a single file.",
)
@click.option(
    "--dir",
    "dir_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Archive all links of all files within a directory.",
)
@click.option(
    "--refetch",
    is_flag=True,
    default=False,
    help="Re-download pages even if already fetched.",
)
def get(
    url: str | None,
    file_path: Path | None,
    dir_path: Path | None,
    refetch: bool,
) -> None:
    """Archive a URL, the links in a file, or a whole directory.

    Runs the full pipeline (index → fetch → parse) on exactly one of:
    a single URL, a single file (--file), or a directory (--dir).
    """
    targets = [t for t in (url, file_path, dir_path) if t is not None]
    if len(targets) != 1:
        raise click.UsageError("Provide exactly one of: URL, --file, or --dir.")

    with PageDatabase(DB_PATH) as db:
        if url is not None:
            urls = register_urls(db, [url])
        elif file_path is not None:
            urls = index_file(db, file_path)
        else:
            urls = index_directory(db, dir_path)

        fetched = fetch_urls(db, urls, refetch=refetch)
        parse_pending(db, reparse=refetch)
        report(db, len(fetched))


@cli.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.argument("name")
def add(directory: Path, name: str) -> None:
    """Register DIRECTORY as a source named NAME."""
    source = Source(
        name=name,
        path=str(directory.resolve()),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with PageDatabase(DB_PATH) as db:
        if not db.add_source(source):
            raise click.ClickException(f"A source named '{name}' already exists.")
    logger.info(f"Added source '{name}' -> {source.path}")


@cli.command()
@click.argument("name")
def remove(name: str) -> None:
    """Unregister the source named NAME (indexed pages are kept)."""
    with PageDatabase(DB_PATH) as db:
        if not db.remove_source(name):
            raise click.ClickException(f"No source named '{name}'.")
    logger.info(f"Removed source '{name}'")


@cli.command()
def sources() -> None:
    """List registered sources."""
    with PageDatabase(DB_PATH) as db:
        registered = db.list_sources()
    if not registered:
        click.echo("No sources registered. Add one with: clotho add <dir> <name>")
        return
    for source in registered:
        click.echo(f"{source.name}\t{source.path}")


@cli.command()
@click.argument("source", required=False)
@click.option(
    "--all",
    "all_sources",
    is_flag=True,
    default=False,
    help="Index every registered source.",
)
def index(source: str | None, all_sources: bool) -> None:
    """Index stage: extract links from a registered SOURCE (or --all)."""
    if bool(source) == all_sources:
        raise click.UsageError("Provide a source name or --all, not both.")

    with PageDatabase(DB_PATH) as db:
        if all_sources:
            urls = index_all(db)
        else:
            try:
                urls = index_source(db, source)
            except KeyError as e:
                raise click.ClickException(str(e.args[0]))
    logger.info(f"Indexed {len(urls)} unique URLs")


@cli.command()
@click.option(
    "--refetch",
    is_flag=True,
    default=False,
    help="Re-download every known page, even fetched/failed ones.",
)
def fetch(refetch: bool) -> None:
    """Fetch stage: download indexed URLs that are still pending."""
    with PageDatabase(DB_PATH) as db:
        fetched = fetch_pending(db, refetch=refetch)
        report(db, len(fetched))


@cli.command()
@click.option(
    "--reparse",
    is_flag=True,
    default=False,
    help="Re-parse every fetched page, not just unparsed ones.",
)
def parse(reparse: bool) -> None:
    """Parse stage: convert fetched HTML/PDFs into markdown."""
    with PageDatabase(DB_PATH) as db:
        parse_pending(db, reparse=reparse)


if __name__ == "__main__":
    cli()
