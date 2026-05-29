"""Web scraper that fetches, validates, converts, and archives pages.

Uses patchright (undetected Playwright fork) for fetching. Each page goes
through: fetch HTML → validate (block-page / size check) → convert to
markdown via trafilatura → write HTML + MD to disk → record in DB.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from loguru import logger
from patchright.async_api import Browser as AsyncBrowser, async_playwright
from patchright.sync_api import sync_playwright

from clotho.db import Page, PageDatabase
from clotho.parse import parse_html

from .url_processor import process_url, registered_domain, slug_for_url, split_url
from .validate import check_html

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5
DEFAULT_MIN_WORDS = 150
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font"}


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
    """

    def __init__(
        self,
        db: PageDatabase,
        saved_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.db = db
        self.saved_dir = saved_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.min_words = min_words

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

    def _process_html(
        self,
        html: str,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Validate HTML, convert to markdown, and archive.

        Returns a Page on success, None on failure (failure is recorded in DB).
        """
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

        html = self._fetch_sync(processed_url)
        if html is None:
            self._store_failure(processed_url, url, domain, slug, "fetch failed")
            return None

        return self._process_html(html, processed_url, url, domain, slug)

    def _fetch_sync(self, url: str) -> str | None:
        """Fetch HTML content synchronously using patchright.

        Args:
            url: The URL to fetch.

        Returns:
            Raw HTML string, or None if the fetch failed.
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pw_page = browser.new_page()
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
                return pw_page.content()
            except Exception as e:
                logger.warning(f"Fetch error {url}: {self._format_fetch_error(e)}")
                return None
            finally:
                pw_page.close()
                browser.close()

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
        """Process URLs, skip cached, fetch the rest concurrently."""
        to_fetch: list[tuple[str, str, str, str]] = []
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
            to_fetch.append((processed_url, url, domain, slug))

        if not to_fetch:
            return []

        return await self._fetch_all(to_fetch)

    async def _fetch_all(
        self,
        to_fetch: list[tuple[str, str, str, str]],
    ) -> list[Page]:
        """Fetch URLs concurrently with a shared browser instance."""
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            tasks = [
                self._fetch_one_async(semaphore, browser, *item) for item in to_fetch
            ]
            fetched = await asyncio.gather(*tasks)
            await browser.close()

        return [page for page in fetched if page is not None]

    async def _fetch_one_async(
        self,
        semaphore: asyncio.Semaphore,
        browser: AsyncBrowser,
        processed_url: str,
        original_url: str,
        domain: str,
        slug: str,
    ) -> Page | None:
        """Fetch, validate, convert, and archive a single URL (async).

        Args:
            semaphore: Concurrency limiter.
            browser: Patchright browser instance.
            processed_url: The processed/normalized URL.
            original_url: The original URL before rewriting.
            domain: Registered domain for the URL.
            slug: Folder name for archival.

        Returns:
            Page if archived successfully, None on failure.
        """
        async with semaphore:
            pw_page = await browser.new_page()
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
                html = await pw_page.content()
            except Exception as e:
                reason = self._format_fetch_error(e)
                self._store_failure(
                    processed_url, original_url, domain, slug, reason
                )
                logger.warning(f"Fetch error {processed_url}: {reason}")
                return None
            finally:
                await pw_page.close()

        # Validate, convert, and archive (CPU-bound, outside semaphore)
        block_reason = check_html(html)
        if block_reason:
            self._store_failure(
                processed_url, original_url, domain, slug, block_reason
            )
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
