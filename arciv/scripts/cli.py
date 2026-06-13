"""Arciv CLI: archive management commands (built on Typer).

Layered archiving with ``get`` (index → fetch → parse in one go):

    arciv get https://example.com   # archive a single URL
    arciv get --file note.md        # archive all links in one file
    arciv get --dir ~/notes         # archive all links in a directory
    arciv list --json | jq -r .url | arciv get -   # archive piped URLs

Sources (named directories that can be re-indexed any time):

    arciv add ~/vault/notes notes   # register directory as source "notes"
    arciv remove notes              # unregister it
    arciv sources                   # list registered sources

Individual pipeline stages, mainly for development:

    arciv index notes               # index one source
    arciv index --all               # index every source
    arciv fetch                     # download pending indexed URLs
    arciv parse                     # convert fetched pages to markdown

Inspection:

    arciv status                    # pipeline counts + failure summary
    arciv list                      # fetched pages: time, domain, URL
    arciv path <URL>                # filepath of a page's markdown
    arciv db dir                    # print the data directory path
    arciv db remove                 # delete the database (asks first)

Global options (before the command): ``-v``/``-vv`` for more detail,
``-q`` for errors only, ``--color auto|always|never``, and ``--json`` to
switch every command to machine-readable output on stdout. Data goes to
stdout; all logs and diagnostics go to stderr, so ``arciv list | cat``
shows only data.
"""

import json
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import NoReturn

import typer
from loguru import logger

from arciv.settings import DATA_DIR, DB_PATH, SAVED_DIR, configure_logger
from arciv.db import PageDatabase, Source
from arciv.scrape import process_url
from arciv.pipeline import (
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
from .output import (
    EXIT_NOINPUT,
    EXIT_USAGE,
    emit,
    emit_json,
    json_output,
    set_json_output,
)

# add_completion=False keeps the CLI surface identical to the old click one
# (no extra --install-completion/--show-completion options).
cli = typer.Typer(
    help="Arciv: personal knowledge archive.",
    no_args_is_help=True,
    add_completion=False,
)
db_app = typer.Typer(help="Inspect or manage the database file.", no_args_is_help=True)
cli.add_typer(db_app, name="db")


class ColorWhen(str, Enum):
    """Choices for the global --color option."""

    auto = "auto"
    always = "always"
    never = "never"


def _fail(message: str, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit, no traceback.

    Mirrors click's ClickException/UsageError: a clean ``Error: ...`` line
    and a non-zero exit code. EXIT_USAGE (64) marks a bad argument
    combination, EXIT_NOINPUT (66) an unknown URL or missing source, and
    the default 1 a generic operation failure.
    """
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)


def _resolve_level(verbose: int, quiet: bool) -> str:
    """Map -q / -v / -vv to a loguru level (quiet wins over verbose)."""
    if quiet:
        return "ERROR"
    if verbose >= 2:
        return "TRACE"
    if verbose == 1:
        return "DEBUG"
    return "INFO"


@cli.callback()
def main(
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Increase log detail; repeat for more (-v debug, -vv trace).",
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Only show errors (wins over --verbose)."
    ),
    color: ColorWhen = typer.Option(
        ColorWhen.auto, "--color", help="Colorize logs: auto, always, or never."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit machine-readable output on stdout."
    ),
) -> None:
    """Arciv: personal knowledge archive.

    Global options go before the command, e.g. ``arciv -v --json status``.
    Data goes to stdout; logs and diagnostics go to stderr.
    """
    configure_logger(level=_resolve_level(verbose, quiet), color=color.value)
    set_json_output(json_out)


@cli.command()
def get(
    url: str | None = typer.Argument(
        None, help="A single URL to archive, or '-' to read URLs from stdin."
    ),
    file_path: Path | None = typer.Option(
        None,
        "--file",
        exists=True,
        dir_okay=False,
        help="Archive all links within a single file.",
    ),
    dir_path: Path | None = typer.Option(
        None,
        "--dir",
        exists=True,
        file_okay=False,
        help="Archive all links of all files within a directory.",
    ),
    refetch: bool = typer.Option(
        False, "--refetch", help="Re-download pages even if already fetched."
    ),
) -> None:
    """Archive a URL, the links in a file, or a whole directory.

    Runs the full pipeline (index → fetch → parse) on exactly one of:
    a single URL, a single file (--file), or a directory (--dir). Pass
    ``-`` as the URL to read newline-separated URLs from stdin.
    """
    targets = [t for t in (url, file_path, dir_path) if t is not None]
    if len(targets) != 1:
        _fail("Provide exactly one of: URL, --file, or --dir.", code=EXIT_USAGE)

    with PageDatabase(DB_PATH) as db:
        if url is not None:
            urls = register_urls(db, _resolve_url_targets(url))
        elif file_path is not None:
            urls = index_file(db, file_path)
        else:
            urls = index_directory(db, dir_path)

        fetched = fetch_urls(db, urls, refetch=refetch)
        # A refetch resets parsed_at, so refetched pages re-parse here too
        parse_pending(db)
        report(db, len(fetched))


def _resolve_url_targets(url: str) -> list[str]:
    """Resolve the ``get`` URL argument to a list of URLs to archive.

    A literal URL becomes a one-element list; ``-`` reads newline-separated
    URLs from stdin (blank lines and surrounding whitespace stripped).
    """
    if url != "-":
        return [url]
    if sys.stdin.isatty():
        _fail(
            "Reading URLs from stdin ('get -') but stdin is a terminal. "
            "Pipe URLs in, e.g.: arciv list --json | jq -r .url | arciv get -",
            code=EXIT_USAGE,
        )
    return [line.strip() for line in sys.stdin if line.strip()]


@cli.command()
def add(
    directory: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        help="The directory to register (must exist).",
    ),
    name: str = typer.Argument(..., help="The unique name for this source."),
) -> None:
    """Register DIRECTORY as a source named NAME."""
    source = Source(
        name=name,
        path=str(directory.resolve()),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with PageDatabase(DB_PATH) as db:
        if not db.add_source(source):
            _fail(f"A source named '{name}' already exists.")
    logger.info(f"Added source '{name}' -> {source.path}")


@cli.command()
def remove(
    name: str = typer.Argument(..., help="The source name to unregister."),
) -> None:
    """Unregister the source named NAME (indexed pages are kept)."""
    with PageDatabase(DB_PATH) as db:
        if not db.remove_source(name):
            _fail(f"No source named '{name}'.", code=EXIT_NOINPUT)
    logger.info(f"Removed source '{name}'")


@cli.command()
def sources() -> None:
    """List registered sources.

    With --json, emits JSONL (one ``{"name", "path"}`` object per line).
    """
    with PageDatabase(DB_PATH) as db:
        registered = db.list_sources()
    if json_output():
        for source in registered:
            emit_json({"name": source.name, "path": source.path})
        return
    if not registered:
        # A hint, not data: keep it off stdout so pipes stay clean
        logger.info("No sources registered. Add one with: arciv add <dir> <name>")
        return
    for source in registered:
        emit(f"{source.name}\t{source.path}")


@cli.command()
def index(
    source: str | None = typer.Argument(
        None, help="Name of the registered source to index."
    ),
    all_sources: bool = typer.Option(
        False, "--all", help="Index every registered source."
    ),
) -> None:
    """Index stage: extract links from a registered SOURCE (or --all)."""
    if bool(source) == all_sources:
        _fail("Provide a source name or --all, not both.", code=EXIT_USAGE)

    with PageDatabase(DB_PATH) as db:
        if all_sources:
            urls = index_all(db)
        else:
            try:
                urls = index_source(db, source)
            except KeyError as e:
                _fail(str(e.args[0]), code=EXIT_NOINPUT)
    logger.info(f"Indexed {len(urls)} unique URLs")


@cli.command()
def fetch(
    refetch: bool = typer.Option(
        False,
        "--refetch",
        help="Re-download every known page, even fetched/failed ones.",
    ),
) -> None:
    """Fetch stage: download indexed URLs that are still pending."""
    with PageDatabase(DB_PATH) as db:
        fetched = fetch_pending(db, refetch=refetch)
        report(db, len(fetched))


@cli.command()
def parse(
    reparse: bool = typer.Option(
        False, "--reparse", help="Re-parse every fetched page, not just unparsed ones."
    ),
) -> None:
    """Parse stage: convert fetched HTML/PDFs into markdown."""
    with PageDatabase(DB_PATH) as db:
        parse_pending(db, reparse=reparse)


@cli.command()
def status() -> None:
    """Show pipeline-state counts and failure summary.

    With --json, emits a single JSON object of the counts plus a
    ``failures`` array.
    """
    with PageDatabase(DB_PATH) as db:
        counts = db.status_counts()
        failures = db.fail_summary()

    if json_output():
        emit_json(
            {
                **counts,
                "failures": [
                    {"domain": domain, "reason": reason, "count": count}
                    for domain, reason, count in failures
                ],
            }
        )
        return

    emit(f"Archive: {DB_PATH}")
    emit(f"Pages: {counts['total']} total")
    emit(f"  pending         {counts['pending']}")
    emit(f"  fetch failed    {counts['fetch_failed']}")
    emit(f"  awaiting parse  {counts['awaiting_parse']}")
    emit(f"  parse rejected  {counts['parse_rejected']}")
    emit(f"  parsed          {counts['parsed']}")

    if failures:
        emit("\nFailures by domain:")
        for domain, reason, count in failures[:10]:
            emit(f"  {domain}: {reason} ({count})")


@cli.command(name="list")
def list_pages(
    limit: int = typer.Option(
        20, "--n", min=0, help="Number of rows to show; 0 shows everything."
    ),
    reverse: bool = typer.Option(
        False, "--reverse", help="Oldest first instead of newest first."
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        help="Only show pages from this registered domain, e.g. medium.com.",
    ),
    null: bool = typer.Option(
        False,
        "--null",
        "-0",
        help="Separate records with a NUL byte instead of a newline (xargs -0).",
    ),
) -> None:
    """List fetched pages, newest first: fetch time, domain, URL.

    Columns are tab-separated so the output pipes cleanly into
    grep/cut/awk, e.g.: arciv list --n 0 | grep /tag/. With --json, emits
    JSONL (one object per line). With --null, records are NUL-separated.
    """
    with PageDatabase(DB_PATH) as db:
        pages = db.list_fetched(
            limit=limit or None, oldest_first=reverse, domain=domain
        )
    for page in pages:
        # ISO timestamp trimmed to seconds for readability
        fetched_at = (page.fetched_at or "")[:19]
        if json_output():
            record = json.dumps(
                {"fetched_at": fetched_at, "domain": page.domain, "url": page.url},
                ensure_ascii=False,
            )
        else:
            record = f"{fetched_at}\t{page.domain}\t{page.url}"
        emit(record, null=null)


@cli.command()
def path(
    url: str = typer.Argument(
        ..., help="The URL whose archived markdown path to print."
    ),
) -> None:
    """Print the filepath of URL's archived markdown.

    Composes with standard tools: cat/less/grep $(arciv path <URL>).
    With --json, emits ``{"url": ..., "path": ...}``.
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
        _fail(f"Unknown URL: {url}", code=EXIT_NOINPUT)
    if page.fail_reason:
        _fail(f"No markdown for {page.url}: {page.fail_reason}")
    if not page.fetched:
        _fail(f"{page.url} is still pending. Run: arciv fetch")
    if not page.parsed:
        _fail(f"{page.url} is fetched but not parsed yet. Run: arciv parse")
    md_path = SAVED_DIR / page.slug / "page.md"
    if not md_path.exists():
        _fail(f"Markdown file missing on disk: {md_path}")
    if json_output():
        emit_json({"url": page.url, "path": str(md_path)})
    else:
        emit(str(md_path))


@db_app.command(name="dir")
def db_dir() -> None:
    """Print the data directory that holds the database."""
    emit(str(DATA_DIR))


@db_app.command(name="remove")
def db_remove(
    force: bool = typer.Option(
        False, "--force", help="Delete without asking for confirmation."
    ),
) -> None:
    """Delete the SQLite database; archived files under saved/ are kept."""
    if not DB_PATH.exists():
        # Diagnostic, not data: keep it on stderr
        logger.info(f"No database at {DB_PATH}")
        return
    if not force:
        typer.confirm(f"Delete {DB_PATH}? All page/source tracking is lost", abort=True)
    # The WAL sidecar files belong to the main file and must go with it
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    emit(f"Deleted {DB_PATH}")


if __name__ == "__main__":
    cli()
