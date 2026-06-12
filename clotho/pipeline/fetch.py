"""Fetch stage: download indexed URLs and archive their raw content.

Thin orchestration around :class:`clotho.scrape.Fetcher`, which does the
patchright browser work (and direct HTTP for PDFs). Raw content lands in
``saved/<slug>/page.html`` or ``page.pdf``; converting it to markdown is
the parse stage's job (see ``clotho.pipeline.parse``).
"""

from loguru import logger

from clotho.settings import SAVED_DIR
from clotho.db import Page, PageDatabase
from clotho.scrape import Fetcher


def fetch_urls(db: PageDatabase, urls: list[str], refetch: bool = False) -> list[Page]:
    """Fetch the given URLs (re-downloading if refetch) and return the
    successfully archived Pages."""
    fetcher = Fetcher(db, saved_dir=SAVED_DIR)
    return fetcher.fetch_batch(urls, refetch=refetch)


def fetch_pending(db: PageDatabase, refetch: bool = False) -> list[Page]:
    """Fetch every indexed URL that hasn't been downloaded yet; with refetch,
    re-download every known page, even fetched/failed ones."""
    pages = db.get_all() if refetch else db.get_unfetched()
    return fetch_urls(db, [page.url for page in pages], refetch=refetch)


def report(db: PageDatabase, archived: int) -> None:
    """Log totals and a failure summary after a run that archived `archived` pages."""
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
