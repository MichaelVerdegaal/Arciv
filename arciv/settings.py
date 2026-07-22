"""Configuration: data directory layout and logging setup.

The data root defaults to the OS user data directory (Linux:
``~/.local/share/arciv``, Windows: ``%LOCALAPPDATA%\\arciv``), so the
archive has one fixed home regardless of where the command runs, and
lives outside any repo checkout, surviving reinstalls. Set
``ARCIV_DATA_DIR`` (in the environment or a ``.env`` file) to relocate
it, e.g. to ``./data`` when developing from a clone.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from platformdirs import user_data_dir

# Load environment variables from the nearest .env (cwd upward), must
# happen before any os.getenv below
load_dotenv()

# Data root holding the database, archived pages, and logs; override via
# ARCIV_DATA_DIR to relocate it (e.g. onto a synced drive)
DATA_DIR = Path(
    os.getenv("ARCIV_DATA_DIR") or user_data_dir("arciv", appauthor=False)
).resolve()
SAVED_DIR = DATA_DIR / "saved"
LOGS_DIR = DATA_DIR / "logs"


def _resolve_search_home() -> Path:
    """Where the optional ``arciv search`` extra keeps its model and index.

    Resolution order, first hit wins:

    1. ``ARCIV_SEARCH_HOME`` (explicit override).
    2. ``MICRORAG_HOME`` if set, or an existing ``~/.microrag`` when the new
       location does not exist yet - so a prior MicroRag install keeps working
       without re-downloading the model or re-indexing.
    3. ``DATA_DIR/search``, alongside the rest of the archive.
    """
    explicit = os.getenv("ARCIV_SEARCH_HOME")
    if explicit:
        return Path(explicit).resolve()
    default = DATA_DIR / "search"
    legacy_env = os.getenv("MICRORAG_HOME")
    if legacy_env:
        return Path(legacy_env).resolve()
    legacy_default = Path.home() / ".microrag"
    if legacy_default.is_dir() and not default.exists():
        return legacy_default.resolve()
    return default


# Home for the search model files and vector index (see _resolve_search_home).
SEARCH_HOME = _resolve_search_home()

# File constants
DB_PATH = DATA_DIR / "arciv.db"
# Optional, hand-edited TOML of URL rules; loaded ahead of the packaged defaults
# so user rules win on first match. Absent by default (defaults-only).
USER_RULES_PATH = DATA_DIR / "rules.toml"


# Warnings produced before logging is configured (see _env_int). They are
# emitted by configure_logger once handlers exist, so they show up in the
# format the user chose instead of loguru's import-time default.
_startup_warnings: list[str] = []


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer from the environment, falling back to default.

    A missing, non-integer, or below-``minimum`` value uses ``default``
    (with a warning for malformed input), so a typo in an ``ARCIV_*`` var
    degrades to the shipped behavior instead of crashing the CLI on startup.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        _startup_warnings.append(f"Ignoring invalid {name}={raw!r}; using {default}")
        return default
    if value < minimum:
        _startup_warnings.append(
            f"Ignoring out-of-range {name}={raw!r}; using {default}"
        )
        return default
    return value


# Pipeline tunables, overridable via ARCIV_* env vars; the fallbacks below
# are the defaults. The pipeline layer (core/pipeline) reads these and passes
# them into the core mechanisms, which keep their own neutral defaults so they
# stay usable without settings (e.g. in tests).
DEFAULT_CONCURRENCY = _env_int("ARCIV_CONCURRENCY", 8)
# Retries after the first attempt for transient fetch failures; 0 disables
# retrying entirely (one attempt per URL).
DEFAULT_MAX_RETRIES = _env_int("ARCIV_MAX_RETRIES", 2, minimum=0)
TIMEOUT_MS = _env_int("ARCIV_TIMEOUT_MS", 30_000)


# Maps the CLI's --color choice to loguru's colorize argument. "auto"
# becomes None so loguru auto-detects the sink's TTY and honors
# NO_COLOR / FORCE_COLOR.
_COLOR_TO_COLORIZE: dict[str, bool | None] = {
    "always": True,
    "never": False,
    "auto": None,
}


def configure_logger(
    level: str = "INFO", color: str = "auto", log_file: bool = True
) -> None:
    """Configure loguru to log to stderr (and a rotating file).

    Data belongs on stdout; everything diagnostic (logs, progress,
    summaries) goes to stderr so ``arciv list | cat`` shows only data.
    Calling this repeatedly is safe: handlers are reset first.

    Args:
        level: Console log level, e.g. "INFO", "DEBUG", "TRACE", "ERROR".
        color: One of "auto" (let loguru detect the TTY and honor
            NO_COLOR/FORCE_COLOR), "always", or "never".
        log_file: Also write a rotating DEBUG log file under LOGS_DIR.
    """
    logger.remove()
    colorize = _COLOR_TO_COLORIZE.get(color)

    # Shared format (color tags get stripped in file output)
    log_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Console on stderr so data printed to stdout (e.g. `arciv list`,
    # `arciv path`) stays clean and pipeable; logs are diagnostics, not data
    logger.add(
        sys.stderr,
        format=log_format,
        level=level,
        colorize=colorize,
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    # File - rotates daily, always at DEBUG for a full diagnostic trail;
    # retention keeps the logs dir from growing forever
    if log_file:
        logger.add(
            LOGS_DIR / "arciv.log",
            format=log_format,
            level="DEBUG",
            backtrace=True,
            diagnose=True,
            rotation="1 day",
            retention="30 days",
            enqueue=True,
        )

    # Settings problems found before logging existed (e.g. a malformed
    # ARCIV_* value read at import) surface now, in the configured format.
    while _startup_warnings:
        logger.warning(_startup_warnings.pop(0))
