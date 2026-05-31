"""Web scraper that fetches, validates, converts, and archives pages.

Uses patchright (undetected Playwright fork) with Chrome in persistent-context
mode for stealth. Each page goes through: fetch HTML → validate (block-page /
size check) → convert to markdown via trafilatura → write HTML + MD to disk →
record in DB. Raw text URLs (.md, .txt) skip HTML conversion entirely.
PDF URLs are downloaded directly and parsed via liteparse.
"""

import asyncio
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from liteparse import LiteParse
from loguru import logger
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright
from patchright.sync_api import sync_playwright

from clotho.db import Page, PageDatabase
from clotho.parse import parse_html

from .url_processor import (
    is_pdf_url,
    is_raw_text_url,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)
from .validate import check_html

TIMEOUT_MS = 30_000
# Extra time to let JS-rendered pages (SPAs) finish loading after
# domcontentloaded. Without it, content() can return an empty shell.
NETWORKIDLE_MS = 3_000
DEFAULT_CONCURRENCY = 8
DEFAULT_MIN_WORDS = 150
DEFAULT_MAX_RETRIES = 2
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font"}

# Transient error patterns worth retrying
_TRANSIENT_ERRORS = (
    "timeout",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_CONNECTION_TIMED_OUT",
)

_pdf_parser = LiteParse(ocr_enabled=False, quiet=True)

# Sentinel value returned by _fetch_sync when the browser triggers a download
_DOWNLOAD_SENTINEL = "__DOWNLOAD__"


class Scraper:
    """Fetches web pages, validates content, and archives HTML + markdown.

    Combines fetching, validation, and conversion into a single pass.
    Content is written to ``saved/<slug>/page.html`` and
    ``saved/<slug>/page.md``.

    Args:
        db: Database to store page records.
        saved_dir: Root directory for archived page folders.
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
        min_words: Minimum word count in markdown for a page to be accepted.
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
        min_words: int = DEFAULT_MIN_WORDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        headless: bool = True,
    ):
        self.db = db
        self.saved_dir = saved_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.min_words = min_words
        self.max_retries = max_retries
        self.headless = headless

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _needs_fetch(self, processed_url: str, refetch: bool) -> bool:
        """Check if a URL needs to be fetched.

        Returns True for new URLs, pending URLs, and all URLs when refetch
        is True. Already-fetched or failed URLs are skipped.

        Args:
            processed_url: The URL to check.
            refetch: Force re-download regardless of status.

        Returns:
            True if the page should be fetched.
        """
        if refetch:
            return True
        existing = self.db.get(processed_url)
        if existing is None:
            return True
        # Pending = not fetched AND no fail reason
        return not existing.fetched and existing.fail_reason is None

    def _store_success(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
        title: str | None,
        author: str | None,
        word_count: int,
    ) -> Page:
        """Record a successful fetch+parse in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            slug=slug,
            fetched=True,
            title=title,
            author=author,
            word_count=word_count,
            scraped_at=datetime.now(timezone.utc).isoformat(),
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
        """Record a fetch/validation failure in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            slug=slug,
            fetched=False,
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

    def _save_files_sync(self, slug: str, html: str, markdown: str) -> None:
        """Write HTML and markdown files to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "page.html").write_text(html, encoding="utf-8")
        (slug_dir / "page.md").write_text(markdown, encoding="utf-8")

    @staticmethod
    async def _save_files_async(slug_dir: Path, html: str, markdown: str) -> None:
        """Write HTML and markdown files to the slug directory (async)."""
        slug_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(slug_dir / "page.html", "w", encoding="utf-8") as f:
            await f.write(html)
        async with aiofiles.open(slug_dir / "page.md", "w", encoding="utf-8") as f:
            await f.write(markdown)

    def _save_pdf_sync(self, slug: str, pdf_bytes: bytes, markdown: str) -> None:
        """Write PDF and markdown files to the slug directory."""
        slug_dir = self.saved_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        (slug_dir / "page.pdf").write_bytes(pdf_bytes)
        (slug_dir / "page.md").write_text(markdown, encoding="utf-8")

    @staticmethod
    async def _save_pdf_async(slug_dir: Path, pdf_bytes: bytes, markdown: str) -> None:
        """Write PDF and markdown files to the slug directory (async)."""
        slug_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(slug_dir / "page.pdf", "wb") as f:
            await f.write(pdf_bytes)
        async with aiofiles.open(slug_dir / "page.md", "w", encoding="utf-8") as f:
            await f.write(markdown)

    @staticmethod
    def _download_pdf(url: str) -> bytes | None:
        """Download a PDF file via HTTP.

        Args:
            url: Direct URL to a .pdf file.

        Returns:
            Raw PDF bytes, or None if the download failed.
        """
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as e:
            logger.warning(f"PDF download failed {url}: {e}")
            return None

    def _process_pdf(
        self,
        pdf_bytes: bytes,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Parse PDF bytes with liteparse, validate, and archive.

        Returns a Page on success, None on failure (failure is recorded in DB).
        """
        try:
            result = _pdf_parser.parse(pdf_bytes)
        except Exception as e:
            reason = f"PDF parse error: {e}"
            self._store_failure(processed_url, original_url, domain, slug, reason)
            logger.warning(f"Rejected {processed_url}: {reason}")
            return None

        text = result.text.strip()
        word_count = len(text.split())

        if word_count < self.min_words:
            reason = f"too short ({word_count} words)"
            self._store_failure(processed_url, original_url, domain, slug, reason)
            logger.warning(f"Rejected {processed_url}: {reason}")
            return None

        self._save_pdf_sync(slug, pdf_bytes, text)

        page = self._store_success(
            processed_url,
            original_url,
            domain,
            slug,
            title=None,
            author=None,
            word_count=word_count,
        )
        logger.info(f"Archived {processed_url} (PDF, {word_count} words)")
        return page

    def _process_html(
        self,
        html: str,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Validate HTML, convert to markdown, and archive.

        For raw text URLs (.md, .txt), the content is stored directly
        without HTML conversion.

        Returns a Page on success, None on failure (failure is recorded in DB).
        """
        # Raw text URLs: store content directly, skip HTML validation/conversion
        if is_raw_text_url(processed_url):
            # The "html" is actually plain text from the browser's rendering
            word_count = len(html.split())
            if word_count < self.min_words:
                reason = f"too short ({word_count} words)"
                self._store_failure(processed_url, original_url, domain, slug, reason)
                logger.warning(f"Rejected {processed_url}: {reason}")
                return None

            self._save_files_sync(slug, html, html)
            page = self._store_success(
                processed_url,
                original_url,
                domain,
                slug,
                title=None,
                author=None,
                word_count=word_count,
            )
            logger.info(f"Archived {processed_url} (raw text, {word_count} words)")
            return page

        # Validate HTML
        block_reason = check_html(html)
        if block_reason:
            self._store_failure(processed_url, original_url, domain, slug, block_reason)
            logger.warning(f"Rejected {processed_url}: {block_reason}")
            return None

        # Convert to markdown
        result = parse_html(html, clean=True)
        if result is None:
            self._store_failure(
                processed_url, original_url, domain, slug, "extraction failed"
            )
            logger.warning(f"Rejected {processed_url}: extraction failed")
            return None

        if result.word_count < self.min_words:
            reason = f"too short ({result.word_count} words)"
            self._store_failure(processed_url, original_url, domain, slug, reason)
            logger.warning(f"Rejected {processed_url}: {reason}")
            return None

        # Write files to disk
        self._save_files_sync(slug, html, result.md_content)

        # Record success
        page = self._store_success(
            processed_url,
            original_url,
            domain,
            slug,
            result.title,
            result.author,
            result.word_count,
        )
        logger.info(f"Archived {processed_url} ({result.word_count} words)")
        return page

    def reparse_existing(self) -> int:
        """Re-parse all successfully fetched pages from their archived HTML.

        Reads page.html from disk and re-runs the conversion pipeline,
        updating the markdown file and database record. Useful after
        changing trafilatura settings or cleanup rules.

        Returns:
            Number of pages successfully re-parsed.
        """
        count = 0
        for page in self.db.get_all():
            if not page.fetched:
                continue
            html_path = self.saved_dir / page.slug / "page.html"
            if not html_path.exists():
                continue

            html = html_path.read_text(encoding="utf-8")
            result = self._process_html(
                html, page.url, page.original_url, page.domain, page.slug
            )
            if result is not None:
                count += 1
        logger.info(f"Re-parsed {count} pages from existing HTML")
        return count

    # =========================================================================
    # SYNCHRONOUS - Single page, debuggable
    # =========================================================================

    def scrape(self, url: str, refetch: bool = False) -> Page | None:
        """Fetch, validate, convert, and archive a single URL synchronously.

        Args:
            url: The URL to fetch.
            refetch: Re-download even if already fetched.

        Returns:
            Page if archived successfully, None if skipped/failed.
        """
        processed_url, skip_reason = process_url(url)
        if processed_url is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            return None

        domain = registered_domain(processed_url) or split_url(processed_url)[0]
        slug = slug_for_url(processed_url)

        if not self._needs_fetch(processed_url, refetch):
            return self.db.get(processed_url)

        # PDF URLs: download directly and parse with liteparse
        if is_pdf_url(processed_url):
            pdf_bytes = self._download_pdf(processed_url)
            if pdf_bytes is None:
                self._store_failure(
                    processed_url, url, domain, slug, "PDF download failed"
                )
                return None
            return self._process_pdf(pdf_bytes, processed_url, url, domain, slug)

        html = self._fetch_sync(processed_url)
        if html is None:
            self._store_failure(processed_url, url, domain, slug, "fetch failed")
            return None

        # Browser got a download trigger instead of HTML — try as PDF
        if html == _DOWNLOAD_SENTINEL:
            pdf_bytes = self._download_pdf(processed_url)
            if pdf_bytes is None:
                self._store_failure(
                    processed_url,
                    url,
                    domain,
                    slug,
                    "download triggered but PDF fetch failed",
                )
                return None
            return self._process_pdf(pdf_bytes, processed_url, url, domain, slug)

        return self._process_html(html, processed_url, url, domain, slug)

    def _fetch_sync(self, url: str) -> str | None:
        """Fetch HTML content synchronously using patchright.

        Uses Chrome with a persistent context and no fingerprint injection
        for maximum stealth.

        Args:
            url: The URL to fetch.

        Returns:
            Raw HTML string, or None if the fetch failed.
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

    # =========================================================================
    # ASYNC BATCH - Multiple pages with concurrency
    # =========================================================================

    def scrape_batch(self, urls: list[str], refetch: bool = False) -> list[Page]:
        """Fetch, validate, convert, and archive multiple URLs concurrently.

        Args:
            urls: List of URLs to fetch.
            refetch: Re-download even if already fetched.

        Returns:
            List of successfully archived Pages.
        """
        return asyncio.run(self._scrape_batch_async(urls, refetch))

    async def _scrape_batch_async(
        self,
        urls: list[str],
        refetch: bool,
    ) -> list[Page]:
        """Process URLs, skip cached, fetch the rest concurrently.

        PDF URLs are downloaded directly (no browser needed) and parsed
        with liteparse. HTML URLs go through patchright.
        """
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

            domain = registered_domain(processed_url) or split_url(processed_url)[0]
            slug = slug_for_url(processed_url)
            entry = (processed_url, url, domain, slug)

            if is_pdf_url(processed_url):
                to_fetch_pdf.append(entry)
            else:
                to_fetch_html.append(entry)

        results: list[Page] = []

        # Process PDFs (no browser needed, CPU-bound parsing)
        for processed_url, original_url, domain, slug in to_fetch_pdf:
            pdf_bytes = self._download_pdf(processed_url)
            if pdf_bytes is None:
                self._store_failure(
                    processed_url, original_url, domain, slug, "PDF download failed"
                )
                continue
            page = self._process_pdf(
                pdf_bytes, processed_url, original_url, domain, slug
            )
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
        """Fetch, validate, convert, and archive a single URL (async).

        Retries transient errors (timeouts, connection resets) up to
        max_retries times before recording a failure.

        Args:
            semaphore: Concurrency limiter.
            context: Patchright browser context.
            processed_url: The processed/normalized URL.
            original_url: The original URL before rewriting.
            domain: Registered domain for the URL.
            slug: Folder name for archival.

        Returns:
            Page if archived successfully, None on failure.
        """
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

                    # Browser triggered a file download — try the PDF path
                    if "Download is starting" in last_reason:
                        await pw_page.close()
                        pdf_bytes = self._download_pdf(processed_url)
                        if pdf_bytes is not None:
                            return self._process_pdf(
                                pdf_bytes, processed_url, original_url, domain, slug
                            )
                        self._store_failure(
                            processed_url,
                            original_url,
                            domain,
                            slug,
                            "download triggered but PDF fetch failed",
                        )
                        logger.warning(
                            f"Fetch error {processed_url}: download triggered "
                            f"but PDF fetch failed"
                        )
                        return None
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

        # Raw text URLs: store directly, skip HTML validation/conversion
        if is_raw_text_url(processed_url):
            word_count = len(html.split())
            if word_count < self.min_words:
                reason = f"too short ({word_count} words)"
                self._store_failure(processed_url, original_url, domain, slug, reason)
                logger.warning(f"Rejected {processed_url}: {reason}")
                return None
            slug_dir = self.saved_dir / slug
            await self._save_files_async(slug_dir, html, html)
            page = self._store_success(
                processed_url,
                original_url,
                domain,
                slug,
                title=None,
                author=None,
                word_count=word_count,
            )
            logger.info(f"Archived {processed_url} (raw text, {word_count} words)")
            return page

        # Validate, convert, and archive (CPU-bound, outside semaphore)
        block_reason = check_html(html)
        if block_reason:
            self._store_failure(processed_url, original_url, domain, slug, block_reason)
            logger.warning(f"Rejected {processed_url}: {block_reason}")
            return None

        result = parse_html(html, clean=True)
        if result is None:
            self._store_failure(
                processed_url, original_url, domain, slug, "extraction failed"
            )
            logger.warning(f"Rejected {processed_url}: extraction failed")
            return None

        if result.word_count < self.min_words:
            reason = f"too short ({result.word_count} words)"
            self._store_failure(processed_url, original_url, domain, slug, reason)
            logger.warning(f"Rejected {processed_url}: {reason}")
            return None

        # Write files to disk
        slug_dir = self.saved_dir / slug
        await self._save_files_async(slug_dir, html, result.md_content)

        # Record success
        page = self._store_success(
            processed_url,
            original_url,
            domain,
            slug,
            result.title,
            result.author,
            result.word_count,
        )
        logger.info(f"Archived {processed_url} ({result.word_count} words)")
        return page
