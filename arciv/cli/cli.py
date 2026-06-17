"""Arciv CLI: archive management commands (built on Typer).

Layered archiving with ``get`` (index → fetch → parse in one go):

    arciv get https://example.com   # archive a single URL
    arciv get --file note.md        # archive all links in one file
    arciv get --dir ~/notes         # archive all links in a directory
    arciv list --json | jq -r .url | arciv get -   # archive piped URLs

Sources (named directories that can be re-archived any time):

    arciv add ~/vault/notes notes   # register source "notes" and archive it
    arciv archive notes             # re-index, fetch, and parse one source
    arciv archive --all             # archive every registered source
    arciv remove notes              # unregister it
    arciv sources                   # list registered sources

Individual pipeline stages, mainly for development:

    arciv index notes               # index one source
    arciv index --all               # index every source
    arciv fetch                     # download pending indexed URLs
    arciv parse                     # convert fetched pages to markdown

URL rules (skip or rewrite URLs before they are fetched):

    arciv rules list                # list rules in the order they apply
    arciv rules add domain x.com skip            # add a skip rule
    arciv rules add domain medium.com rewrite -r scribe.rip
    arciv rules remove 3            # remove the rule with that id

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
Data goes to stdout; all logs and diagnostics go to stderr, so
``arciv list | cat`` shows only data.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer
from loguru import logger
from typer.core import TyperGroup

from arciv.settings import DATA_DIR, DB_PATH, SAVED_DIR, configure_logger
from arciv.core.db import PageDatabase, Rule, Source
from arciv.core.db.models import RULE_ACTIONS, RULE_MATCH_TYPES
from arciv.core.fetch import process_url
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


# add_completion=False keeps the CLI surface identical to the old click one
# (no extra --install-completion/--show-completion options).
cli = typer.Typer(
    help="Arciv: personal knowledge archive.",
    no_args_is_help=True,
    add_completion=False,
    cls=GlobalOptionGroup,
)
db_app = typer.Typer(help="Inspect or manage the database file.", no_args_is_help=True)
cli.add_typer(db_app, name="db")
rules_app = typer.Typer(
    help="View, add, and remove URL-processing rules.", no_args_is_help=True
)
cli.add_typer(rules_app, name="rules")


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
    PruneMode.all: "EVERY page — the entire archive index",
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


def _validate_match_type(value: str) -> str:
    """Typer callback: reject an unknown rule match type during parsing.

    Runs before the command body so the choice is validated the way Typer
    intends, while still exiting EXIT_USAGE (not Typer's default 2) to keep
    the CLI's sysexits convention.
    """
    if value not in RULE_MATCH_TYPES:
        _fail(
            f"Unknown match type: {value!r}. "
            f"Choose one of: {', '.join(RULE_MATCH_TYPES)}.",
            code=EXIT_USAGE,
        )
    return value


def _validate_action(value: str) -> str:
    """Typer callback: reject an unknown rule action during parsing."""
    if value not in RULE_ACTIONS:
        _fail(
            f"Unknown action: {value!r}. Choose one of: {', '.join(RULE_ACTIONS)}.",
            code=EXIT_USAGE,
        )
    return value


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
        parse_pending(db)
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


@cli.command()
def add(
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
    to only register it, then archive later with ``arciv archive NAME``.
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


@cli.command()
def archive(
    source: Annotated[
        str | None,
        typer.Argument(help="Name of the registered source to archive."),
    ] = None,
    all_sources: Annotated[
        bool, typer.Option("--all", help="Archive every registered source.")
    ] = False,
) -> None:
    """Archive a source end to end: index, then batch-fetch and parse.

    Re-indexes first so notes added or removed since last time are picked up,
    then downloads and parses every URL found in one batch. Provide a source
    name or --all, not both.
    """
    if bool(source) == all_sources:
        _fail("Provide a source name or --all, not both.", code=EXIT_USAGE)

    with PageDatabase(DB_PATH) as db:
        if all_sources:
            sources_list = db.list_sources()
            if not sources_list:
                logger.info(
                    "No sources registered. Add one with: arciv add <dir> <name>"
                )
                return
            # One batch across every source beats a browser launch per source.
            result = archive_urls(db, index_all(db))
            logger.info(
                f"Archived {len(sources_list)} source(s): {len(result.urls)} "
                f"indexed, {len(result.fetched)} fetched, {result.parsed} parsed"
            )
            return
        try:
            result = archive_source(db, source)
        except KeyError as e:
            _fail(str(e.args[0]), code=EXIT_NOINPUT)
        _report_archive(source, result)


@cli.command()
def remove(
    name: Annotated[str, typer.Argument(help="The source name to unregister.")],
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
        pages = db.get_all() if refetch else db.get_unfetched()
        urls = [page.url for page in pages]
        fetched = fetch_urls(db, urls, refetch=refetch)
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
    """Parse stage: convert fetched HTML/PDFs into markdown."""
    with PageDatabase(DB_PATH) as db:
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
    - ``all`` wipes every page row — the whole archive index.

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
        typer.Option("--n", min=0, help="Number of rows to show; 0 shows everything."),
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
            processed, _ = process_url(url, db.list_rules())
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


@rules_app.command(name="list")
def rules_list() -> None:
    """List URL rules in the order they are applied (first match wins).

    Columns are tab-separated — id, match type, pattern, action, and the
    replacement/reason — so the output pipes cleanly into grep/cut/awk. The
    leading id is what ``arciv rules remove`` takes. With --json, emits JSONL
    (one object per line).
    """
    with PageDatabase(DB_PATH) as db:
        rules = db.list_rules()
    if json_output():
        for rule in rules:
            emit_json(
                {
                    "id": rule.id,
                    "match_type": rule.match_type,
                    "pattern": rule.pattern,
                    "action": rule.action,
                    "replacement": rule.replacement,
                    "position": rule.position,
                }
            )
        return
    if not rules:
        # A hint, not data: keep it off stdout so pipes stay clean
        logger.info(
            "No rules defined. Add one with: arciv rules add <match> <pattern> <action>"
        )
        return
    for rule in rules:
        emit(
            f"{rule.id}\t{rule.match_type}\t{rule.pattern}\t"
            f"{rule.action}\t{rule.replacement or ''}"
        )


@rules_app.command(name="add")
def rules_add(
    match_type: Annotated[
        str,
        typer.Argument(
            callback=_validate_match_type,
            help=f"How to match the URL: one of {', '.join(RULE_MATCH_TYPES)}.",
        ),
    ],
    pattern: Annotated[
        str, typer.Argument(help="The string compared against the URL.")
    ],
    action: Annotated[
        str,
        typer.Argument(
            callback=_validate_action,
            help=f"What to do on a match: one of {', '.join(RULE_ACTIONS)}.",
        ),
    ],
    replacement: Annotated[
        str | None,
        typer.Option(
            "--replacement",
            "-r",
            help=(
                "For rewrite: the new host (or regex replacement). "
                "For skip: the reason shown when archiving (optional)."
            ),
        ),
    ] = None,
) -> None:
    """Append a URL rule (a match plus an action).

    New rules go to the end of the list, so adding one never reorders the
    existing rules. See ``arciv rules list`` for the order they are applied.
    """
    # match_type and action are validated by their argument callbacks above.
    pattern = pattern.strip()
    replacement = (replacement or "").strip() or None

    if not pattern:
        _fail("Enter a pattern to match.", code=EXIT_USAGE)
    if action == "rewrite" and not replacement:
        _fail("A rewrite rule needs a replacement host.", code=EXIT_USAGE)

    with PageDatabase(DB_PATH) as db:
        rule = db.add_rule(
            Rule(
                match_type=match_type,
                pattern=pattern,
                action=action,
                replacement=replacement,
            )
        )
    logger.info(f"Added rule {rule.id}: {match_type} {pattern!r} -> {action}")
    if json_output():
        emit_json(
            {
                "id": rule.id,
                "match_type": rule.match_type,
                "pattern": rule.pattern,
                "action": rule.action,
                "replacement": rule.replacement,
                "position": rule.position,
            }
        )


@rules_app.command(name="remove")
def rules_remove(
    rule_id: Annotated[
        int,
        typer.Argument(help="The id of the rule to remove (see 'arciv rules list')."),
    ],
) -> None:
    """Remove a URL rule by its id."""
    with PageDatabase(DB_PATH) as db:
        if not db.remove_rule(rule_id):
            _fail(f"No rule with id {rule_id}.", code=EXIT_NOINPUT)
    logger.info(f"Removed rule {rule_id}")


if __name__ == "__main__":
    cli()
