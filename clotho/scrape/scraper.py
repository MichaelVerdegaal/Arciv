import asyncio
import hashlib
from pathlib import Path

import aiofiles
from loguru import logger
from playwright.async_api import Browser, async_playwright
from playwright.sync_api import sync_playwright

from clotho.notes import MarkdownNote
from config import HTML_DIR, MARKDOWN_DIR

from .clean_markdown import clean_markdown
from .convert import html_to_markdown
from .url_processor import process_url, split_url

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5


class Scraper:
    """Web scraper that fetches pages and converts them to cached Markdown.
    
    Supports both single-page scraping (synchronous, for debugging) and
    batch scraping (async with concurrency control).
    
    Args:
        page_timeout: Playwright page load timeout in milliseconds.
        max_concurrency: Maximum concurrent page fetches for batch operations.
    """

    def __init__(
        self,
        page_timeout: int = TIMEOUT_MS,
        max_concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency

    def _hash_filename(self, url: str, extension: str = ".md") -> str:
        """Generate a hashed filename from URL.
        
        Args:
            url: The URL to hash.
            extension: File extension including the dot.
            
        Returns:
            Filename in format "{domain}-{hash}{extension}".
        """
        domain, _ = split_url(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}{extension}"

    def _get_paths(self, url: str) -> tuple[str, Path, Path] | None:
        """Process URL and determine cache paths.
        
        Args:
            url: Raw URL to process.
            
        Returns:
            Tuple of (processed_url, html_cache_path, markdown_cache_path),
            or None if the URL should be skipped.
        """
        processed_url = process_url(url)
        if processed_url is None:
            return None

        domain, _ = split_url(processed_url)
        html_path = HTML_DIR / domain / self._hash_filename(processed_url, ".html")
        md_path = MARKDOWN_DIR / domain / self._hash_filename(processed_url, ".md")
        return processed_url, html_path, md_path

    def _convert_and_save(
        self,
        html_content: str,
        md_path: Path,
        clean: bool,
    ) -> MarkdownNote | None:
        """Convert HTML to Markdown and save to disk.
        
        Args:
            html_content: Raw HTML string.
            md_path: Destination path for the Markdown file.
            clean: Whether to apply markdown cleaning.
            
        Returns:
            MarkdownNote wrapping the saved file, or None if conversion failed.
        """
        md_content = html_to_markdown(html_content)
        if md_content is None:
            return None

        if clean:
            md_content = clean_markdown(md_content)

        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
        return MarkdownNote(md_path)

    def _log_fetch_error(self, url: str, error: Exception) -> None:
        """Log a fetch error with a clean, actionable message."""
        error_msg = str(error).split("\n")[0]
        
        if "net::ERR_NAME_NOT_RESOLVED" in error_msg:
            logger.error(f"DNS resolution failed for {url}")
        elif "net::ERR_CONNECTION_REFUSED" in error_msg:
            logger.error(f"Connection refused for {url}")
        elif "Timeout" in error_msg:
            logger.error(f"Timeout fetching {url}")
        else:
            logger.error(f"Failed to fetch {url}: {error_msg}")

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
        paths = self._get_paths(url)
        if paths is None:
            logger.debug(f"URL skipped: {url}")
            return None

        processed_url, html_path, md_path = paths

        # Cache hit: markdown exists
        if md_path.exists() and not reclean and not refetch:
            return MarkdownNote(md_path)

        # Cache hit: HTML exists, just reconvert
        if html_path.exists() and not refetch:
            html_content = html_path.read_text(encoding="utf-8")
            note = self._convert_and_save(html_content, md_path, clean)
            if note is None:
                logger.warning(f"Failed to extract content from {processed_url}")
            return note

        # Cache miss: fetch fresh
        logger.info(f"Scraping {processed_url[:80]}...")

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

                return self._convert_and_save(html_content, md_path, clean)
            except Exception as e:
                self._log_fetch_error(processed_url, e)
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
        return asyncio.run(
            self._scrape_batch_async(urls, refetch, reclean, clean)
        )

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
            paths = self._get_paths(url)
            if paths is None:
                continue

            processed_url, html_path, md_path = paths

            # Cache hit: markdown exists
            if md_path.exists() and not reclean and not refetch:
                results.append(MarkdownNote(md_path))
                continue

            # Cache hit: HTML exists, just reconvert
            if html_path.exists() and not refetch:
                html_content = html_path.read_text(encoding="utf-8")
                note = self._convert_and_save(html_content, md_path, clean)
                if note:
                    results.append(note)
                continue

            to_fetch.append((processed_url, html_path, md_path))

        if to_fetch:
            logger.info(f"Fetching {len(to_fetch)} URLs...")
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

            async def fetch_one(url: str, html_path: Path, md_path: Path) -> MarkdownNote | None:
                async with semaphore:
                    logger.info(f"Scraping {url[:80]}...")
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

                        return self._convert_and_save(html_content, md_path, clean)
                    except Exception as e:
                        self._log_fetch_error(url, e)
                        return None
                    finally:
                        await page.close()

            tasks = [fetch_one(url, hp, mp) for url, hp, mp in to_fetch]
            fetched = await asyncio.gather(*tasks)
            await browser.close()

        return [note for note in fetched if note is not None]