"""Configuration: data directory layout and logging setup.

The data root defaults to the OS user data directory (Linux:
``~/.local/share/arciv``, Windows: ``%LOCALAPPDATA%\\arciv``), so the
archive has one fixed home regardless of where the command runs, and
lives outside any repo checkout, so the future backend container can
mount it directly. Set ``ARCIV_DATA_DIR`` (in the environment or a
``.env`` file) to relocate it, e.g. to ``./data`` when developing from
a clone.
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

# File constants
DB_PATH = DATA_DIR / "arciv.db"


# Maps the CLI's --color choice to loguru's colorize argument. "auto"
# becomes None so loguru auto-detects the sink's TTY and honors
# NO_COLOR / FORCE_COLOR.
_COLOR_TO_COLORIZE: dict[str, bool | None] = {
    "always": True,
    "never": False,
    "auto": None,
}


def configure_logger(level: str = "INFO", color: str = "auto") -> None:
    """Configure loguru to log to stderr (and a rotating file).

    Data belongs on stdout; everything diagnostic (logs, progress,
    summaries) goes to stderr so ``arciv list | cat`` shows only data.
    Calling this repeatedly is safe: handlers are reset first.

    Args:
        level: Console log level, e.g. "INFO", "DEBUG", "TRACE", "ERROR".
        color: One of "auto" (let loguru detect the TTY and honor
            NO_COLOR/FORCE_COLOR), "always", or "never".
    """
    logger.remove()
    colorize = _COLOR_TO_COLORIZE.get(color)

    # Shared format (color tags get stripped in file output)
    log_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Console sink on stderr so data on stdout stays clean
    logger.add(
        sys.stderr,
        format=log_format,
        level=level,
        colorize=colorize,
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    # File - rotates daily, always at DEBUG for a full diagnostic trail
    logger.add(
        LOGS_DIR / "arciv.log",
        format=log_format,
        level="DEBUG",
        backtrace=True,
        diagnose=True,
        rotation="1 day",
        enqueue=True,
    )
