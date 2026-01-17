import asyncio
import hashlib

from loguru import logger
from playwright.async_api import async_playwright

from config import SCRAPED_PAGES_DIR

from .clean_markdown import clean_markdown
from .convert import html_to_markdown
from .url_processor import process_url, split_url

TIMEOUT_MS = 10000  # 10 seconds


class Scraper:
    def __init__(self, page_timeout: int = TIMEOUT_MS):
        self.page_timeout = page_timeout

    def _hash_filename(self, url: str, extension: str = ".md") -> str:
        """Generate a hashed filename from URL: {domain}-{hash}.{extension}

        Args:
            url: The URL to generate the filename for
            extension: File extension (default: .md)

        Returns:
            A string filename based on the URL
        """
        domain, _ = split_url(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}{extension}"

    async def _fetch_html(self, url: str) -> tuple[str | None, str]:
        """Fetches the HTML content of a URL using Playwright.

        Args:
            url: The URL to fetch

        Returns:
            Tuple of (html_content, url) where html_content is None if failed
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self.page_timeout
                )
                html = await page.content()
                return html, url
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
                return None, url
            finally:
                await page.close()

    def scrape(
        self, url: str, overwrite: bool = False, save: bool = True
    ) -> str | None:
        """Scrape a web page, convert to markdown, and clean.

        Args:
            url: The URL of the page to scrape
            overwrite: Whether to overwrite existing saved file
            save: Whether to save the cleaned markdown to file

        Returns:
            Cleaned markdown text, or None if failed
        """
        processed_url = process_url(url)

        if processed_url is None:
            logger.debug(f"Skipping URL: {url}")
            return None

        # Check if cleaned file already exists
        filename = self._hash_filename(processed_url, extension=".md")
        output_path = SCRAPED_PAGES_DIR / filename

        if output_path.exists() and not overwrite:
            logger.debug(f"Using cached: {filename}")
            return output_path.read_text(encoding="utf-8")

        logger.info(f"Scraping {processed_url[:80]}...")
        html_content, url = asyncio.run(self._fetch_html(processed_url))

        if html_content is None:
            return None

        # Convert HTML to markdown
        md_content = html_to_markdown(html_content)
        if md_content is None:
            logger.warning(f"Failed to extract content from {url}")
            return None

        # Clean and optionally save
        cleaned_content = clean_markdown(md_content)
        if save:
            SCRAPED_PAGES_DIR.mkdir(parents=True, exist_ok=True)
            output_path.write_text(cleaned_content, encoding="utf-8")

        return cleaned_content
