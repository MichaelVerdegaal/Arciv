from pathlib import Path

from loguru import logger

from clotho.notes import ObsidianNote
from clotho.scrape import Scraper
from config import NOTES_PATH

TEST_NOTE_PATH = "C:/Users/Michael/Documents/DevVault/Test note.md"


# Get all note files in directory
note_files: list[Path] = ObsidianNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Get test note
test_note: ObsidianNote = ObsidianNote(TEST_NOTE_PATH)
logger.info(f"Loaded: {test_note}")

# Extract links from test note
extracted_links = test_note.extract_links()
logger.info(f"Extracted {len(extracted_links)} links from test note:")

# Scrape links
scraper: Scraper = Scraper()
LINK_MANUAL = "https://freedium-mirror.cfd/https://medium.com/data-science/topic-modeling-with-bert-779f7db187e6"
text = scraper.scrape(LINK_MANUAL, refetch=True)
