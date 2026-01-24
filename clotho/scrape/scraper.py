import asyncio
import hashlib
from pathlib import Path

import aiofiles
from loguru import logger
from playwright.async_api import Browser, async_playwright

from clotho.notes import MarkdownNote
from config import HTML_DIR, MARKDOWN_DIR

from .clean_markdown import clean_markdown
from .convert import html_to_markdown
from .url_processor import process_url, split_url

TIMEOUT_MS = 10000  # 10 seconds
DEFAULT_CONCURRENCY = 5  # Max concurrent page fetches


class Scraper:
    def __init__(
        self, page_timeout: int = TIMEOUT_MS, max_concurrency: int = DEFAULT_CONCURRENCY
    ):
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency

    def _hash_filename(self, url: str, extension: str = ".md") -> str:
        """Generate a hashed filename from URL: {domain}-{hash}.{extension}

        Args:
            url: The URL to generate the filename for
            extension: File extension (default: .md)

        Returns:
            A string filename based on the URL hash
        """
        domain, _ = split_url(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}{extension}"

    async def _fetch_html(self, browser: Browser, url: str, html_path) -> str | None:
        """Fetches HTML content from URL using shared browser instance.

        Args:
            browser: Playwright browser instance to use
            url: The URL to fetch
            html_path: Path where the HTML file will be saved

        Returns:
            HTML content string, or None if failed
        """
        page = await browser.new_page()

        try:
            await page.goto(
                url, wait_until="domcontentloaded", timeout=self.page_timeout
            )
            html = await page.content()

            html_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(html_path, mode="w", encoding="utf-8") as f:
                await f.write(html)

            return html
        except Exception as e:
            # Extract clean error message from Playwright exceptions
            error_msg = str(e).split("\n")[0]  # First line only
            if "net::ERR_NAME_NOT_RESOLVED" in error_msg:
                logger.error(f"DNS resolution failed for {url} (site may be down)")
            elif "net::ERR_CONNECTION_REFUSED" in error_msg:
                logger.error(f"Connection refused for {url}")
            elif "Timeout" in error_msg:
                logger.error(f"Timeout fetching {url}")
            else:
                logger.error(f"Failed to fetch {url}: {error_msg}")
            return None
        finally:
            await page.close()

    def _get_paths(self, url: str) -> tuple[str, Path, Path] | None:
        """Process URL and return paths for caching.

        Args:
            url: The URL to process

        Returns:
            Tuple of (processed_url, html_path, md_path) or None if URL should be skipped
        """
        processed_url = process_url(url)
        if processed_url is None:
            return None

        domain, _ = split_url(processed_url)
        html_path = (
            HTML_DIR / domain / self._hash_filename(processed_url, extension=".html")
        )
        md_path = (
            MARKDOWN_DIR / domain / self._hash_filename(processed_url, extension=".md")
        )
        return processed_url, html_path, md_path

    def _convert_and_save(
        self, html_content: str, md_path: Path, clean: bool
    ) -> MarkdownNote | None:
        """Convert HTML to markdown, optionally clean, and save.

        Args:
            html_content: The HTML content to convert
            md_path: Path where the markdown file will be saved
            clean: Whether to clean the markdown

        Returns:
            MarkdownNote instance or None if conversion failed
        """
        md_content = html_to_markdown(html_content)
        if md_content is None:
            return None

        if clean:
            md_content = clean_markdown(md_content)

        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
        return MarkdownNote(md_path)

    def scrape(
        self,
        url: str,
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> MarkdownNote | None:
        """Scrape a single URL. For multiple URLs, use scrape_batch() instead.

        Args:
            url: The URL of the page to scrape
            refetch: Whether to re-fetch the HTML even if cached
            reclean: Whether to recreate the markdown even if cached
            clean: Whether to clean the markdown before saving

        Returns:
            MarkdownNote instance from the saved file, or None if failed
        """
        results = asyncio.run(
            self._scrape_batch_async([url], refetch=refetch, reclean=reclean, clean=clean)
        )
        return results[0] if results else None

    def scrape_batch(
        self,
        urls: list[str],
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> list[MarkdownNote]:
        """Scrape multiple URLs concurrently.

        Args:
            urls: List of URLs to scrape
            refetch: Whether to re-fetch HTML even if cached
            reclean: Whether to recreate markdown even if cached
            clean: Whether to clean the markdown before saving

        Returns:
            List of successfully scraped MarkdownNote instances
        """
        return asyncio.run(
            self._scrape_batch_async(urls, refetch=refetch, reclean=reclean, clean=clean)
        )

    async def _scrape_batch_async(
        self,
        urls: list[str],
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> list[MarkdownNote]:
        """Internal async implementation for batch scraping.

        Args:
            urls: List of URLs to scrape
            refetch: Whether to re-fetch HTML even if cached
            reclean: Whether to recreate markdown even if cached
            clean: Whether to clean the markdown before saving

        Returns:
            List of successfully scraped MarkdownNote instances
        """
        # Pre-process URLs and check cache
        to_fetch: list[tuple[str, Path, Path]] = []  # (url, html_path, md_path)
        results: list[MarkdownNote] = []

        for url in urls:
            paths = self._get_paths(url)
            if paths is None:
                logger.debug(f"URL skipped: {url}")
                continue

            processed_url, html_path, md_path = paths

            # Return cached markdown if available
            if md_path.exists() and not reclean and not refetch:
                results.append(MarkdownNote(md_path))
                continue

            # Use cached HTML if available
            if html_path.exists() and not refetch:
                html_content = html_path.read_text(encoding="utf-8")
                note = self._convert_and_save(html_content, md_path, clean)
                if note:
                    results.append(note)
                else:
                    logger.warning(f"Failed to extract content from {processed_url}")
                continue

            to_fetch.append((processed_url, html_path, md_path))

        if not to_fetch:
            return results

        # Fetch URLs concurrently with shared browser
        logger.info(f"Fetching {len(to_fetch)} URLs concurrently...")
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            async def fetch_one(
                url: str, html_path: Path, md_path: Path
            ) -> MarkdownNote | None:
                async with semaphore:
                    logger.info(f"Scraping {url[:80]}...")
                    html_content = await self._fetch_html(browser, url, html_path)
                    if html_content is None:
                        return None
                    return self._convert_and_save(html_content, md_path, clean)

            tasks = [fetch_one(url, hp, mp) for url, hp, mp in to_fetch]
            fetched = await asyncio.gather(*tasks)

            await browser.close()

        results.extend(note for note in fetched if note is not None)
        return results
