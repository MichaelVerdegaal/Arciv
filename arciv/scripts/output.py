"""Stdout output helpers and exit-code constants for the CLI.

Data goes to stdout; logs/diagnostics go to stderr (see
``configure_logger``). These helpers keep stdout output explicit and let
every command switch between human text and machine output (``--json``)
without each command re-implementing the choice.

The output mode is process-global state set once by the CLI launcher
(``--json``), so commands can read it without threading a flag through
every call. That is a deliberate small bit of module state, not a
framework.
"""

import json
import sys
from typing import Any

# Exit codes. Plain ints (not os.EX_*, which is Unix-only and would break
# the import on Windows). The 64/65/66 values follow the BSD sysexits
# convention so scripts can branch on them.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 64  # bad/missing argument combination
EXIT_DATAERR = 65  # input data was present but unusable
EXIT_NOINPUT = 66  # unknown URL or missing source

# Whether --json was requested; set once by the launcher.
_json_output = False


def set_json_output(enabled: bool) -> None:
    """Record whether commands should emit machine (JSON) output."""
    global _json_output
    _json_output = enabled


def json_output() -> bool:
    """Whether --json was requested for this run."""
    return _json_output


def emit(text: str = "", *, null: bool = False) -> None:
    """Write one record to stdout.

    Args:
        text: The record to write (without a trailing separator).
        null: Terminate with a NUL byte instead of a newline, like
            ``find -print0``, so records survive odd characters and feed
            ``xargs -0``. Writes raw bytes to avoid CRLF translation on
            Windows corrupting the separator.
    """
    if null:
        sys.stdout.buffer.write(text.encode("utf-8") + b"\0")
        sys.stdout.buffer.flush()
    else:
        print(text)


def emit_json(obj: Any) -> None:
    """Write one compact JSON object/array as a line on stdout."""
    print(json.dumps(obj, ensure_ascii=False))
