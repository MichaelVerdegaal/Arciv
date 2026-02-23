"""Web scraper that fetches pages and stores results in SQLite."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import brotli
from loguru import logger
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from clotho.db import Page, PageDatabase
from config import HTML_DIR

from .clean_markdown import clean_markdown
from .convert import count_words, extract_metadata, html_to_markdown
from .url_processor import hash_filename, process_url, registered_domain, split_url

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5
DEFAULT_MIN_WORDS = 200
BROTLI_QUALITY = 6


@dataclass
class _ConversionResult:
    """Internal result of HTML-to-markdown conversion."""

    md_content: str
    word_count: int
    title: str | None = None
    author: str | None = None


class Scraper:
    """Web scraper that fetches pages and stores results in SQLite.

    Supports both single-page scraping (synchronous, for debugging) and
    batch scraping (async with concurrency control). All results are
    persisted to a PageDatabase.

    Args:
        db: Database to store scraped pages.
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
        min_words: Minimum word count for a page to be considered valid.
    """

    def __init__(
        self,
        db: PageDatabase,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.db = db
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
        return HTML_DIR / domain / filename, subpath

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

    def _convert(self, html_content: str, clean: bool) -> _ConversionResult | None:
        """Convert HTML to markdown and extract metadata.

        Args:
            html_content: Raw HTML string.
            clean: Whether to apply markdown cleaning.

        Returns:
            Conversion result, or None if extraction failed entirely.
        """
        md_content = html_to_markdown(html_content)
        if md_content is None:
            return None

        if clean:
            md_content = clean_markdown(md_content)

        title, author = extract_metadata(html_content)
        return _ConversionResult(
            md_content=md_content,
            word_count=count_words(md_content),
            title=title,
            author=author,
        )

    def _build_and_store(
        self,
        processed_url: str,
        original_url: str,
        source_notes: list[str],
        domain: str,
        html_subpath: str,
        result: _ConversionResult | None,
    ) -> Page | None:
        """Build a Page from conversion result, store in DB, and log.

        Returns:
            The Page if scraping succeeded (status='scraped'), None otherwise.
            Failed/too-short outcomes are still stored in the database.
        """
        if result is None:
            page = Page(
                url=processed_url,
                original_url=original_url,
                source_notes=source_notes,
                domain=domain,
                status="failed",
                fail_reason="extraction failed",
                html_path=html_subpath,
            )
            self.db.upsert(page)
            logger.warning(f"Failed {processed_url}: extraction failed")
            return None

        if result.word_count < self.min_words:
            reason = f"too short ({result.word_count} < {self.min_words} words)"
            page = Page(
                url=processed_url,
                original_url=original_url,
                source_notes=source_notes,
                domain=domain,
                status="too_short",
                fail_reason=reason,
                html_path=html_subpath,
                word_count=result.word_count,
            )
            self.db.upsert(page)
            logger.warning(f"Failed {processed_url}: {reason}")
            return None

        page = Page(
            url=processed_url,
            original_url=original_url,
            source_notes=source_notes,
            domain=domain,
            status="scraped",
            md_content=result.md_content,
            html_path=html_subpath,
            title=result.title,
            author=result.author,
            word_count=result.word_count,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        self.db.upsert(page)
        logger.info(f"Scraped {processed_url} ({result.word_count} words)")
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
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> MarkdownNote | None:
        """Scrape a single URL synchronously.

        This is the simple, debuggable path. Use for single pages or debugging.
        For multiple URLs, use scrape_batch() instead.

        Args:
            url: The URL to scrape.
            refetch: Re-download HTML even if cached.
            reclean: Regenerate Markdown even if cached.
            clean: Apply markdown cleaning to extracted content.

        Returns:
            MarkdownNote for the scraped content, or None if scraping failed.
        """
        processed_url, skip_reason = process_url(url)
        if processed_url is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            return None

        # Filenames
        domain, _ = split_url(processed_url)
        html_path = HTML_DIR / domain / self._hash_filename(processed_url, ".html")
        md_path = MARKDOWN_DIR / domain / self._hash_filename(processed_url, ".md")
        md_filename = md_path.name

        # Cache hit: markdown exists
        if md_path.exists() and not reclean and not refetch:
            logger.info(f"Scraped {processed_url} -> {md_filename} (cached)")
            return MarkdownNote(md_path)

        # Cache hit: HTML exists, just reconvert
        if html_path.exists() and not refetch:
            html_content = html_path.read_text(encoding="utf-8")
            note, fail_reason = self._convert_and_save(html_content, md_path, clean)
            if note:
                logger.info(f"Scraped {processed_url} -> {md_filename} (reconverted)")
            else:
                logger.warning(f"Failed {processed_url}: {fail_reason}")
            return note

        # Cache miss: fetch fresh
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(
                    processed_url,
                    wait_until="domcontentloaded",
                    timeout=self.page_timeout,
                )
                html_content = page.content()

                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html_content, encoding="utf-8")

                note, fail_reason = self._convert_and_save(html_content, md_path, clean)
                if note:
                    logger.info(f"Scraped {processed_url} -> {md_filename}")
                else:
                    logger.warning(f"Failed {processed_url}: {fail_reason}")
                return note

            except Exception as e:
                logger.warning(f"Failed {processed_url}: {self._format_fetch_error(e)}")
                return None
            finally:
                page.close()
                browser.close()

    # =========================================================================
    # ASYNC BATCH - Multiple pages with concurrency
    # =========================================================================

    def scrape_batch(
        self,
        urls: list[str],
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> list[MarkdownNote]:
        """Scrape multiple URLs concurrently.

        Args:
            urls: List of URLs to scrape.
            refetch: Re-download HTML even if cached.
            reclean: Regenerate Markdown even if cached.
            clean: Apply markdown cleaning to extracted content.

        Returns:
            List of successfully scraped MarkdownNotes (failed URLs are logged
            and omitted from results).
        """
        return asyncio.run(self._scrape_batch_async(urls, refetch, reclean, clean))

    async def _scrape_batch_async(
        self,
        urls: list[str],
        refetch: bool,
        reclean: bool,
        clean: bool,
    ) -> list[MarkdownNote]:
        """Check caches, then fetch what's missing concurrently."""
        results: list[MarkdownNote] = []
        to_fetch: list[tuple[str, Path, Path]] = []

        for url in urls:
            processed_url, skip_reason = process_url(url)
            if processed_url is None:
                logger.warning(f"Skipped {url}: {skip_reason}")
                continue

            domain, _ = split_url(processed_url)
            html_path = HTML_DIR / domain / self._hash_filename(processed_url, ".html")
            md_path = MARKDOWN_DIR / domain / self._hash_filename(processed_url, ".md")
            md_filename = md_path.name

            # Cache hit: markdown exists
            if md_path.exists() and not reclean and not refetch:
                logger.info(f"Scraped {processed_url} -> {md_filename} (cached)")
                results.append(MarkdownNote(md_path))
                continue

            # Cache hit: HTML exists, just reconvert
            if html_path.exists() and not refetch:
                html_content = html_path.read_text(encoding="utf-8")
                note, fail_reason = self._convert_and_save(html_content, md_path, clean)
                if note:
                    logger.info(
                        f"Scraped {processed_url} -> {md_filename} (reconverted)"
                    )
                    results.append(note)
                else:
                    logger.warning(f"Failed {processed_url}: {fail_reason}")
                continue

            to_fetch.append((processed_url, html_path, md_path))

        if to_fetch:
            fetched = await self._fetch_all(to_fetch, clean)
            results.extend(fetched)

        return results

    async def _fetch_all(
        self,
        to_fetch: list[tuple[str, Path, Path]],
        clean: bool,
    ) -> list[MarkdownNote]:
        """Fetch URLs concurrently with shared browser instance."""
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            async def fetch_one(
                url: str, html_path: Path, md_path: Path
            ) -> MarkdownNote | None:
                md_filename = md_path.name
                async with semaphore:
                    page = await browser.new_page()
                    try:
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=self.page_timeout,
                        )
                        html_content = await page.content()

                        html_path.parent.mkdir(parents=True, exist_ok=True)
                        async with aiofiles.open(html_path, "w", encoding="utf-8") as f:
                            await f.write(html_content)

                        note, fail_reason = self._convert_and_save(
                            html_content, md_path, clean
                        )
                        if note:
                            logger.info(f"Scraped {url} -> {md_filename}")
                        else:
                            logger.warning(f"Failed {url}: {fail_reason}")
                        return note

                    except Exception as e:
                        logger.warning(f"Failed {url}: {self._format_fetch_error(e)}")
                        )
                        return None
                    finally:
                        await pw_page.close()

            tasks = [fetch_one(*item) for item in to_fetch]
            fetched = await asyncio.gather(*tasks)
            await browser.close()

        return [page for page in fetched if page is not None]
