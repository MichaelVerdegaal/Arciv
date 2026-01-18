from pathlib import Path

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import Scraper
from config import NOTES_PATH

TEST_NOTE_PATH = "C:/Users/Michael/Documents/DevVault/Test note.md"


# Get all note files in directory
note_files: list[Path] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Get test note
test_note: MarkdownNote = MarkdownNote(TEST_NOTE_PATH)
logger.info(f"Loaded: {test_note}")

# Extract links from test note
extracted_links = test_note.extract_links()
logger.info(f"Extracted {len(extracted_links)} links from test note:")

# Scrape links
scraper: Scraper = Scraper()
LINK_MANUAL = "https://medium.com/data-science/topic-modeling-with-bert-779f7db187e6"
# text = scraper.scrape(LINK_MANUAL, refetch=False, reclean=True)
for link in extracted_links:
    text = scraper.scrape(link, refetch=False, reclean=True)
