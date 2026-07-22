"""Stdout output helpers and exit-code constants for the CLI.

Data goes to stdout; logs and diagnostics go to stderr (see
``configure_logger``). These helpers keep stdout output explicit and let
each command switch between human text and machine output (``--json``)
without re-implementing the choice.

The output mode is process-global state set once by the CLI callback
(``--json``), so commands can read it without threading a flag through
every call. That is a deliberate small bit of module state, not a
framework.
"""

import json
import sys
from typing import Any

import typer

# Exit codes. The 64/66 values follow the BSD sysexits convention so
# scripts can branch on them. (Typer's own argument-parsing errors still
# exit 2, the click/Unix convention for a usage error.)
EXIT_USAGE = 64  # bad/missing argument combination
EXIT_NOINPUT = 66  # unknown URL or missing source

# Whether --json was requested; set once by the CLI callback.
_json_output = False

# The -v count, set once by the CLI callback. Logging level is derived from
# it in configure_logger, but a couple of commands (e.g. `arciv search query`)
# also vary their stdout richness with it, so it is readable here too.
_verbosity = 0


def set_json_output(enabled: bool) -> None:
    """Record whether commands should emit machine (JSON) output."""
    global _json_output
    _json_output = enabled


def json_output() -> bool:
    """Whether --json was requested for this run."""
    return _json_output


def set_verbosity(level: int) -> None:
    """Record the -v count for this run."""
    global _verbosity
    _verbosity = level


def verbosity() -> int:
    """The -v count requested for this run (0 when unset)."""
    return _verbosity


def emit(text: str = "", *, null: bool = False) -> None:
    """Write one record to stdout.

    Both separators are written as raw bytes so the output is identical on
    every platform: no CRLF translation on Windows corrupting a NUL record
    or turning data lines into ``\\r\\n``.

    Args:
        text: The record to write (without a trailing separator).
        null: Terminate with a NUL byte instead of a newline, like
            ``find -print0``, so records survive odd characters and feed
            ``xargs -0``.
    """
    separator = b"\0" if null else b"\n"
    sys.stdout.buffer.write(text.encode("utf-8") + separator)
    sys.stdout.buffer.flush()


def emit_json(obj: Any) -> None:
    """Write one compact JSON object/array as a line on stdout."""
    typer.echo(json.dumps(obj, ensure_ascii=False))


def emit_pipeline_summary(
    *, indexed: int = 0, fetched: int = 0, parsed: int = 0, failed: int = 0
) -> None:
    """Emit one structured ``--json`` summary for a mutating pipeline command.

    The four mutating commands (``archive``, ``get``, ``fetch``, ``parse``)
    share this object shape so a script can assert an outcome inline without a
    follow-up ``status --json``. Each field counts what happened *this run*;
    stages a command doesn't perform stay 0 (e.g. ``fetch`` reports no
    ``indexed`` or ``parsed``).

    Args:
        indexed: Unique URLs found by the index stage.
        fetched: Pages successfully downloaded.
        parsed: Pages successfully converted to markdown.
        failed: Targeted URLs that ended the run with a failure reason.
    """
    emit_json(
        {
            "indexed": indexed,
            "fetched": fetched,
            "parsed": parsed,
            "failed": failed,
        }
    )
