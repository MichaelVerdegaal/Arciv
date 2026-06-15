"""Fetch stage: download indexed URLs and archive their raw content.

Thin orchestration around :class:`arciv.core.fetch.Fetcher`, which does the
patchright browser work (and direct HTTP for PDFs). Raw content lands in
``saved/<slug>/page.html`` or ``page.pdf``; converting it to markdown is
the parse stage's job (see ``arciv.core.pipeline.parse``).
"""

from collections import Counter

from loguru import logger

from arciv.settings import SAVED_DIR
from arciv.core.db import Page, PageDatabase
from arciv.core.fetch import Fetcher


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


def report(db: PageDatabase, archived: int, urls: list[str]) -> None:
    """Log totals after a run that archived ``archived`` pages.

    Only failures among ``urls`` (the URLs processed this run) are listed, so
    a clean run says nothing about failures and a single succeeding ``get``
    stays quiet. The full failure history across the archive lives in
    ``arciv status``, not here.
    """
    total = db.count()
    pending = len(db.get_unfetched())
    logger.info(
        f"Done: {archived} new pages archived, {total} total in DB, {pending} pending"
    )

    run_failures = Counter(
        (page.domain, page.fail_reason)
        for url in urls
        if (page := db.get(url)) is not None and page.fail_reason is not None
    )
    if not run_failures:
        return
    failed_total = sum(run_failures.values())
    logger.warning(f"{failed_total} failed this run:")
    for (domain, reason), count in run_failures.most_common(10):
        logger.warning(f"  {domain}: {reason} ({count})")
