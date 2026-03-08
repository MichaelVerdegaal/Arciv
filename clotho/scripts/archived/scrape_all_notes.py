"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.db import PageDatabase
from clotho.notes import MarkdownNote
from clotho.parse import Parser
from clotho.scrape import Scraper, process_url, registered_domain, split_url
from config import DB_PATH, HTML_DIR, NOTES_PATH, configure_logger

configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Extract links and build processed URL -> notes mapping
url_sources: dict[str, list[str]] = {}
original_urls: dict[str, str] = {}
for note in note_files:
    for link in note.extract_urls():
        processed, _ = process_url(link)
        if processed is None:
            continue
        url_sources.setdefault(processed, []).append(note.filename)
        if processed not in original_urls:
            original_urls[processed] = link

logger.info(f"Collected {len(url_sources)} unique URLs")

with PageDatabase(DB_PATH) as db:
    # Register new URLs as pending page entries
    page_map = {
        url: (original_urls[url], registered_domain(url) or split_url(url)[0])
        for url in url_sources
    }
    db.ensure_pages(page_map)

    # Rebuild source mapping from current note contents
    db.rebuild_sources(url_sources)

    # Fetch HTML for pending URLs
    scraper = Scraper(db, html_dir=HTML_DIR)
    fetched = scraper.scrape_batch(list(url_sources.keys()))

    # Parse fetched HTML into markdown
    parser = Parser(db, html_dir=HTML_DIR)
    parsed = parser.parse_unparsed()

    logger.info(
        f"Results: {len(fetched)} fetched, {len(parsed)} parsed, "
        f"{db.count()} total in DB "
        f"({db.count('scraped')} scraped, "
        f"{db.count('fetched')} fetched, "
        f"{db.count('failed')} failed, "
        f"{db.count('too_short')} too short)"
    )
