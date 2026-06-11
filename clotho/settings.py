"""Configuration: data directory layout and logging setup.

The data root defaults to ``data/`` relative to the current working
directory, so running from the repository root behaves as before. When
Clotho is installed as a uv tool, set ``CLOTHO_DATA_DIR`` (in the
environment or a ``.env`` file) to give the archive a fixed home.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load environment variables from the nearest .env (cwd upward), must
# happen before any os.getenv below
load_dotenv()

# Data root holding the database, archived pages, and logs; override via
# CLOTHO_DATA_DIR to relocate it (e.g. onto a synced drive)
DATA_DIR = Path(os.getenv("CLOTHO_DATA_DIR", "data")).resolve()
SAVED_DIR = DATA_DIR / "saved"
LOGS_DIR = DATA_DIR / "logs"

# File constants
DB_PATH = DATA_DIR / "clotho.db"


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

    # Console with colors
    if log_console:
        logger.add(
            sys.stdout,
            format=log_format,
            level=console_level,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

    # File - mode="a" appends across runs
    if log_file:
        logger.add(
            LOGS_DIR / "clotho.log",
            format=log_format,
            level=file_level,
            backtrace=True,
            diagnose=True,
            rotation="1 day",
            enqueue=True,
        )
