import asyncio
import hashlib
from pathlib import Path

import aiofiles
from loguru import logger
from playwright.async_api import async_playwright

from config import SCRAPED_DOCS_DIR
from clotho.scrape2.url_processor import process_url
from .url_util import split_url


TIMEOUT_MS = 10000  # 10 seconds


class Scraper:
    def __init__(self, page_timeout: int = TIMEOUT_MS):
        self.page_timeout = page_timeout

    def _hash_filename(self, url: str) -> str:
        """Generate a hashed filename from URL: {domain}-{hash}.html

        Args:
            url: The URL to generate the filename for

        Returns:
            A string filename based on the URL
        """
        domain, _ = split_url(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}.html"

    async def _fetch_html(
        self, url: str, overwrite: bool = False
    ) -> tuple[Path | None, str]:
        """Fetches the HTML page of a URL using Playwright and writes it to file.

        Args:
            url: The URL to fetch
            overwrite: Fetch page even if saved file exists

        Returns:
            The filename where HTML is saved, or None if failed
        """
        # Return saved .html file if it exists
        filename = self._hash_filename(url)
        file_path = SCRAPED_DOCS_DIR / filename

        if file_path.exists() and not overwrite:
            return file_path, url

        # Launch Playwright browser and fetch page
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.page_timeout
                )
                html = await page.content()
                async with aiofiles.open(file_path, mode="w", encoding="utf-8") as file:
                    await file.write(html)
                return file_path, url
            except Exception as e:
                logger.error(f"Failed to fetch HTML for {url}: {e}")
                return None, url
            finally:
                await page.close()

    def scrape(self, url: str, overwrite: bool = False) -> tuple[Path | None, str]:
        """Scrape a web page and save its HTML to a file.

        Args:
            url: The URL of the page to scrape
            overwrite: Whether to overwrite existing saved file

        Returns:
            A tuple of (file_path, url) where file_path is the path to the saved HTML file or None if failed
        """
        processed_url = process_url(url)

        if processed_url is None:
            logger.debug(f"Skipping URL: {url[:80]}")
            return None, url

        logger.info(f"Scraping {processed_url[:80]}...")
        return asyncio.run(self._fetch_html(processed_url, overwrite))
