"""Web scraper that fetches pages and stores results in SQLite."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import aiofiles
import brotli
from loguru import logger
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from clotho.db import Page, PageDatabase
from clotho.parse import ConversionResult, parse_html

from .url_processor import hash_filename, process_url, registered_domain, split_url

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5
DEFAULT_MIN_WORDS = 200
BROTLI_QUALITY = 6


class Scraper:
    """Web scraper that fetches pages and stores results in SQLite.

    Supports both single-page scraping (synchronous, for debugging) and
    batch scraping (async with concurrency control). All results are
    persisted to a PageDatabase.

    Args:
        db: Database to store scraped pages.
        html_dir: Directory for storing compressed HTML archives.
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
        min_words: Minimum word count for a page to be considered valid.
    """

    def __init__(
        self,
        db: PageDatabase,
        html_dir: Path,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.db = db
        self.html_dir = html_dir
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.min_words = min_words

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

    @staticmethod
    def _load_compressed_html(path: Path) -> str:
        """Load and decompress a Brotli-compressed HTML file."""
        return brotli.decompress(path.read_bytes()).decode("utf-8")

    def _resolve_cache(
        self,
        processed_url: str,
        html_abs_path: Path,
        refetch: bool,
        reclean: bool,
    ) -> Literal["cached", "reconvert", "fetch"]:
        """Determine what work is needed for a URL.

        Args:
            processed_url: The processed/normalized URL.
            html_abs_path: Path to the compressed HTML archive on disk.
            refetch: Whether to re-download HTML even if cached.
            reclean: Whether to re-convert HTML to markdown even if cached.

        Returns:
            "cached" if existing scraped result can be reused,
            "reconvert" if HTML exists on disk and just needs re-parsing,
            "fetch" if the page needs to be downloaded.
        """
        existing = self.db.get(processed_url)
        if existing and existing.status == "scraped" and not reclean and not refetch:
            return "cached"
        if not refetch and html_abs_path.exists():
            return "reconvert"
        return "fetch"

    def _build_and_store(
        self,
        processed_url: str,
        original_url: str,
        source_notes: list[str],
        domain: str,
        html_subpath: str,
        result: ConversionResult | None,
    ) -> Page | None:
        """Build a Page from conversion result, store in DB, and log.

        Returns:
            The Page if scraping succeeded (status='scraped'), None otherwise.
            Failed/too-short outcomes are still stored in the database.
        """
        page = Page(
            url=processed_url,
            original_url=original_url,
            source_notes=source_notes,
            domain=domain,
            html_path=html_subpath,
        )

        if result is None:
            page.status = "failed"
            page.fail_reason = "extraction failed"
        elif result.word_count < self.min_words:
            page.status = "too_short"
            page.fail_reason = (
                f"too short ({result.word_count} < {self.min_words} words)"
            )
            page.word_count = result.word_count
        else:
            page.status = "scraped"
            page.md_content = result.md_content
            page.title = result.title
            page.author = result.author
            page.word_count = result.word_count
            page.scraped_at = datetime.now(timezone.utc).isoformat()

        self.db.upsert(page)

        if page.status != "scraped":
            logger.warning(f"Failed {processed_url}: {page.fail_reason}")
            return None

        logger.info(f"Scraped {processed_url} ({page.word_count} words)")
        return page

    def _store_fetch_failure(
        self,
        processed_url: str,
        original_url: str,
        source_notes: list[str],
        domain: str,
        fail_reason: str,
    ) -> None:
        """Record a fetch failure in the database."""
        page = Page(
            url=processed_url,
            original_url=original_url,
            source_notes=source_notes,
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

    def scrape(
        self,
        url: str,
        source_notes: list[str] | None = None,
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> Page | None:
        """Scrape a single URL synchronously.

        This is the simple, debuggable path. Use for single pages or debugging.
        For multiple URLs, use scrape_batch() instead.

        Args:
            url: The URL to scrape.
            source_notes: Daily note filenames that referenced this URL.
            refetch: Re-download HTML even if cached.
            reclean: Re-convert HTML to markdown even if cached.
            clean: Apply markdown cleaning to extracted content.

        Returns:
            Page if scraping succeeded, None if skipped or failed.
            Failed pages are still stored in the database.
        """
        processed_url, skip_reason = process_url(url)
        if processed_url is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            return None

        notes = source_notes or []
        domain = registered_domain(processed_url) or split_url(processed_url)[0]
        html_abs_path, html_subpath = self._html_path(processed_url)

        # Merge source notes with any existing record
        if notes:
            self.db.merge_source_notes(processed_url, notes)

        # Use shared cache resolution
        action = self._resolve_cache(processed_url, html_abs_path, refetch, reclean)

        if action == "cached":
            logger.info(f"Scraped {processed_url} (cached)")
            return self.db.get(processed_url)

        if action == "reconvert":
            html_content = self._load_compressed_html(html_abs_path)
            result = parse_html(html_content, clean)
            return self._build_and_store(
                processed_url, url, notes, domain, html_subpath, result
            )

        # action == "fetch"
        html_content = self._fetch_sync(processed_url)
        if html_content is None:
            self._store_fetch_failure(processed_url, url, notes, domain, "fetch failed")
            return None
        self._save_compressed_html(html_content, html_abs_path)

        result = parse_html(html_content, clean)
        return self._build_and_store(
            processed_url, url, notes, domain, html_subpath, result
        )

    def _fetch_sync(self, url: str) -> str | None:
        """Fetch HTML content synchronously using Playwright.

        Args:
            url: The URL to fetch.

        Returns:
            Raw HTML string, or None if the fetch failed.
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pw_page = browser.new_page()
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

    def scrape_batch(
        self,
        urls: list[str],
        source_notes: dict[str, list[str]] | None = None,
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> list[Page]:
        """Scrape multiple URLs concurrently.

        Args:
            urls: List of URLs to scrape.
            source_notes: Optional mapping of original URL to source note
                filenames that referenced it.
            refetch: Re-download HTML even if cached.
            reclean: Re-convert HTML to markdown even if cached.
            clean: Apply markdown cleaning to extracted content.

        Returns:
            List of successfully scraped Pages. Failed URLs are stored in
            the database but omitted from results.
        """
        return asyncio.run(
            self._scrape_batch_async(urls, source_notes, refetch, reclean, clean)
        )

    async def _scrape_batch_async(
        self,
        urls: list[str],
        source_notes_map: dict[str, list[str]] | None,
        refetch: bool,
        reclean: bool,
        clean: bool,
    ) -> list[Page]:
        """Check caches, then fetch what's missing concurrently."""
        results: list[Page] = []
        to_fetch: list[tuple[str, str, list[str], str, str, Path]] = []
        seen_processed: set[str] = set()

        for url in urls:
            processed_url, skip_reason = process_url(url)
            if processed_url is None:
                logger.warning(f"Skipped {url}: {skip_reason}")
                continue

            notes = (source_notes_map or {}).get(url, [])
            domain = registered_domain(processed_url) or split_url(processed_url)[0]
            html_abs_path, html_subpath = self._html_path(processed_url)

            # Deduplicate processed URLs (multiple originals can map to same)
            if processed_url in seen_processed:
                if notes:
                    self.db.merge_source_notes(processed_url, notes)
                continue
            seen_processed.add(processed_url)

            # Merge source notes with any existing record
            if notes:
                self.db.merge_source_notes(processed_url, notes)

            # Use shared cache resolution
            action = self._resolve_cache(processed_url, html_abs_path, refetch, reclean)

            if action == "cached":
                existing = self.db.get(processed_url)
                if existing:
                    logger.info(f"Scraped {processed_url} (cached)")
                    results.append(existing)
                continue

            if action == "reconvert":
                html_content = self._load_compressed_html(html_abs_path)
                result = parse_html(html_content, clean)
                page = self._build_and_store(
                    processed_url, url, notes, domain, html_subpath, result
                )
                if page:
                    results.append(page)
                continue

            # action == "fetch"
            to_fetch.append(
                (processed_url, url, notes, domain, html_subpath, html_abs_path)
            )

        if to_fetch:
            fetched = await self._fetch_all(to_fetch, clean)
            results.extend(fetched)

        return results

    async def _fetch_all(
        self,
        to_fetch: list[tuple[str, str, list[str], str, str, Path]],
        clean: bool,
    ) -> list[Page]:
        """Fetch URLs concurrently with a shared browser instance."""
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            tasks = [
                self._fetch_and_store_async(semaphore, browser, *item, clean)
                for item in to_fetch
            ]
            fetched = await asyncio.gather(*tasks)
            await browser.close()

        return [page for page in fetched if page is not None]

    async def _fetch_and_store_async(
        self,
        semaphore: asyncio.Semaphore,
        browser: object,
        processed_url: str,
        original_url: str,
        notes: list[str],
        domain: str,
        html_subpath: str,
        html_abs_path: Path,
        clean: bool,
    ) -> Page | None:
        """Fetch a single URL, save HTML, convert, and store.

        Args:
            semaphore: Concurrency limiter.
            browser: Playwright browser instance.
            processed_url: The processed/normalized URL.
            original_url: The original URL before processing.
            notes: Source note filenames.
            domain: Registered domain.
            html_subpath: Relative path for DB storage.
            html_abs_path: Absolute path for HTML archive.
            clean: Whether to apply markdown cleaning.

        Returns:
            The Page if scraping succeeded, None otherwise.
        """
        async with semaphore:
            pw_page = await browser.new_page()
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

                # Convert and store
                result = parse_html(html_content, clean)
                return self._build_and_store(
                    processed_url,
                    original_url,
                    notes,
                    domain,
                    html_subpath,
                    result,
                )

            except Exception as e:
                self._store_fetch_failure(
                    processed_url,
                    original_url,
                    notes,
                    domain,
                    self._format_fetch_error(e),
                )
                return None
            finally:
                await pw_page.close()
