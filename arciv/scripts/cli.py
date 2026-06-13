"""Arciv CLI: archive management commands (built on cyclopts).

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
from pathlib import Path
from typing import Annotated

from cyclopts import App, CycloptsError, Parameter
from cyclopts.types import ExistingDirectory
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
from .errors import ArcivError, UsageError
from .output import (
    EXIT_FAILURE,
    EXIT_NOINPUT,
    EXIT_OK,
    EXIT_USAGE,
    emit,
    emit_json,
    json_output,
    set_json_output,
)

app = App(
    name="arciv",
    help="Arciv: personal knowledge archive.",
    # Handle our own errors/exit codes in main(); don't let cyclopts
    # sys.exit() out from under us. It still prints its formatted error.
    exit_on_error=False,
    print_error=True,
    # Let `--` mark end-of-options, e.g. `arciv add -- --weird-name dir`.
    end_of_options_delimiter="--",
    # Let KeyboardInterrupt propagate so main() can print "Aborted".
    suppress_keyboard_interrupt=False,
)
db_app = App(name="db", help="Inspect or manage the database file.")
app.command(db_app)


@app.command
def get(
    url: Annotated[str | None, Parameter(allow_leading_hyphen=True)] = None,
    *,
    file_path: Annotated[Path | None, Parameter(name="--file")] = None,
    dir_path: Annotated[Path | None, Parameter(name="--dir")] = None,
    refetch: bool = False,
) -> None:
    """Archive a URL, the links in a file, or a whole directory.

    Runs the full pipeline (index → fetch → parse) on exactly one target.
    Pass ``-`` as the URL to read newline-separated URLs from stdin.

    Args:
        url: A single URL to archive, or ``-`` to read URLs from stdin.
        file_path: Archive all links within a single file.
        dir_path: Archive all links of all files within a directory.
        refetch: Re-download pages even if already fetched.
    """
    targets = [t for t in (url, file_path, dir_path) if t is not None]
    if len(targets) != 1:
        raise UsageError("Provide exactly one of: URL, --file, or --dir.")
    if file_path is not None and not file_path.is_file():
        raise UsageError(f"Not a file: {file_path}")
    if dir_path is not None and not dir_path.is_dir():
        raise UsageError(f"Not a directory: {dir_path}")

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
        raise UsageError(
            "Reading URLs from stdin ('get -') but stdin is a terminal. "
            "Pipe URLs in, e.g.: arciv list --json | jq -r .url | arciv get -"
        )
    return [line.strip() for line in sys.stdin if line.strip()]


@app.command
def add(directory: ExistingDirectory, name: str) -> None:
    """Register a directory as a named source.

    Args:
        directory: The directory to register (must exist).
        name: The unique name for this source.
    """
    source = Source(
        name=name,
        path=str(directory.resolve()),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with PageDatabase(DB_PATH) as db:
        if not db.add_source(source):
            raise ArcivError(f"A source named '{name}' already exists.")
    logger.info(f"Added source '{name}' -> {source.path}")


@app.command
def remove(name: str) -> None:
    """Unregister the named source (indexed pages are kept).

    Args:
        name: The source name to unregister.
    """
    with PageDatabase(DB_PATH) as db:
        if not db.remove_source(name):
            raise ArcivError(f"No source named '{name}'.", EXIT_NOINPUT)
    logger.info(f"Removed source '{name}'")


@app.command
def sources() -> None:
    """List registered sources (name and path)."""
    with PageDatabase(DB_PATH) as db:
        registered = db.list_sources()
    if json_output():
        for source in registered:
            emit_json({"name": source.name, "path": source.path})
        return
    if not registered:
        logger.info("No sources registered. Add one with: arciv add <dir> <name>")
        return
    for source in registered:
        emit(f"{source.name}\t{source.path}")


@app.command
def index(
    source: str | None = None,
    *,
    all_sources: Annotated[bool, Parameter(name="--all")] = False,
) -> None:
    """Index stage: extract links from a registered source (or --all).

    Args:
        source: Name of the registered source to index.
        all_sources: Index every registered source.
    """
    if bool(source) == all_sources:
        raise UsageError("Provide a source name or --all, not both.")

    with PageDatabase(DB_PATH) as db:
        if all_sources:
            urls = index_all(db)
        else:
            try:
                urls = index_source(db, source)
            except KeyError as e:
                raise ArcivError(str(e.args[0]), EXIT_NOINPUT)
    logger.info(f"Indexed {len(urls)} unique URLs")


@app.command
def fetch(*, refetch: bool = False) -> None:
    """Fetch stage: download indexed URLs that are still pending.

    Args:
        refetch: Re-download every known page, even fetched/failed ones.
    """
    with PageDatabase(DB_PATH) as db:
        fetched = fetch_pending(db, refetch=refetch)
        report(db, len(fetched))


@app.command
def parse(*, reparse: bool = False) -> None:
    """Parse stage: convert fetched HTML/PDFs into markdown.

    Args:
        reparse: Re-parse every fetched page, not just unparsed ones.
    """
    with PageDatabase(DB_PATH) as db:
        parse_pending(db, reparse=reparse)


@app.command
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


@app.command(name="list")
def list_pages(
    *,
    limit: Annotated[int, Parameter(name="--n")] = 20,
    reverse: bool = False,
    domain: str | None = None,
    null: Annotated[bool, Parameter(name=["--null", "-0"])] = False,
) -> None:
    """List fetched pages, newest first: fetch time, domain, URL.

    Columns are tab-separated so the output pipes cleanly into
    grep/cut/awk, e.g.: ``arciv list --n 0 | grep /tag/``. With --json,
    emits JSONL (one object per line). With --null, records are
    NUL-separated for ``xargs -0``.

    Args:
        limit: Number of rows to show; 0 shows everything.
        reverse: Oldest first instead of newest first.
        domain: Only show pages from this registered domain, e.g. medium.com.
        null: Separate records with a NUL byte instead of a newline.
    """
    if limit < 0:
        raise UsageError("--n must be 0 or greater (0 means everything).")
    # NOTE: zero matches exits 0 with empty output (least surprising).
    # TODO: a grep-style --exit-on-empty could return non-zero instead.
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


@app.command
def path(url: str) -> None:
    """Print the filepath of a URL's archived markdown.

    Composes with standard tools: ``cat/less/grep $(arciv path <URL>)``.
    With --json, emits ``{"url": ..., "path": ...}``.

    Args:
        url: The URL whose archived markdown path to print.
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
        raise ArcivError(f"Unknown URL: {url}", EXIT_NOINPUT)
    if page.fail_reason:
        raise ArcivError(f"No markdown for {page.url}: {page.fail_reason}")
    if not page.fetched:
        raise ArcivError(f"{page.url} is still pending. Run: arciv fetch")
    if not page.parsed:
        raise ArcivError(f"{page.url} is fetched but not parsed yet. Run: arciv parse")
    md_path = SAVED_DIR / page.slug / "page.md"
    if not md_path.exists():
        raise ArcivError(f"Markdown file missing on disk: {md_path}")
    if json_output():
        emit_json({"url": page.url, "path": str(md_path)})
    else:
        emit(str(md_path))


@db_app.command(name="dir")
def db_dir() -> None:
    """Print the data directory that holds the database."""
    emit(str(DATA_DIR))


@db_app.command(name="remove")
def db_remove(*, force: bool = False) -> None:
    """Delete the SQLite database; archived files under saved/ are kept.

    Args:
        force: Delete without asking for confirmation.
    """
    if not DB_PATH.exists():
        logger.info(f"No database at {DB_PATH}")
        return
    if not force:
        if not sys.stdin.isatty():
            raise UsageError(
                f"Refusing to delete {DB_PATH} without confirmation. "
                "Pass --force to delete non-interactively."
            )
        answer = input(f"Delete {DB_PATH}? All page/source tracking is lost [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise ArcivError("Aborted.")
    # The WAL sidecar files belong to the main file and must go with it
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    emit(f"Deleted {DB_PATH}")


def _resolve_level(verbose: int, quiet: bool) -> str:
    """Map -q / -v / -vv to a loguru level (quiet wins over verbose)."""
    if quiet:
        return "ERROR"
    if verbose >= 2:
        return "TRACE"
    if verbose == 1:
        return "DEBUG"
    return "INFO"


@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[
        int, Parameter(name=["--verbose", "-v"], count=True, negative=[])
    ] = 0,
    quiet: Annotated[bool, Parameter(name=["--quiet", "-q"], negative=[])] = False,
    color: Annotated[str, Parameter(name="--color")] = "auto",
    json_out: Annotated[bool, Parameter(name="--json", negative=[])] = False,
) -> object:
    """Arciv: personal knowledge archive.

    Args:
        verbose: Increase log detail; repeat for more (-v debug, -vv trace).
        quiet: Only show errors (wins over --verbose).
        color: Colorize logs: auto (default), always, or never.
        json_out: Emit machine-readable output on stdout.
    """
    configure_logger(level=_resolve_level(verbose, quiet), color=color)
    set_json_output(json_out)
    return app(tokens)


# Keep `--` working as end-of-options for the *subcommand*: stop the meta
# launcher from consuming it so it reaches the inner app() unchanged.
app.meta.end_of_options_delimiter = ""


def main() -> int:
    """Console entry point. Returns a process exit code."""
    try:
        app.meta()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return EXIT_OK
        return code if isinstance(code, int) else EXIT_FAILURE
    except KeyboardInterrupt:
        print("Aborted", file=sys.stderr)
        return 130
    except ArcivError as exc:
        logger.error(str(exc))
        return exc.exit_code
    except CycloptsError:
        # cyclopts already printed a formatted message to stderr
        return EXIT_USAGE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
