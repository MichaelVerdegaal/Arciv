"""Fetch stage: download raw page content (HTML or PDF) to disk.

One fetch layer, two engines from Scrapling, one ``Response`` type:

- HTML goes through :class:`~scrapling.fetchers.AsyncStealthySession`
  (patchright under a stealth wrapper: CDP-leak patching, canvas noise, an
  optional Turnstile solver), sharing one browser context across the batch.
- PDFs and direct downloads go through :class:`~scrapling.fetchers.Fetcher`
  (curl_cffi, TLS-impersonated), no browser needed.

Each page goes: fetch HTML → write ``page.html`` to the slug folder → record
in DB. PDF URLs are downloaded directly and stored as ``page.pdf``. Validation
and markdown conversion happen later, in the parse stage (see
``arciv.core.pipeline.parse_pipeline``).
"""

import asyncio
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger
from scrapling.fetchers import AsyncStealthySession
from scrapling.fetchers import Fetcher as StaticFetcher

from arciv.core.clock import utc_now_iso
from arciv.core.db import Page, PageDatabase

from arciv.core.urls import (
    Rule,
    is_pdf_url,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)

# Neutral mechanism defaults so a Fetcher is usable without settings (e.g.
# in tests). The env-tunable values the CLI actually runs with live in
# arciv.settings and are injected by the pipeline layer
# (pipeline/fetch_pipeline.py).
TIMEOUT_MS = 30_000
DEFAULT_CONCURRENCY = 8
DEFAULT_MAX_RETRIES = 2

# Transient error patterns worth retrying
_TRANSIENT_ERRORS = (
    "timeout",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_CONNECTION_TIMED_OUT",
)


class Fetcher:
    """Downloads web pages and archives the raw content on disk.

    HTML pages are written to ``saved/<slug>/page.html``, PDFs to
    ``saved/<slug>/page.pdf``. Successful downloads are marked
    ``fetched=1`` in the database; converting them to markdown is the
    parse stage's job.

    Args:
        db: Database to store page records.
        saved_dir: Root directory for archived page folders.
        page_timeout: Browser page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
        max_retries: Retries after the first attempt for transient failures
            (timeouts, connection resets); total attempts = max_retries + 1.
        rules: URL-processing rules to re-apply before fetching. Defaults to
            NO rules (the in-code plumbing guards still apply): the pipeline
            layer injects ``load_rules(USER_RULES_PATH)``, and defaulting to a
            different rule set here would silently ignore the user's
            rules.toml for anyone constructing a Fetcher directly.
    """

    def __init__(
        self,
        db: PageDatabase,
        saved_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rules: Sequence[Rule] = (),
    ):
        self.db = db
        self.saved_dir = saved_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.rules = list(rules)

    # -- internal helpers --

    @staticmethod
    def _needs_fetch(existing: Page | None, refetch: bool) -> bool:
        """True for new URLs (no existing row), pending URLs, and all URLs
        when refetch is set; already-fetched or failed URLs are skipped."""
        if refetch:
            return True
        if existing is None:
            return True
        # Pending = not fetched AND no fail reason
        return not existing.fetched and existing.fail_reason is None

    @staticmethod
    def _entry_for(
        existing: Page | None, processed_url: str, input_url: str
    ) -> tuple[str, str, str]:
        """Build the (original_url, domain, slug) triple for a URL.

        Prefers the original_url already recorded on the existing row by the
        index stage so a fetch of an indexed page doesn't overwrite it with
        the processed URL.
        """
        original_url = existing.original_url if existing else input_url
        domain = registered_domain(processed_url) or split_url(processed_url)[0]
        slug = slug_for_url(processed_url, domain)
        return original_url, domain, slug

    def _store_success(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
        content_type: str,
    ) -> Page:
        """Record a successful fetch in the database.

        Title, author, word count, and parsed_at are reset; the parse
        stage fills them in once the fresh content has been converted.
        """
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            slug=slug,
            content_type=content_type,
            fetched_at=utc_now_iso(),
        )
        self.db.upsert(page)
        return page

    def _store_failure(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
        fail_reason: str,
    ) -> None:
        """Record a fetch failure in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            slug=slug,
            fail_reason=fail_reason,
        )
        self.db.upsert(page)

    @staticmethod
    def _format_fetch_error(error: Exception) -> str:
        """Format a fetch error into a concise reason string."""
        error_msg = str(error).split("\n")[0]

        if "net::ERR_NAME_NOT_RESOLVED" in error_msg:
            return "DNS resolution failed"
        elif "net::ERR_CONNECTION_REFUSED" in error_msg:
            return "connection refused"
        elif "Timeout" in error_msg:
            return "timeout"
        else:
            return error_msg

    @staticmethod
    def _is_transient(reason: str) -> bool:
        """Check if a failure reason indicates a transient/retryable error."""
        return any(marker in reason for marker in _TRANSIENT_ERRORS)

    async def _save_html(self, slug: str, html: str) -> None:
        """Write the raw HTML file to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(slug_dir / "page.html", "w", encoding="utf-8") as f:
            await f.write(html)

    def _save_pdf(self, slug: str, pdf_bytes: bytes) -> None:
        """Write the raw PDF file to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "page.pdf").write_bytes(pdf_bytes)

    def _download_pdf(self, url: str) -> bytes | None:
        """Download a file via curl_cffi (TLS-impersonated) from a direct URL.

        Returns the raw bytes, or None if the request failed or the server
        answered with an error status. curl_cffi doesn't raise on 4xx/5xx, so
        the status is checked explicitly."""
        try:
            response = StaticFetcher.get(
                url,
                impersonate="chrome",
                timeout=self.page_timeout / 1000,
                stealthy_headers=True,
            )
        except Exception as e:
            logger.warning(f"PDF download failed {url}: {e}")
            return None
        if response.status >= 400:
            logger.warning(f"PDF download failed {url}: HTTP {response.status}")
            return None
        return response.body

    async def _fetch_pdf(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
        fail_reason: str = "PDF download failed",
    ) -> Page | None:
        """Download a PDF, save it to disk, and record the outcome.

        The curl_cffi download is synchronous and can block for the full
        timeout, so it runs in a worker thread to keep it off the event loop —
        otherwise one slow PDF would stall every concurrent browser fetch. The
        disk and DB writes stay on the loop thread, since the sqlite connection
        is single-threaded.
        """
        pdf_bytes = await asyncio.to_thread(self._download_pdf, processed_url)
        if pdf_bytes is None:
            self._store_failure(processed_url, original_url, domain, slug, fail_reason)
            return None
        self._save_pdf(slug, pdf_bytes)
        page = self._store_success(processed_url, original_url, domain, slug, "pdf")
        logger.info(f"Fetched {processed_url} (PDF, {len(pdf_bytes)} bytes)")
        return page

    # -- fetch entry points --

    def fetch_batch(self, urls: list[str], refetch: bool = False) -> list[Page]:
        """Fetch multiple URLs concurrently (re-downloading if refetch) and
        archive their raw content. Returns the successfully fetched Pages."""
        return asyncio.run(self._fetch_batch_async(urls, refetch))

    def _mark_diverted(self, diverted: dict[str, str]) -> None:
        """Record a fail_reason on stored rows the current rules no longer
        target.

        A stored URL that today's rules skip — or rewrite to a different key —
        would otherwise stay pending forever: nothing will ever fetch that
        exact key again, ``status`` counts it as pending on every run, and no
        ``prune`` mode selects rows without a fail_reason. Writing the
        divergence as the fail_reason makes it visible and prunable. Only
        pending rows are touched; already-fetched content is never demoted.
        """
        for url, page in self.db.get_many(list(diverted)).items():
            if not page.fetched and page.fail_reason is None:
                page.fail_reason = diverted[url]
                self.db.upsert(page)
                logger.warning(f"Marked {url}: {diverted[url]}")

    async def _isolated(
        self,
        entry: tuple[str, str, str, str],
        task: Coroutine[Any, Any, Page | None],
    ) -> Page | None:
        """Await one per-URL fetch task without letting an unexpected
        exception escape into ``asyncio.gather``, where it would cancel every
        other in-flight fetch in the batch. The expected failure modes are
        handled inside the task; whatever still escapes (disk full, a DB
        integrity error) is recorded as that one page's failure.
        """
        try:
            return await task
        except Exception as e:
            processed_url, original_url, domain, slug = entry
            logger.error(f"Unexpected error fetching {processed_url}: {e}")
            try:
                self._store_failure(
                    processed_url, original_url, domain, slug, f"unexpected: {e}"
                )
            except Exception as store_error:
                logger.error(
                    f"Could not record the failure for {processed_url}: {store_error}"
                )
            return None

    async def _fetch_batch_async(
        self,
        urls: list[str],
        refetch: bool,
    ) -> list[Page]:
        """Process URLs, skip cached, fetch the rest concurrently.

        PDF URLs are downloaded directly (no browser needed). HTML URLs go
        through the stealth browser session.
        """
        to_fetch_html: list[tuple[str, str, str, str]] = []
        to_fetch_pdf: list[tuple[str, str, str, str]] = []
        candidates: dict[str, str] = {}  # processed URL -> first input URL
        diverted: dict[str, str] = {}  # stored URL the rules now skip/rewrite

        # Re-process with the current rules so a rule edited after indexing still
        # applies (and re-canonicalises) before anything is downloaded.
        for url in urls:
            processed_url, skip_reason = process_url(url, self.rules)
            if processed_url is None:
                logger.warning(f"Skipped {url}: {skip_reason}")
                diverted[url] = f"skipped by rule change since indexing: {skip_reason}"
                continue
            if processed_url != url:
                diverted[url] = (
                    f"rewritten by rule change since indexing -> {processed_url}"
                )
            candidates.setdefault(processed_url, url)

        if diverted:
            self._mark_diverted(diverted)

        # One batched lookup: the same row answers both "needs fetch?" and
        # "which original_url?".
        existing_pages = self.db.get_many(list(candidates))
        for processed_url, input_url in candidates.items():
            existing = existing_pages.get(processed_url)
            if not self._needs_fetch(existing, refetch):
                continue

            original_url, domain, slug = self._entry_for(
                existing, processed_url, input_url
            )
            entry = (processed_url, original_url, domain, slug)

            if is_pdf_url(processed_url):
                to_fetch_pdf.append(entry)
            else:
                to_fetch_html.append(entry)

        results: list[Page] = []

        # Every fetch outcome is recorded with an upsert; those all run on the
        # event loop thread (the sqlite connection is single-threaded), so
        # bulk() batches their commits instead of fsyncing once per page.
        with self.db.bulk():
            # PDFs are downloaded directly over HTTP; no browser needed. Each
            # download blocks in a worker thread (see _fetch_pdf), so run them
            # concurrently, capped at max_concurrency to bound open connections.
            # They run before (not alongside) the browser batch on purpose:
            # interleaving the two pools isn't worth the complexity for the
            # small PDF share of a typical batch.
            if to_fetch_pdf:
                pdf_sem = asyncio.Semaphore(self.max_concurrency)

                async def _bounded_pdf(
                    entry: tuple[str, str, str, str],
                ) -> Page | None:
                    async with pdf_sem:
                        return await self._fetch_pdf(*entry)

                pdf_pages = await asyncio.gather(
                    *(
                        self._isolated(entry, _bounded_pdf(entry))
                        for entry in to_fetch_pdf
                    )
                )
                results.extend(page for page in pdf_pages if page is not None)

            if to_fetch_html:
                # HTML URLs share one stealthy browser session.
                # ``disable_resources`` drops images/stylesheets/fonts (and
                # more) for speed; ``network_idle`` lets JS-rendered pages
                # settle so content() isn't an empty shell. The session's page
                # pool caps concurrency at ``max_pages``; retries are left to
                # our own transient-only loop (``retries=1``).
                async with AsyncStealthySession(
                    max_pages=self.max_concurrency,
                    headless=True,
                    disable_resources=True,
                    network_idle=True,
                    timeout=self.page_timeout,
                    retries=1,
                ) as session:
                    fetched = await asyncio.gather(
                        *(
                            self._isolated(entry, self._fetch_one(session, *entry))
                            for entry in to_fetch_html
                        )
                    )
                results.extend(page for page in fetched if page is not None)

        return results

    async def _fetch_one(
        self,
        session: AsyncStealthySession,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Fetch a single URL (async) through the stealth session and archive
        its raw HTML. Transient errors (timeouts, connection resets) are
        retried up to max_retries times after the first attempt before
        recording a failure. Returns the Page, or None on failure."""
        html: str | None = None
        last_reason = ""

        # attempt counts retries: 0 is the first try, max_retries the last.
        for attempt in range(self.max_retries + 1):
            try:
                response = await session.fetch(processed_url)
                html = response.html_content
                if html is None:
                    # A clean response with no content is still a failure, and
                    # must not be stored with an empty reason.
                    last_reason = "browser returned no content"
            except Exception as e:
                last_reason = self._format_fetch_error(e)

                # Browser triggered a file download, so try the PDF path
                if "Download is starting" in last_reason:
                    return await self._fetch_pdf(
                        processed_url,
                        original_url,
                        domain,
                        slug,
                        fail_reason="download triggered but PDF fetch failed",
                    )

            if html is not None:
                break

            if not self._is_transient(last_reason) or attempt == self.max_retries:
                self._store_failure(
                    processed_url, original_url, domain, slug, last_reason
                )
                logger.warning(f"Fetch error {processed_url}: {last_reason}")
                return None

            logger.debug(
                f"Retry {attempt + 1}/{self.max_retries} for {processed_url}: "
                f"{last_reason}"
            )
            # The sleep holds one of the session's max_pages slots, so a burst
            # of transient failures temporarily lowers effective concurrency.
            await asyncio.sleep(2 * (attempt + 1))

        await self._save_html(slug, html)
        page = self._store_success(processed_url, original_url, domain, slug, "html")
        logger.info(f"Fetched {processed_url}")
        return page
