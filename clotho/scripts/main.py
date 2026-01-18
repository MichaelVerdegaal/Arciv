"""
Work in progress script for testing and development purposes.
"""

from pathlib import Path

from loguru import logger

from clotho.extract import Extractor, YakeStrategy
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
notes: list[MarkdownNote] = []
for link in extracted_links:
    note_ob: MarkdownNote = scraper.scrape(link, refetch=False, reclean=False)
    notes.append(note_ob)


# Extract
yake_strategy: YakeStrategy = YakeStrategy()
extractor: Extractor = Extractor(default_strategy=yake_strategy)

for note in notes:
    keywords = extractor.extract(note.text)
    logger.info(f"\nExtracted keywords for note: {note}")
    for kw, score in keywords:
        logger.info(f"\t{kw}, {score:.4f}")
