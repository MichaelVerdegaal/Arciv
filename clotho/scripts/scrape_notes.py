"""Scrape all URLs from Obsidian daily notes into the archive.

End-to-end pipeline: read notes → extract URLs → register in DB →
fetch/validate/convert → write HTML+MD to disk → report results.
"""

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
from config import DB_PATH, NOTES_PATH, SAVED_DIR, configure_logger


def scrape_all(refetch: bool = False, reparse: bool = False) -> None:
    """Run the full scrape pipeline.

    Args:
        refetch: Re-download all pages, even already fetched ones.
        reparse: Re-parse already fetched HTML into markdown (without re-fetching).
    """
    configure_logger()

    # Discover notes and extract URLs
    note_files = MarkdownNote.get_note_files(NOTES_PATH)
    logger.info(f"Found {len(note_files)} notes in {NOTES_PATH}")

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
        # Register new URLs
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

        # Prune orphan rows: failed rows whose URL is no longer canonical
        pruned = db.prune_orphans(set(url_sources.keys()))
        if pruned:
            logger.info(f"Pruned {pruned} orphan rows from previous runs")

        # Rebuild note → URL mapping
        db.rebuild_sources(url_sources)

        # Fetch unfetched pages (or all if refetch)
        scraper = Scraper(db, saved_dir=SAVED_DIR)
        fetched = scraper.scrape_batch(list(url_sources.keys()), refetch=refetch)

        # Re-parse existing HTML if requested
        reparse_count = 0
        if reparse:
            reparse_count = scraper.reparse_existing()

        # Report
        total = db.count()
        unfetched = len(db.get_unfetched())
        failures = db.fail_summary()

        logger.info(
            f"Done: {len(fetched)} new pages archived"
            + (f", {reparse_count} re-parsed" if reparse else "")
            + f", {total} total in DB, {unfetched} pending"
        )

        if failures:
            logger.info("Failure summary:")
            for domain, reason, count in failures[:10]:
                logger.info(f"  {domain}: {reason} ({count})")


if __name__ == "__main__":
    scrape_all()
