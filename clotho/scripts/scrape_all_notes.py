"""
Work in progress script for testing and development purposes.
"""

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import Scraper
from config import MARKDOWN_DIR, NOTES_PATH, configure_logger

configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Collect all links from notes
all_links: list[str] = []
for note in note_files:
    extracted_links = note.extract_links()
    if extracted_links:
        logger.debug(
            f"Extracted {len(extracted_links)} links from {note.note_path.name}"
        )
        all_links.extend(extracted_links)

logger.info(f"Collected {len(all_links)} total links to scrape")

# Scrape all links concurrently
scraper: Scraper = Scraper()
scraped_notes: list[MarkdownNote] = scraper.scrape_batch(
    all_links, refetch=False, reclean=False
)

logger.info(f"Scraped {len(scraped_notes)} notes total")
scraped_notes = MarkdownNote.get_note_files(MARKDOWN_DIR)
