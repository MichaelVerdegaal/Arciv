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


def configure_logger(
    console_level: str = "DEBUG",
    file_level: str = "DEBUG",
    log_console: bool = True,
    log_file: bool = True,
) -> None:
    """Configure loguru logger with detailed formatting."""
    logger.remove()

    # Shared format (color tags get stripped in file output)
    log_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Console on stderr so data printed to stdout (e.g. `arciv list`,
    # `arciv path`) stays clean and pipeable; logs are diagnostics, not data
    if log_console:
        logger.add(
            sys.stderr,
            format=log_format,
            level=console_level,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

    # File - mode="a" appends across runs
    if log_file:
        logger.add(
            LOGS_DIR / "arciv.log",
            format=log_format,
            level=file_level,
            backtrace=True,
            diagnose=True,
            rotation="1 day",
            enqueue=True,
        )
