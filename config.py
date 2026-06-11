import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Directory constants
ROOT_DIR = Path(__file__).parent

# Load environment variables (must happen before any os.getenv below)
load_dotenv(ROOT_DIR / ".env")

# Data root holding the database, archived pages, and logs; override via
# CLOTHO_DATA_DIR to relocate it (e.g. onto a Docker volume)
DATA_DIR = Path(os.getenv("CLOTHO_DATA_DIR", str(ROOT_DIR / "data")))
SAVED_DIR = DATA_DIR / "saved"
LOGS_DIR = DATA_DIR / "logs"

# File constants
DB_PATH = DATA_DIR / "clotho.db"

# Obsidian daily-notes directory; override via CLOTHO_NOTES_PATH in .env
NOTES_PATH = Path(
    os.getenv(
        "CLOTHO_NOTES_PATH",
        r"C:\Users\Michael.Verdegaal\Documents\WorkVault\Daily notes",
    )
)


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
