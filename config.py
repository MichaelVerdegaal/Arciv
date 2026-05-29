import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Directory constants
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
SAVED_DIR = DATA_DIR / "saved"
NOTES_PATH = Path(
    r"C:\Users\Michael.Verdegaal\Documents\WorkVault\Daily notes"
)  # TODO: will remove hardcoding later

# File constants
DB_PATH = DATA_DIR / "clotho.db"

# Load environment variables
load_dotenv(ROOT_DIR / ".env")


def configure_logger(
    console_level: str = "DEBUG",
    file_level: str = "DEBUG",
    log_console: bool = True,
    log_file: bool = True,
) -> None:
    """Configure loguru logger with detailed formatting."""
    logger.remove()

    # Shared formt (color tags get stripped in file output)
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
            ROOT_DIR / "execution.log",
            format=log_format,
            level=file_level,
            backtrace=True,
            diagnose=True,
            rotation="1 day",
            enqueue=True,
        )
