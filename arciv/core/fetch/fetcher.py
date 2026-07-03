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
``arciv.core.pipeline.parse``).
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from loguru import logger
from scrapling.fetchers import AsyncStealthySession
from scrapling.fetchers import Fetcher as StaticFetcher

from arciv.core.db import Page, PageDatabase

from .rules import Rule, load_rules
from .url_helpers import (
    is_pdf_url,
    registered_domain,
    slug_for_url,
    split_url,
)
from .url_processing import process_url

# Neutral mechanism defaults so a Fetcher is usable without settings (e.g.
# in tests). The env-tunable values the CLI actually runs with live in
# arciv.settings and are injected by the pipeline layer (pipeline/fetch.py).
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
        max_retries: Maximum retry attempts for transient failures.
        rules: URL-processing rules to re-apply before fetching. Defaults to the
            packaged defaults only; the pipeline injects the user-merged list.
    """

    def __init__(
        self,
        db: PageDatabase,
        saved_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rules: Sequence[Rule] | None = None,
    ):
        self.db = db
        self.saved_dir = saved_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.rules = list(rules) if rules is not None else load_rules()

    # -- internal helpers --

    def _needs_fetch(self, processed_url: str, refetch: bool) -> bool:
        """True for new URLs, pending URLs, and all URLs when refetch is
        set; already-fetched or failed URLs are skipped."""
        if refetch:
            return True
        existing = self.db.get(processed_url)
        if existing is None:
            return True
        # Pending = not fetched AND no fail reason
        return not existing.fetched and existing.fail_reason is None

    def _entry_for(self, processed_url: str, input_url: str) -> tuple[str, str, str]:
        """Build the (original_url, domain, slug) triple for a URL.

        Prefers the original_url already recorded by the index stage so a
        fetch of an indexed page doesn't overwrite it with the processed URL.
        """
        existing = self.db.get(processed_url)
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
            fetched_at=datetime.now(timezone.utc).isoformat(),
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
        seen_processed: set[str] = set()

        # Re-process with the current rules so a rule edited after indexing still
        # applies (and re-canonicalises) before anything is downloaded.
        for url in urls:
            processed_url, skip_reason = process_url(url, self.rules)
            if processed_url is None:
                logger.warning(f"Skipped {url}: {skip_reason}")
                continue

            if processed_url in seen_processed:
                continue
            seen_processed.add(processed_url)

            if not self._needs_fetch(processed_url, refetch):
                continue

            original_url, domain, slug = self._entry_for(processed_url, url)
            entry = (processed_url, original_url, domain, slug)

            if is_pdf_url(processed_url):
                to_fetch_pdf.append(entry)
            else:
                to_fetch_html.append(entry)

        results: list[Page] = []

        # PDFs are downloaded directly over HTTP; no browser needed. Each
        # download blocks in a worker thread (see _fetch_pdf), so run them
        # concurrently, capped at max_concurrency to bound open connections.
        if to_fetch_pdf:
            pdf_sem = asyncio.Semaphore(self.max_concurrency)

            async def _bounded_pdf(entry: tuple[str, str, str, str]) -> Page | None:
                async with pdf_sem:
                    return await self._fetch_pdf(*entry)

            pdf_pages = await asyncio.gather(
                *(_bounded_pdf(entry) for entry in to_fetch_pdf)
            )
            results.extend(page for page in pdf_pages if page is not None)

        if not to_fetch_html:
            return results

        # HTML URLs share one stealthy browser session. ``disable_resources``
        # drops images/stylesheets/fonts (and more) for speed; ``network_idle``
        # lets JS-rendered pages settle so content() isn't an empty shell. The
        # session's page pool caps concurrency at ``max_pages``; retries are
        # left to our own transient-only loop below (``retries=1``).
        async with AsyncStealthySession(
            max_pages=self.max_concurrency,
            headless=True,
            disable_resources=True,
            network_idle=True,
            timeout=self.page_timeout,
            retries=1,
        ) as session:
            fetched = await asyncio.gather(
                *(self._fetch_one(session, *item) for item in to_fetch_html)
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
        its raw HTML. Retries transient errors (timeouts, connection resets) up
        to max_retries times before recording a failure. Returns the Page, or
        None on failure."""
        html: str | None = None
        last_reason = ""

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await session.fetch(processed_url)
                html = response.html_content
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
                f"Retry {attempt}/{self.max_retries} for {processed_url}: {last_reason}"
            )
            await asyncio.sleep(2 * attempt)

        await self._save_html(slug, html)
        page = self._store_success(processed_url, original_url, domain, slug, "html")
        logger.info(f"Fetched {processed_url}")
        return page
