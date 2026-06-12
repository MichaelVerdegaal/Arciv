"""Fetch stage: download raw page content (HTML or PDF) to disk.

Uses patchright (undetected Playwright fork) with Chrome in persistent-context
mode for stealth. Each page goes through: fetch HTML → write ``page.html`` to
the slug folder → record in DB. PDF URLs are downloaded via direct HTTP and
stored as ``page.pdf``. Validation and markdown conversion happen later, in
the parse stage (see ``clotho.pipeline.parse``).
"""

import asyncio
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from loguru import logger
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright
from patchright.sync_api import sync_playwright

from clotho.db import Page, PageDatabase

from .url_processor import (
    is_pdf_url,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)
from .user_agents import random_user_agent

TIMEOUT_MS = 30_000
# Extra time to let JS-rendered pages (SPAs) finish loading after
# domcontentloaded. Without it, content() can return an empty shell.
NETWORKIDLE_MS = 3_000
DEFAULT_CONCURRENCY = 8
DEFAULT_MAX_RETRIES = 2
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font"}

# Transient error patterns worth retrying
_TRANSIENT_ERRORS = (
    "timeout",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_CONNECTION_TIMED_OUT",
)

# Sentinel value returned by _fetch_sync when the browser triggers a download
_DOWNLOAD_SENTINEL = "__DOWNLOAD__"


class Fetcher:
    """Downloads web pages and archives the raw content on disk.

    HTML pages are written to ``saved/<slug>/page.html``, PDFs to
    ``saved/<slug>/page.pdf``. Successful downloads are marked
    ``fetched=1`` in the database; converting them to markdown is the
    parse stage's job.

    Args:
        db: Database to store page records.
        saved_dir: Root directory for archived page folders.
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
        max_retries: Maximum retry attempts for transient failures.
        headless: Run the browser without a visible window. Disable only when a
            site needs the extra stealth of a headed browser.
    """

    def __init__(
        self,
        db: PageDatabase,
        saved_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        headless: bool = True,
    ):
        self.db = db
        self.saved_dir = saved_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.headless = headless
        # User-Agent for raw HTTP (PDF) downloads, refreshed per session.
        # Drawing from the pool here triggers the once-per-process UA pool
        # refresh. The browser uses real Chrome's own UA, not this one.
        self._session_user_agent: str = random_user_agent()

    def _start_session(self) -> None:
        """Pick a fresh User-Agent for the upcoming fetch session."""
        self._session_user_agent = random_user_agent()
        logger.debug(f"Session User-Agent: {self._session_user_agent}")

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
        slug = slug_for_url(processed_url)
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

    def _save_html_sync(self, slug: str, html: str) -> None:
        """Write the raw HTML file to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "page.html").write_text(html, encoding="utf-8")

    async def _save_html_async(self, slug: str, html: str) -> None:
        """Write the raw HTML file to the slug directory (async)."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(slug_dir / "page.html", "w", encoding="utf-8") as f:
            await f.write(html)

    def _save_pdf_sync(self, slug: str, pdf_bytes: bytes) -> None:
        """Write the raw PDF file to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "page.pdf").write_bytes(pdf_bytes)

    def _download_pdf(self, url: str) -> bytes | None:
        """Download a PDF via HTTP from a direct .pdf URL. Returns the raw
        bytes, or None if the download failed."""
        request = urllib.request.Request(
            url, headers={"User-Agent": self._session_user_agent}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as e:
            logger.warning(f"PDF download failed {url}: {e}")
            return None

    def _fetch_pdf(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
        fail_reason: str = "PDF download failed",
    ) -> Page | None:
        """Download a PDF, save it to disk, and record the outcome."""
        pdf_bytes = self._download_pdf(processed_url)
        if pdf_bytes is None:
            self._store_failure(processed_url, original_url, domain, slug, fail_reason)
            return None
        self._save_pdf_sync(slug, pdf_bytes)
        page = self._store_success(processed_url, original_url, domain, slug, "pdf")
        logger.info(f"Fetched {processed_url} (PDF, {len(pdf_bytes)} bytes)")
        return page

    # -- synchronous: single page, debuggable --

    def fetch(self, url: str, refetch: bool = False) -> Page | None:
        """Fetch a single URL synchronously (re-downloading if refetch) and
        archive its raw content. Returns the Page, or None if skipped or
        failed."""
        self._start_session()
        processed_url, skip_reason = process_url(url)
        if processed_url is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            return None

        original_url, domain, slug = self._entry_for(processed_url, url)

        if not self._needs_fetch(processed_url, refetch):
            return self.db.get(processed_url)

        # PDF URLs: download directly, no browser needed
        if is_pdf_url(processed_url):
            return self._fetch_pdf(processed_url, original_url, domain, slug)

        html = self._fetch_sync(processed_url)
        if html is None:
            self._store_failure(
                processed_url, original_url, domain, slug, "fetch failed"
            )
            return None

        # Browser got a download trigger instead of HTML, so try it as a PDF
        if html == _DOWNLOAD_SENTINEL:
            return self._fetch_pdf(
                processed_url,
                original_url,
                domain,
                slug,
                fail_reason="download triggered but PDF fetch failed",
            )

        self._save_html_sync(slug, html)
        page = self._store_success(processed_url, original_url, domain, slug, "html")
        logger.info(f"Fetched {processed_url}")
        return page

    def _fetch_sync(self, url: str) -> str | None:
        """Fetch HTML synchronously with patchright; returns the raw HTML,
        or None if the fetch failed.

        Uses Chrome with a persistent context and no fingerprint injection
        for maximum stealth.
        """
        with tempfile.TemporaryDirectory() as user_data_dir:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=self.headless,
                    no_viewport=True,
                    ignore_https_errors=True,
                )
                pw_page = context.new_page()
                pw_page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                        else route.continue_()
                    ),
                )
                try:
                    pw_page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.page_timeout,
                    )
                    # SPAs render content after domcontentloaded; let the
                    # network settle so client-side content is present.
                    try:
                        pw_page.wait_for_load_state(
                            "networkidle", timeout=NETWORKIDLE_MS
                        )
                    except PlaywrightTimeoutError:
                        pass
                    return pw_page.content()
                except Exception as e:
                    error_msg = self._format_fetch_error(e)
                    if "Download is starting" in error_msg:
                        return _DOWNLOAD_SENTINEL
                    logger.warning(f"Fetch error {url}: {error_msg}")
                    return None
                finally:
                    pw_page.close()
                    context.close()

    # -- async batch: multiple pages with concurrency --

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
        through patchright.
        """
        self._start_session()
        to_fetch_html: list[tuple[str, str, str, str]] = []
        to_fetch_pdf: list[tuple[str, str, str, str]] = []
        seen_processed: set[str] = set()

        for url in urls:
            processed_url, skip_reason = process_url(url)
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

        # Process PDFs (no browser needed)
        for processed_url, original_url, domain, slug in to_fetch_pdf:
            page = self._fetch_pdf(processed_url, original_url, domain, slug)
            if page is not None:
                results.append(page)

        # Process HTML URLs with browser
        if to_fetch_html:
            results.extend(await self._fetch_all(to_fetch_html))

        return results

    async def _fetch_all(
        self,
        to_fetch: list[tuple[str, str, str, str]],
    ) -> list[Page]:
        """Fetch URLs concurrently with a shared persistent browser context.

        Uses Chrome with no fingerprint injection (patchright best practice).
        Retries transient failures (timeouts, resets) up to max_retries.
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async with async_playwright() as p:
            with tempfile.TemporaryDirectory() as user_data_dir:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=self.headless,
                    no_viewport=True,
                    ignore_https_errors=True,
                )
                tasks = [
                    self._fetch_one_async(semaphore, context, *item)
                    for item in to_fetch
                ]
                fetched = await asyncio.gather(*tasks)
                await context.close()

        return [page for page in fetched if page is not None]

    async def _fetch_one_async(
        self,
        semaphore: asyncio.Semaphore,
        context: object,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Fetch a single URL (async) inside the patchright context and
        archive its raw HTML. Retries transient errors (timeouts, connection
        resets) up to max_retries times before recording a failure. Returns
        the Page, or None on failure."""
        html: str | None = None
        last_reason = ""

        for attempt in range(1, self.max_retries + 1):
            async with semaphore:
                pw_page = await context.new_page()
                await pw_page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                        else route.continue_()
                    ),
                )
                try:
                    await pw_page.goto(
                        processed_url,
                        wait_until="domcontentloaded",
                        timeout=self.page_timeout,
                    )
                    # SPAs render content after domcontentloaded; let the
                    # network settle so client-side content is present.
                    try:
                        await pw_page.wait_for_load_state(
                            "networkidle", timeout=NETWORKIDLE_MS
                        )
                    except PlaywrightTimeoutError:
                        pass
                    html = await pw_page.content()
                except Exception as e:
                    last_reason = self._format_fetch_error(e)

                    # Browser triggered a file download, so try the PDF path
                    if "Download is starting" in last_reason:
                        await pw_page.close()
                        return self._fetch_pdf(
                            processed_url,
                            original_url,
                            domain,
                            slug,
                            fail_reason="download triggered but PDF fetch failed",
                        )
                finally:
                    if not pw_page.is_closed():
                        await pw_page.close()

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

        await self._save_html_async(slug, html)
        page = self._store_success(processed_url, original_url, domain, slug, "html")
        logger.info(f"Fetched {processed_url}")
        return page
