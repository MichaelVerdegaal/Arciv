"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import process_url
from config import NOTES_PATH, configure_logger
from surrealdb import Surreal

configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")
first_note = note_files[0]

# Extract links and build processed URL -> notes mapping
url_sources: dict[str, list[str]] = {}
original_urls: dict[str, str] = {}
for note in note_files:
    for link in note.extract_links():
        processed, _ = process_url(link)
        if processed is None:
            continue
        url_sources.setdefault(processed, []).append(note.filename)
        if processed not in original_urls:
            original_urls[processed] = link

logger.info(f"Collected {len(url_sources)} unique URLs")
