import sys
from pathlib import Path

from loguru import logger

# Configure loguru: remove default handler, add stdout with diagnostics
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    backtrace=True,
    diagnose=True,
)

# TODO: will remove hardcoding later
NOTE_PATH = Path("C:/Users/Michael/Documents/WorkVault/Daily notes")
