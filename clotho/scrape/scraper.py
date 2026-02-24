"""Web scraper that fetches HTML pages and stores them as compressed archives."""

import asyncio
from pathlib import Path

import aiofiles
import brotli
from loguru import logger
from playwright.async_api import Browser as AsyncBrowser, async_playwright
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from clotho.db import Page, PageDatabase

from .url_processor import hash_filename, process_url, registered_domain, split_url
from .user_agents import random_user_agent

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5
BROTLI_QUALITY = 6
BLOCKED_RESOURCE_TYPES = {"image", "stylesheet", "font"}


class Scraper:
    """Web scraper that fetches HTML pages and stores compressed archives.

    Handles URL processing, HTML fetching via Playwright, and Brotli-compressed
    archival. Does NOT parse HTML to markdown — use clotho.parse.Parser for that.

    Supports both single-page fetching (sync, for debugging) and batch
    fetching (async with concurrency control).

    Args:
        db: Database to store page records.
        html_dir: Directory for storing compressed HTML archives.
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
    """

    def __init__(
        self,
        db: PageDatabase,
        html_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.db = db
        self.html_dir = html_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _html_path(self, processed_url: str) -> tuple[Path, str]:
        """Build the absolute and relative HTML archive paths.

        Args:
            processed_url: The processed/normalized URL.

        Returns:
            Tuple of (absolute_path, relative_subpath for DB storage).
        """
        domain, _ = split_url(processed_url)
        filename = hash_filename(processed_url, ".html.br")
        subpath = f"{domain}/{filename}"
        return self.html_dir / domain / filename, subpath

    @staticmethod
    def _save_compressed_html(html_content: str, path: Path) -> None:
        """Compress HTML with Brotli and save to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            brotli.compress(html_content.encode("utf-8"), quality=BROTLI_QUALITY)
        )

    def _needs_fetch(self, processed_url: str, refetch: bool) -> bool:
        """Check if a URL needs to be fetched.

        Returns True for new URLs, pending URLs, and all URLs when refetch
        is True. Already-fetched/scraped/failed URLs are skipped.

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
        return existing.status == "pending"

    def _store_fetch_success(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        html_subpath: str,
    ) -> Page:
        """Record a successful fetch in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            status="fetched",
            html_path=html_subpath,
        )
        self.db.upsert(page)
        logger.info(f"Fetched {processed_url}")
        return page

    def _store_fetch_failure(
        self,
        processed_url: str,
        original_url: str,
        domain: str,
        fail_reason: str,
    ) -> None:
        """Record a fetch failure in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            domain=domain,
            status="failed",
            fail_reason=fail_reason,
        )
        self.db.upsert(page)
        logger.warning(f"Failed {processed_url}: {fail_reason}")

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

    # =========================================================================
    # SYNCHRONOUS - Single page, debuggable
    # =========================================================================

    def scrape(self, url: str, refetch: bool = False) -> Page | None:
        """Fetch a single URL synchronously.

        Downloads the HTML, saves it as a Brotli-compressed archive, and
        records the result in the database with status 'fetched'.
        Does NOT convert HTML to markdown.

        Args:
            url: The URL to fetch.
            refetch: Re-download HTML even if already fetched.

        Returns:
            Page if fetch succeeded or already cached, None if skipped/failed.
        """
        processed_url, skip_reason = process_url(url)
        if processed_url is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            return None

        domain = registered_domain(processed_url) or split_url(processed_url)[0]
        html_abs_path, html_subpath = self._html_path(processed_url)

        if not self._needs_fetch(processed_url, refetch):
            logger.info(f"Already fetched {processed_url} (cached)")
            return self.db.get(processed_url)

        html_content = self._fetch_sync(processed_url)
        if html_content is None:
            self._store_fetch_failure(processed_url, url, domain, "fetch failed")
            return None

        self._save_compressed_html(html_content, html_abs_path)
        return self._store_fetch_success(processed_url, url, domain, html_subpath)

    def _fetch_sync(self, url: str) -> str | None:
        """Fetch HTML content synchronously using Playwright.

        Args:
            url: The URL to fetch.

        Returns:
            Raw HTML string, or None if the fetch failed.
        """
        stealth = Stealth()
        with stealth.use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            pw_page = browser.new_page(user_agent=random_user_agent())
            pw_page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                else route.continue_(),
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
        """Fetch multiple URLs concurrently.

        Downloads HTML for URLs that need it, skipping already-fetched pages.
        Does NOT convert HTML to markdown.

        Args:
            urls: List of URLs to fetch.
            refetch: Re-download HTML even if already fetched.

        Returns:
            List of newly fetched Pages.
        """
        return asyncio.run(self._scrape_batch_async(urls, refetch))

    async def _scrape_batch_async(
        self,
        urls: list[str],
        refetch: bool,
    ) -> list[Page]:
        """Process URLs, skip cached, fetch the rest concurrently."""
        to_fetch: list[tuple[str, str, str, str, Path]] = []
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
                logger.info(f"Already fetched {processed_url} (cached)")
                continue

            domain = registered_domain(processed_url) or split_url(processed_url)[0]
            html_abs_path, html_subpath = self._html_path(processed_url)
            to_fetch.append((processed_url, url, domain, html_subpath, html_abs_path))

        if not to_fetch:
            return []

        return await self._fetch_all(to_fetch)

    async def _fetch_all(
        self,
        to_fetch: list[tuple[str, str, str, str, Path]],
    ) -> list[Page]:
        """Fetch URLs concurrently with a shared browser instance."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        stealth = Stealth()

        async with stealth.use_async(async_playwright()) as p:
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
        html_subpath: str,
        html_abs_path: Path,
    ) -> Page | None:
        """Fetch a single URL and save the Brotli-compressed HTML archive.

        Args:
            semaphore: Concurrency limiter.
            browser: Playwright browser instance.
            processed_url: The processed/normalized URL.
            original_url: The original URL before processing.
            domain: Registered domain.
            html_subpath: Relative path for DB storage.
            html_abs_path: Absolute path for HTML archive.

        Returns:
            The Page if fetch succeeded, None otherwise.
        """
        async with semaphore:
            pw_page = await browser.new_page(user_agent=random_user_agent())
            await pw_page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                else route.continue_(),
            )
            try:
                await pw_page.goto(
                    processed_url,
                    wait_until="domcontentloaded",
                    timeout=self.page_timeout,
                )
                html_content = await pw_page.content()

                # Save Brotli-compressed HTML archive
                html_abs_path.parent.mkdir(parents=True, exist_ok=True)
                compressed = brotli.compress(
                    html_content.encode("utf-8"),
                    quality=BROTLI_QUALITY,
                )
                async with aiofiles.open(html_abs_path, "wb") as f:
                    await f.write(compressed)

                return self._store_fetch_success(
                    processed_url, original_url, domain, html_subpath
                )

            except Exception as e:
                self._store_fetch_failure(
                    processed_url,
                    original_url,
                    domain,
                    self._format_fetch_error(e),
                )
                return None
            finally:
                await pw_page.close()
