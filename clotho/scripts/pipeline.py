"""Archive pipeline: indexing → fetching → parsing.

Indexing reads Obsidian notes, extracts and normalizes URLs, and registers
them in the database. Fetching downloads pending pages (HTML via patchright,
PDFs via direct HTTP). Parsing validates fetched content and converts it to
markdown. Fetching and parsing run as one pass per page inside Scraper;
parsing can also run standalone over already-archived HTML.
"""

from pathlib import Path

from loguru import logger

from clotho.db import PageDatabase
from clotho.notes import MarkdownNote
from clotho.scrape import (
    Scraper,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)
from config import DB_PATH, SAVED_DIR, configure_logger


def index_notes(db: PageDatabase, notes_dir: Path) -> list[str]:
    """Indexing stage: extract URLs from notes and register them in the DB.

    Reads every markdown note in the directory, extracts and normalizes its
    links, creates pending page rows for new URLs, prunes failed rows whose
    URLs no longer appear in any note, and rebuilds the note→URL mapping.

    Args:
        db: Page database.
        notes_dir: Directory containing Obsidian markdown notes.

    Returns:
        All processed URLs currently referenced by the notes.
    """
    note_files = MarkdownNote.get_note_files(notes_dir)
    logger.info(f"Found {len(note_files)} notes in {notes_dir}")

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

    url_entries = [
        (
            url,
            original_urls[url],
            registered_domain(url) or split_url(url)[0],
            slug_for_url(url),
        )
        for url in url_sources
    ]
    db.ensure_pages(url_entries)

    pruned = db.prune_orphans(set(url_sources.keys()))
    if pruned:
        logger.info(f"Pruned {pruned} orphan rows from previous runs")

    db.rebuild_sources(url_sources)
    return list(url_sources)


def _report(db: PageDatabase, archived: int) -> None:
    """Log totals and a failure summary after a fetch run."""
    total = db.count()
    pending = len(db.get_unfetched())
    logger.info(
        f"Done: {archived} new pages archived, {total} total in DB, {pending} pending"
    )

    failures = db.fail_summary()
    if failures:
        logger.info("Failure summary:")
        for domain, reason, count in failures[:10]:
            logger.info(f"  {domain}: {reason} ({count})")


def run_pipeline(notes_dir: Path, refetch: bool = False) -> None:
    """Run all stages: index the notes, then fetch and parse new URLs.

    Args:
        notes_dir: Directory containing Obsidian markdown notes.
        refetch: Re-download all pages, even already fetched ones.
    """
    configure_logger()
    with PageDatabase(DB_PATH) as db:
        urls = index_notes(db, notes_dir)
        scraper = Scraper(db, saved_dir=SAVED_DIR)
        fetched = scraper.scrape_batch(urls, refetch=refetch)
        _report(db, len(fetched))


def fetch_urls(urls: list[str], refetch: bool = False) -> None:
    """Fetch and parse specific URLs, skipping the notes indexing stage.

    Args:
        urls: URLs to fetch.
        refetch: Re-download even if already fetched.
    """
    configure_logger()
    with PageDatabase(DB_PATH) as db:
        scraper = Scraper(db, saved_dir=SAVED_DIR)
        fetched = scraper.scrape_batch(urls, refetch=refetch)
        _report(db, len(fetched))


def reparse_archive() -> None:
    """Parsing stage alone: re-parse all archived HTML into markdown.

    Useful after changing trafilatura settings or cleanup rules — no
    network traffic, everything is read from disk.
    """
    configure_logger()
    with PageDatabase(DB_PATH) as db:
        scraper = Scraper(db, saved_dir=SAVED_DIR)
        scraper.reparse_existing()
