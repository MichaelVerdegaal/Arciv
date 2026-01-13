import sys
from pathlib import Path

from loguru import logger

# Directory constants
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
SCRAPED_DOCS_DIR = DATA_DIR / "scraped"
CONVERTED_DOCS_DIR = DATA_DIR / "converted"
CLEANED_DOCS_DIR = DATA_DIR / "cleaned"
NOTE_PATH = Path(
    "C:/Users/Michael.Verdegaal/Documents/WorkVault/Daily notes"
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
