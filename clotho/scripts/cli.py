"""Clotho CLI: archive management commands.

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

Inspection:

    clotho status                    # pipeline counts + failure summary
    clotho list                      # fetched pages: time, domain, URL
    clotho path <URL>                # filepath of a page's markdown
    clotho db dir                    # print the data directory path
    clotho db remove                 # delete the database (asks first)
"""

from datetime import datetime, timezone
from pathlib import Path

import click
from loguru import logger

from clotho.settings import DATA_DIR, DB_PATH, SAVED_DIR, configure_logger
from clotho.db import PageDatabase, Source
from clotho.scrape import process_url
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
    """Clotho: personal knowledge archive."""
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
        # A refetch resets parsed_at, so refetched pages re-parse here too
        parse_pending(db)
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


@cli.command()
def status() -> None:
    """Show pipeline-state counts and failure summary."""
    with PageDatabase(DB_PATH) as db:
        counts = db.status_counts()
        failures = db.fail_summary()

    click.echo(f"Archive: {DB_PATH}")
    click.echo(f"Pages: {counts['total']} total")
    click.echo(f"  pending         {counts['pending']}")
    click.echo(f"  fetch failed    {counts['fetch_failed']}")
    click.echo(f"  awaiting parse  {counts['awaiting_parse']}")
    click.echo(f"  parse rejected  {counts['parse_rejected']}")
    click.echo(f"  parsed          {counts['parsed']}")

    if failures:
        click.echo("\nFailures by domain:")
        for domain, reason, count in failures[:10]:
            click.echo(f"  {domain}: {reason} ({count})")


@cli.command(name="list")
@click.option(
    "--n",
    "limit",
    type=click.IntRange(min=0),
    default=20,
    show_default=True,
    help="Number of rows to show; 0 shows everything.",
)
@click.option(
    "--reverse",
    is_flag=True,
    default=False,
    help="Oldest first instead of newest first.",
)
def list_pages(limit: int, reverse: bool) -> None:
    """List fetched pages, newest first: fetch time, domain, URL.

    Columns are tab-separated so the output pipes cleanly into
    grep/cut/awk, e.g.: clotho list --n 0 | grep medium.com
    """
    with PageDatabase(DB_PATH) as db:
        pages = db.list_fetched(limit=limit or None, oldest_first=reverse)
    for page in pages:
        # ISO timestamp trimmed to seconds for readability
        fetched_at = (page.fetched_at or "")[:19]
        click.echo(f"{fetched_at}\t{page.domain}\t{page.url}")


@cli.command()
@click.argument("url")
def path(url: str) -> None:
    """Print the filepath of URL's archived markdown.

    Composes with standard tools: cat/less/grep $(clotho path <URL>).
    """
    with PageDatabase(DB_PATH) as db:
        page = db.get(url)
        if page is None:
            # The archive keys pages by processed URL; normalize the input
            # the same way so e.g. #fragment variants still resolve
            processed, _ = process_url(url)
            if processed is not None and processed != url:
                page = db.get(processed)
    if page is None:
        raise click.ClickException(f"Unknown URL: {url}")
    if page.fail_reason:
        raise click.ClickException(f"No markdown for {page.url}: {page.fail_reason}")
    if not page.fetched:
        raise click.ClickException(f"{page.url} is still pending. Run: clotho fetch")
    if not page.parsed:
        raise click.ClickException(
            f"{page.url} is fetched but not parsed yet. Run: clotho parse"
        )
    md_path = SAVED_DIR / page.slug / "page.md"
    if not md_path.exists():
        raise click.ClickException(f"Markdown file missing on disk: {md_path}")
    click.echo(md_path)


@cli.group(name="db")
def db_group() -> None:
    """Inspect or manage the database file."""


@db_group.command(name="dir")
def db_dir() -> None:
    """Print the data directory that holds the database."""
    click.echo(DATA_DIR)


@db_group.command(name="remove")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Delete without asking for confirmation.",
)
def db_remove(force: bool) -> None:
    """Delete the SQLite database; archived files under saved/ are kept."""
    if not DB_PATH.exists():
        click.echo(f"No database at {DB_PATH}")
        return
    if not force:
        click.confirm(f"Delete {DB_PATH}? All page/source tracking is lost", abort=True)
    # The WAL sidecar files belong to the main file and must go with it
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    click.echo(f"Deleted {DB_PATH}")


if __name__ == "__main__":
    cli()
