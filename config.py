import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Directory constants
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
HTML_DIR = DATA_DIR / "html"
NOTES_PATH = Path(
    "C:/Users/Michael/Documents/DevVault/Daily notes"
)  # TODO: will remove hardcoding later

# File constants
DB_PATH = DATA_DIR / "clotho.db"

# Load environment variables
load_dotenv(ROOT_DIR / ".env")


def configure_logger():
    """Configure loguru logger with detailed formatting."""
    logger.remove()

    # Shared formt (color tags get stripped in file output)
    log_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Console with colors
    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    # File - mode="a" appends across runs
    logger.add(
        ROOT_DIR / "execution.log",
        format=log_format,
        level="DEBUG",
        backtrace=True,
        diagnose=True,
        rotation="1 day",
        enqueue=True,
    )
