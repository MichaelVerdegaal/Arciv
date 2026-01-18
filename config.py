import sys
from pathlib import Path

from loguru import logger

# Directory constants
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
HTML_DIR = DATA_DIR / "html"
MARKDOWN_DIR = DATA_DIR / "markdown"
NOTES_PATH = Path(
    "C:/Users/Michael/Documents/DevVault/Daily notes"
)  # TODO: will remove hardcoding later

# File constants
STOPWORDS_FILE = DATA_DIR / "stopwords_en.txt"


# Configure loguru: remove default handler, add stdout with diagnostics
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    backtrace=True,
    diagnose=True,
)
