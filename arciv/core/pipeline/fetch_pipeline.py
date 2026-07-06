"""Fetch stage: download indexed URLs and archive their raw content.

Thin orchestration around :class:`arciv.core.fetch.Fetcher`, which does the
Scrapling browser work for HTML (and curl_cffi downloads for PDFs). Raw content
lands in ``saved/<slug>/page.html`` or ``page.pdf``; converting it to markdown
is the parse stage's job (see ``arciv.core.pipeline.parse_pipeline``).
"""

from collections import Counter

from loguru import logger

from arciv.core.db import Page, PageDatabase
from arciv.core.fetch import Fetcher
from arciv.core.urls import load_rules
from arciv.settings import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_RETRIES,
    SAVED_DIR,
    TIMEOUT_MS,
    USER_RULES_PATH,
)


def fetch_urls(db: PageDatabase, urls: list[str], refetch: bool = False) -> list[Page]:
    """Fetch the given URLs (re-downloading if refetch) and return the
    successfully archived Pages."""
    fetcher = Fetcher(
        db,
        saved_dir=SAVED_DIR,
        page_timeout=TIMEOUT_MS,
        max_concurrency=DEFAULT_CONCURRENCY,
        max_retries=DEFAULT_MAX_RETRIES,
        rules=load_rules(USER_RULES_PATH),
    )
    return fetcher.fetch_batch(urls, refetch=refetch)


def report(db: PageDatabase, archived: int, urls: list[str]) -> None:
    """Log totals after a run that archived ``archived`` pages.

    Only failures among ``urls`` (the URLs processed this run) are listed, so
    a clean run says nothing about failures and a single succeeding ``get``
    stays quiet. The full failure history across the archive lives in
    ``arciv status``, not here.
    """
    total = db.count()
    pending = db.count_unfetched()
    logger.info(
        f"Done: {archived} new pages archived, {total} total in DB, {pending} pending"
    )

    run_failures = Counter(db.failures_for(urls))
    if not run_failures:
        return
    failed_total = sum(run_failures.values())
    logger.warning(f"{failed_total} failed this run:")
    for (domain, reason), count in run_failures.most_common(10):
        logger.warning(f"  {domain}: {reason} ({count})")
