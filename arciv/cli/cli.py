"""Arciv CLI: archive management commands (built on Typer).

One-shot archiving with ``get`` (index → fetch → parse in one go, nothing
tracked — the ephemeral, pipe-friendly path):

    arciv get https://example.com   # archive a single URL
    arciv get --file note.md        # archive all links in one file
    arciv get --dir ~/notes         # archive all links in a directory
    arciv list --json | jq -r .url | arciv get -   # archive piped URLs

Sources are registered directories you re-sync over time (the tracked path):

    arciv source add ~/vault/notes notes  # register "notes" and archive it
    arciv source update notes             # re-index, fetch, and parse it
    arciv source update --all             # update every registered source
    arciv source remove notes             # unregister it (asks first)
    arciv source                          # list registered sources
    arciv list --source notes             # pages indexed from one source

Individual pipeline stages, mainly for development:

    arciv index notes               # index one source
    arciv index --all               # index every source
    arciv fetch                     # download pending indexed URLs
    arciv parse                     # convert fetched pages to markdown

URL rules (skip or rewrite URLs before they are fetched):

    arciv rules list                # list active rules, in the order they apply
    arciv rules test <URL>          # show how the rules treat a URL

Rules are data, not commands: edit the TOML at ``<data dir>/rules.toml`` (see
``arciv db dir``); user rules load ahead of the packaged defaults.

Inspection:

    arciv status                    # pipeline counts + failure summary
    arciv list                      # fetched pages: time, domain, URL
    arciv path <URL>                # filepath of a page's markdown
    arciv prune failed              # drop stale rows: missing | failed | all
    arciv db dir                    # print the data directory path
    arciv db remove                 # delete the database (asks first)

Global options work before or after the command: ``-v``/``-vv`` for more
detail, ``-q`` for errors only, ``--color auto|always|never``, and
``--json`` to switch every command to machine-readable output on stdout.
The mutating commands (``source update``, ``get``, ``fetch``, ``parse``) emit
a structured ``{indexed, fetched, parsed, failed}`` summary under ``--json``.
``arciv --version`` prints the installed version. Data goes to stdout; all
logs and diagnostics go to stderr, so ``arciv list | cat`` shows only data.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer
from loguru import logger
from typer.core import TyperGroup

from arciv.settings import (
    DATA_DIR,
    DB_PATH,
    SAVED_DIR,
    USER_RULES_PATH,
    configure_logger,
)
from arciv.core.db import PageDatabase, Source
from arciv.core.urls import evaluate_url, load_rules, process_url
from arciv.core.pipeline import (
    ArchiveResult,
    archive_source,
    archive_urls,
    fetch_urls,
    parse_pending,
    report,
)
from arciv.core.index import (
    index_all,
    index_directory,
    index_file,
    index_source,
    register_urls,
)
from .output import (
    EXIT_NOINPUT,
    EXIT_USAGE,
    emit,
    emit_json,
    emit_pipeline_summary,
    json_output,
    set_json_output,
)


class GlobalOptionGroup(TyperGroup):
    """Let the global options work anywhere on the command line.

    Typer/Click only accept group-level options *before* the subcommand
    (``arciv --json status``). Users naturally write them after the command
    (``arciv status --json``), which Click otherwise rejects as an unknown
    option. This group hoists the recognized global tokens to the front
    before parsing, so both orders work.
    """

    # Global flags that take no value, and the long options that take one.
    _GLOBAL_FLAGS = frozenset({"-v", "--verbose", "-q", "--quiet", "--json"})
    _GLOBAL_VALUE_OPTS = frozenset({"--color"})

    def parse_args(self, ctx, args):
        hoisted: list[str] = []
        rest: list[str] = []
        i = 0
        while i < len(args):
            token = args[i]
            name = token.split("=", 1)[0]
            if token in self._GLOBAL_FLAGS:
                hoisted.append(token)
            elif (
                token.startswith("-")
                and not token.startswith("--")
                and len(token) > 1
                and all(c in "vq" for c in token[1:])
            ):
                # Bundled short flags made only of global ones, e.g. -vv, -qv.
                hoisted.append(token)
            elif name in self._GLOBAL_VALUE_OPTS:
                hoisted.append(token)
                # Pull along a separately-spelled value, e.g. "--color never".
                if "=" not in token and i + 1 < len(args):
                    i += 1
                    hoisted.append(args[i])
            else:
                rest.append(token)
            i += 1
        return super().parse_args(ctx, hoisted + rest)


# add_completion=True exposes --install-completion/--show-completion and turns
# on shell completion for commands and flags. The GlobalOptionGroup only
# reorders recognized global tokens during a normal parse, so it does not
# interfere with the completion machinery.
cli = typer.Typer(
    help="Arciv: personal knowledge archive.",
    no_args_is_help=True,
    add_completion=True,
    cls=GlobalOptionGroup,
)
db_app = typer.Typer(help="Inspect or manage the database file.", no_args_is_help=True)
cli.add_typer(db_app, name="db")
rules_app = typer.Typer(
    help="Inspect URL-processing rules (edit them in the data dir's rules.toml).",
    no_args_is_help=True,
)
cli.add_typer(rules_app, name="rules")
# invoke_without_command lets a bare ``arciv source`` list the sources (see
# source_main), while ``source add/update/remove/list`` are the subcommands.
source_app = typer.Typer(
    help="Register, update, list, and remove sources.",
    invoke_without_command=True,
)
cli.add_typer(source_app, name="source")


# Choices for the global --color option. A Literal gives Typer the same
# choice validation and shell completion as an Enum, but hands the command a
# plain str (no .value unwrapping) and needs no separate class.
ColorWhen = Literal["auto", "always", "never"]


class PruneMode(str, Enum):
    """What ``arciv prune`` deletes (see the command's help)."""

    missing = "missing"
    failed = "failed"
    all = "all"


# Human-readable descriptions for each prune mode, shown in the confirmation
# prompt so the operator sees exactly what is about to be deleted.
_PRUNE_DESCRIPTIONS: dict[PruneMode, str] = {
    PruneMode.missing: "failed pages no longer indexed in any note",
    PruneMode.failed: "all failed pages (fetch failures and skipped/too-short)",
    PruneMode.all: "EVERY page (the entire archive index)",
}


def _fail(message: str, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit, no traceback.

    Mirrors click's ClickException/UsageError: a clean ``Error: ...`` line
    and a non-zero exit code. EXIT_USAGE (64) marks a bad argument
    combination, EXIT_NOINPUT (66) an unknown URL or missing source, and
    the default 1 a generic operation failure.
    """
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)


def _arciv_version() -> str:
    """The installed arciv version, or "unknown" if metadata is unavailable
    (e.g. running from a source tree that was never installed)."""
    try:
        return version("arciv")
    except PackageNotFoundError:
        return "unknown"


def _version_callback(value: bool) -> None:
    """Print the version and exit, the conventional ``--version`` behaviour.

    Eager so it runs before any other option is processed, letting
    ``arciv --version`` work without a subcommand.
    """
    if value:
        emit(f"arciv {_arciv_version()}")
        raise typer.Exit()


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
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase log detail; repeat for more (-v debug, -vv trace).",
        ),
    ] = 0,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Only show errors (wins over --verbose)."),
    ] = False,
    color: Annotated[
        ColorWhen,
        typer.Option("--color", help="Colorize logs: auto, always, or never."),
    ] = "auto",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable output on stdout."),
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed arciv version and exit.",
        ),
    ] = False,
) -> None:
    """Arciv: personal knowledge archive.

    Global options go before the command, e.g. ``arciv -v --json status``.
    Data goes to stdout; logs and diagnostics go to stderr.
    """
    configure_logger(level=_resolve_level(verbose, quiet), color=color)
    set_json_output(json_out)


@cli.command()
def get(
    url: Annotated[
        str | None,
        typer.Argument(help="A single URL to archive, or '-' to read URLs from stdin."),
    ] = None,
    file_path: Annotated[
        Path | None,
        typer.Option(
            "--file",
            exists=True,
            dir_okay=False,
            help="Archive all links within a single file.",
        ),
    ] = None,
    dir_path: Annotated[
        Path | None,
        typer.Option(
            "--dir",
            exists=True,
            file_okay=False,
            help="Archive all links of all files within a directory.",
        ),
    ] = None,
    refetch: Annotated[
        bool,
        typer.Option("--refetch", help="Re-download pages even if already fetched."),
    ] = False,
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
        parsed = parse_pending(db)
        if json_output():
            emit_pipeline_summary(
                indexed=len(urls),
                fetched=len(fetched),
                parsed=parsed,
                failed=_count_failed(db, urls),
            )
        else:
            report(db, len(fetched), urls)


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


def _report_archive(name: str, result: ArchiveResult) -> None:
    """Log a one-line summary of a source archival run."""
    logger.info(
        f"Archived source '{name}': {len(result.urls)} indexed, "
        f"{len(result.fetched)} fetched, {result.parsed} parsed"
    )


def _count_failed(db: PageDatabase, urls: list[str]) -> int:
    """How many of ``urls`` carry a failure reason now.

    Counts the URLs this run targeted that ended with a ``fail_reason`` set
    (fetch failures plus parse rejections/skips), matching the run-scoped
    failure summary ``report`` logs to stderr.
    """
    return len(db.failures_for(urls))


def _emit_archive_summary(db: PageDatabase, result: ArchiveResult) -> None:
    """Emit the --json pipeline summary for an ArchiveResult."""
    emit_pipeline_summary(
        indexed=len(result.urls),
        fetched=len(result.fetched),
        parsed=result.parsed,
        failed=_count_failed(db, result.urls),
    )


def _list_sources() -> None:
    """List registered sources to stdout (tab-separated, or JSONL with --json).

    Shared by ``arciv source`` (no subcommand) and ``arciv source list``.
    """
    with PageDatabase(DB_PATH) as db:
        registered = db.list_sources()
    if json_output():
        for source in registered:
            emit_json({"name": source.name, "path": source.path})
        return
    if not registered:
        # A hint, not data: keep it off stdout so pipes stay clean
        logger.info(
            "No sources registered. Add one with: arciv source add <dir> <name>"
        )
        return
    for source in registered:
        emit(f"{source.name}\t{source.path}")


@source_app.callback(invoke_without_command=True)
def source_main(ctx: typer.Context) -> None:
    """Register, update, list, and remove sources.

    A source is a directory whose notes are indexed for links to archive, and
    which you re-sync over time with ``source update``. With no subcommand,
    ``arciv source`` lists the registered sources. (Contrast ``arciv get``,
    which archives a one-off URL/file/directory and tracks nothing.)
    """
    if ctx.invoked_subcommand is None:
        _list_sources()


@source_app.command(name="list")
def source_list() -> None:
    """List registered sources (same as a bare ``arciv source``).

    With --json, emits JSONL (one ``{"name", "path"}`` object per line).
    """
    _list_sources()


@source_app.command(name="add")
def source_add(
    directory: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            help="The directory to register (must exist).",
        ),
    ],
    name: Annotated[str, typer.Argument(help="The unique name for this source.")],
    no_archive: Annotated[
        bool,
        typer.Option(
            "--no-archive",
            help="Only register the source; skip indexing/fetching/parsing it now.",
        ),
    ] = False,
) -> None:
    """Register DIRECTORY as a source named NAME and archive it.

    After registering, the source is indexed and every URL found is fetched
    and parsed in one batch (index, then fetch, then parse). Pass --no-archive
    to only register it, then archive later with ``arciv source update NAME``.
    """
    source = Source(
        name=name,
        path=str(directory.resolve()),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with PageDatabase(DB_PATH) as db:
        if not db.add_source(source):
            _fail(f"A source named '{name}' already exists.")
        logger.info(f"Added source '{name}' -> {source.path}")
        if no_archive:
            return
        _report_archive(name, archive_source(db, name))


@source_app.command(name="update")
def source_update(
    name: Annotated[
        str | None,
        typer.Argument(help="Name of the registered source to update."),
    ] = None,
    all_sources: Annotated[
        bool, typer.Option("--all", help="Update every registered source.")
    ] = False,
) -> None:
    """Update a source end to end: re-index, then batch-fetch and parse.

    Re-indexes first so notes added or removed since last time are picked up,
    then downloads and parses whatever is not fetched/parsed yet, in one batch.
    Provide a source name or --all, not both.
    """
    if bool(name) == all_sources:
        _fail("Provide a source name or --all, not both.", code=EXIT_USAGE)

    with PageDatabase(DB_PATH) as db:
        if all_sources:
            sources_list = db.list_sources()
            if not sources_list:
                logger.info(
                    "No sources registered. Add one with: arciv source add <dir> <name>"
                )
                return
            # One batch across every source beats a browser launch per source.
            result = archive_urls(db, index_all(db))
            if json_output():
                _emit_archive_summary(db, result)
            else:
                logger.info(
                    f"Updated {len(sources_list)} source(s): {len(result.urls)} "
                    f"indexed, {len(result.fetched)} fetched, {result.parsed} parsed"
                )
            return
        try:
            result = archive_source(db, name)
        except KeyError as e:
            _fail(str(e.args[0]), code=EXIT_NOINPUT)
        if json_output():
            _emit_archive_summary(db, result)
        else:
            _report_archive(name, result)


@source_app.command(name="remove")
def source_remove(
    name: Annotated[str, typer.Argument(help="The source name to unregister.")],
    force: Annotated[
        bool, typer.Option("--force", help="Remove without asking for confirmation.")
    ] = False,
    remove_files: Annotated[
        bool,
        typer.Option(
            "--remove-files",
            help=(
                "Also delete the archived files of pages linked only by this "
                "source (pages also linked elsewhere are kept)."
            ),
        ),
    ] = False,
) -> None:
    """Unregister the source named NAME. Asks first unless --force is given.

    By default the indexed pages are kept; only the source registration and
    its link attribution go away. Pass --remove-files to also delete the
    archived files (and rows) of pages this source links exclusively — pages
    another source or an ad-hoc ``get`` run still points at are left intact.
    """
    with PageDatabase(DB_PATH) as db:
        if db.get_source(name) is None:
            _fail(f"No source named '{name}'.", code=EXIT_NOINPUT)
        if not force:
            prompt = f"Remove source '{name}'?"
            if remove_files:
                prompt += (
                    " This also deletes the archived files of pages linked "
                    "only by this source"
                )
            typer.confirm(prompt, abort=True)
        # Compute and delete the exclusively-linked pages while the source's
        # links still carry its name; remove_source's cascade would NULL them.
        slugs = db.prune_source_pages(name) if remove_files else []
        db.remove_source(name)

    removed_folders = 0
    for slug in slugs:
        # A blank slug would resolve to SAVED_DIR itself; never recurse into it
        if not slug:
            continue
        folder = SAVED_DIR / slug
        if folder.is_dir():
            shutil.rmtree(folder)
            removed_folders += 1

    logger.info(f"Removed source '{name}'")
    if remove_files:
        emit(
            f"Removed {len(slugs)} page(s) linked only by '{name}'; "
            f"deleted {removed_folders} saved folder(s)."
        )


@cli.command()
def index(
    source: Annotated[
        str | None,
        typer.Argument(help="Name of the registered source to index."),
    ] = None,
    all_sources: Annotated[
        bool, typer.Option("--all", help="Index every registered source.")
    ] = False,
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
    refetch: Annotated[
        bool,
        typer.Option(
            "--refetch",
            help="Re-download every known page, even fetched/failed ones.",
        ),
    ] = False,
) -> None:
    """Fetch stage: download indexed URLs that are still pending."""
    with PageDatabase(DB_PATH) as db:
        # Select the URLs up front so report() can scope its failure summary
        # to exactly the pages this run touched (refetch reprocesses all).
        urls = db.get_all_urls() if refetch else db.get_unfetched_urls()
        fetched = fetch_urls(db, urls, refetch=refetch)
        if json_output():
            # fetch neither indexes nor parses, so those counts stay 0.
            emit_pipeline_summary(fetched=len(fetched), failed=_count_failed(db, urls))
        else:
            report(db, len(fetched), urls)


@cli.command()
def parse(
    reparse: Annotated[
        bool,
        typer.Option(
            "--reparse", help="Re-parse every fetched page, not just unparsed ones."
        ),
    ] = False,
) -> None:
    """Parse stage: convert fetched HTML/PDFs into markdown.

    With --json, emits a structured ``{indexed, fetched, parsed, failed}``
    summary of this run.
    """
    with PageDatabase(DB_PATH) as db:
        if json_output():
            # Capture the URLs this run will attempt up front so the failed
            # count is scoped to them (rejections set fail_reason).
            urls = db.get_fetched_urls() if reparse else db.get_unparsed_urls()
            parsed = parse_pending(db, reparse=reparse)
            emit_pipeline_summary(parsed=parsed, failed=_count_failed(db, urls))
        else:
            parse_pending(db, reparse=reparse)


@cli.command()
def prune(
    mode: Annotated[
        PruneMode,
        typer.Argument(
            help=(
                "missing: drop failed rows no longer indexed; "
                "failed: drop all failed rows; "
                "all: drop every row (destructive)."
            ),
        ),
    ],
    force: Annotated[
        bool, typer.Option("--force", help="Delete without asking for confirmation.")
    ] = False,
) -> None:
    """Delete stale page rows and their archived files under saved/.

    Three modes, narrowest first:

    - ``missing`` removes failed pages that no note links to anymore (the dead
      rows left when a URL drops out of the notes and re-indexing unlinks it).
    - ``failed`` removes every page with a failure reason, indexed or not.
    - ``all`` wipes every page row, the whole archive index.

    The matching ``saved/<slug>/`` folders are deleted too, so disk space is
    reclaimed. Link rows are removed alongside the pages; registered sources
    are untouched. Asks for confirmation unless --force is given.
    """
    with PageDatabase(DB_PATH) as db:
        targets = db.prune_pages(mode.value, dry_run=True)
        if not targets:
            # Diagnostic, not data: keep it on stderr so pipes stay clean
            logger.info(f"Nothing to prune for '{mode.value}'.")
            return
        if not force:
            typer.confirm(
                f"Delete {len(targets)} page(s) "
                f"({_PRUNE_DESCRIPTIONS[mode]}) and their saved files?",
                abort=True,
            )
        deleted = db.prune_pages(mode.value)

    removed_folders = 0
    for slug in deleted:
        # A blank slug would resolve to SAVED_DIR itself; never recurse into it
        if not slug:
            continue
        folder = SAVED_DIR / slug
        if folder.is_dir():
            shutil.rmtree(folder)
            removed_folders += 1

    emit(f"Pruned {len(deleted)} page(s); removed {removed_folders} saved folder(s).")


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
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            min=0,
            help="Number of rows to show; 0 shows everything.",
        ),
    ] = 20,
    reverse: Annotated[
        bool, typer.Option("--reverse", help="Oldest first instead of newest first.")
    ] = False,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            help="Only show pages from this registered domain, e.g. medium.com.",
        ),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            help="Only show pages indexed from this registered source.",
        ),
    ] = None,
    null: Annotated[
        bool,
        typer.Option(
            "--null",
            "-0",
            help="Separate records with a NUL byte instead of a newline (xargs -0).",
        ),
    ] = False,
) -> None:
    """List fetched pages, newest first: fetch time, domain, URL.

    Columns are tab-separated so the output pipes cleanly into
    grep/cut/awk, e.g.: arciv list -n 0 | grep /tag/. Restrict to one
    registered source with --source NAME (or one domain with --domain).
    With --json, emits JSONL (one object per line). With --null, records
    are NUL-separated.
    """
    with PageDatabase(DB_PATH) as db:
        if source is not None and db.get_source(source) is None:
            _fail(f"No source named '{source}'.", code=EXIT_NOINPUT)
        pages = db.list_fetched(
            limit=limit or None, oldest_first=reverse, domain=domain, source=source
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
    url: Annotated[
        str, typer.Argument(help="The URL whose archived markdown path to print.")
    ],
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
            processed, _ = process_url(url, load_rules(USER_RULES_PATH))
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
    force: Annotated[
        bool, typer.Option("--force", help="Delete without asking for confirmation.")
    ] = False,
    remove_files: Annotated[
        bool,
        typer.Option(
            "--remove-files", help="Also delete the archived files under saved/."
        ),
    ] = False,
) -> None:
    """Delete the SQLite database.

    By default the archived files under saved/ are kept; pass --remove-files
    to delete those too.
    """
    if not DB_PATH.exists() and not (remove_files and SAVED_DIR.is_dir()):
        # Diagnostic, not data: keep it on stderr
        logger.info(f"No database at {DB_PATH}")
        return
    if not force:
        prompt = f"Delete {DB_PATH}? All page/source tracking is lost"
        if remove_files:
            prompt += f" (and all archived files under {SAVED_DIR})"
        typer.confirm(prompt, abort=True)
    # The WAL sidecar files belong to the main file and must go with it
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    emit(f"Deleted {DB_PATH}")
    if remove_files and SAVED_DIR.is_dir():
        shutil.rmtree(SAVED_DIR)
        emit(f"Removed archived files under {SAVED_DIR}")


def _describe_actions(rule) -> str:
    """One-line summary of a rule's actions for ``rules list``."""
    parts: list[str] = []
    for action in rule.actions:
        if action.type == "skip":
            parts.append(f"skip ({action.reason})" if action.reason else "skip")
        elif action.type == "prepend":
            parts.append(f"prepend {action.text!r}")
        elif action.type == "replace":
            parts.append(f"replace {action.old!r} -> {action.new!r}")
        elif action.type == "regex_replace":
            parts.append(f"regex_replace {action.pattern!r} -> {action.replacement!r}")
        else:
            parts.append(action.type)
    return "; ".join(parts)


@rules_app.command(name="list")
def rules_list() -> None:
    """List the active URL rules in the order they apply (first match wins).

    Shows the merged list: the user's ``rules.toml`` (if any) ahead of the
    packaged defaults. Columns are tab-separated (name, match type, pattern,
    and the action summary) so the output pipes cleanly into grep/cut/awk.
    With --json, emits JSONL (one object per line).
    """
    rules = load_rules(USER_RULES_PATH)
    if json_output():
        for rule in rules:
            emit_json(
                {
                    "name": rule.name,
                    "type": rule.match_type,
                    "match": rule.pattern,
                    "actions": [vars(action) for action in rule.actions],
                }
            )
        return
    for rule in rules:
        emit(
            f"{rule.name}\t{rule.match_type}\t{rule.pattern}\t{_describe_actions(rule)}"
        )


@rules_app.command(name="test")
def rules_test(
    url: Annotated[
        str, typer.Argument(help="The URL to run through the active rule list.")
    ],
) -> None:
    """Show what the active rules do to URL: skip, rewrite, or pass through.

    Runs URL through the same processing the index and fetch stages use (the
    plumbing guards, then the rules, then canonicalization) and prints the
    verdict, naming the rule responsible for a skip or rewrite. Lets you tune a
    rule in rules.toml and check it without a full index run.

    With --json, emits a single object: ``{"url", "verdict", "target",
    "reason", "rule"}`` where verdict is skipped, rewritten, or passthrough.
    """
    verdict = evaluate_url(url, load_rules(USER_RULES_PATH))
    rule_name = verdict.rule.name if verdict.rule else None

    if json_output():
        emit_json(
            {
                "url": url,
                "verdict": verdict.verdict,
                "target": verdict.url,
                "reason": verdict.reason,
                "rule": rule_name,
            }
        )
        return

    if verdict.verdict == "skipped":
        line = f"skipped: {verdict.reason}"
    elif verdict.verdict == "rewritten":
        line = f"rewritten -> {verdict.url}"
    else:
        line = f"passthrough: {verdict.url}"
    if rule_name is not None:
        line += f" (rule {rule_name!r})"
    emit(line)


if __name__ == "__main__":
    cli()
