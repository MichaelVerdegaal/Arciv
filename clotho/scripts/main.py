"""
Work in progress script for testing and development purposes.
"""

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import Scraper
from config import MARKDOWN_DIR, NOTES_PATH

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Scrape links from all notes
scraper: Scraper = Scraper()
scraped_notes: list[MarkdownNote] = []

for note in note_files:
    logger.info(f"Processing: {note}")

    extracted_links = note.extract_links()
    logger.info(f"Extracted {len(extracted_links)} links from {note_path.name}")

    for link in extracted_links:
        scraped_note: MarkdownNote | None = scraper.scrape(
            link, refetch=False, reclean=False
        )
        if scraped_note is not None:
            scraped_notes.append(scraped_note)

logger.info(f"Scraped {len(scraped_notes)} notes total")
