"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.db import PageDatabase
from clotho.notes import MarkdownNote
from clotho.scrape import Scraper
from config import DB_PATH, HTML_DIR, NOTES_PATH, configure_logger

configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Extract links with source note tracking
url_sources: dict[str, list[str]] = {}
for note in note_files:
    for link in note.extract_links():
        url_sources.setdefault(link, []).append(note.filename)

logger.info(f"Collected {len(url_sources)} unique URLs to scrape")

# Scrape all links concurrently
with PageDatabase(DB_PATH) as db:
    scraper = Scraper(db, html_dir=HTML_DIR)
    pages = scraper.scrape_batch(
        list(url_sources.keys()),
        source_notes=url_sources,
        refetch=False,
        reclean=False,
    )

    logger.info(
        f"Results: {len(pages)} scraped, "
        f"{db.count()} total in DB "
        f"({db.count('scraped')} scraped, "
        f"{db.count('failed')} failed, "
        f"{db.count('too_short')} too short)"
    )
