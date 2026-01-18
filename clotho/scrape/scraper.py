import asyncio
import hashlib

import aiofiles
from loguru import logger
from playwright.async_api import async_playwright

from config import HTML_DIR, MARKDOWN_DIR

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
            A string filename based on the URL hash
        """
        domain, _ = split_url(url)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}{extension}"

    async def _fetch_and_save_html(self, url: str, html_path) -> str | None:
        """Fetches HTML content from URL and saves to file.

        Args:
            url: The URL to fetch
            html_path: Path where the HTML file will be saved

        Returns:
            HTML content string, or None if failed
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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

    def scrape(
        self,
        url: str,
        refetch: bool = False,
        reclean: bool = False,
        clean: bool = True,
    ) -> str | None:
        """Scrape a web page, convert to markdown, and optionally clean.

        Args:
            url: The URL of the page to scrape
            refetch: Whether to re-fetch the HTML even if cached
            reclean: Whether to recreate the markdown even if cached
            clean: Whether to clean the markdown before saving. Only applies if creating
                a new markdown file.

        Returns:
            Markdown text (cleaned or uncleaned based on clean param), or None if failed
        """
        processed_url = process_url(url)

        if processed_url is None:
            logger.debug(f"Skipping URL: {url}")
            return None

        # Generate file paths with domain subdirectories
        domain, _ = split_url(processed_url)
        html_path = HTML_DIR / domain / self._hash_filename(processed_url, extension=".html")
        md_path = MARKDOWN_DIR / domain / self._hash_filename(processed_url, extension=".md")

        # Return cached markdown if available and not forcing refresh
        if md_path.exists() and not reclean and not refetch:
            logger.debug(f"Using cached: {md_path.name}")
            return md_path.read_text(encoding="utf-8")

        # Fetch HTML if needed
        if html_path.exists() and not refetch:
            logger.debug(f"Using cached HTML: {html_path.name}")
            html_content = html_path.read_text(encoding="utf-8")
        else:
            logger.info(f"Scraping {processed_url[:80]}...")
            html_content = asyncio.run(
                self._fetch_and_save_html(processed_url, html_path)
            )
            if html_content is None:
                return None

        # Convert HTML to markdown
        md_content = html_to_markdown(html_content)
        if md_content is None:
            logger.warning(f"Failed to extract content from {processed_url}")
            return None

        # Clean if requested
        if clean:
            md_content = clean_markdown(md_content)

        # Save markdown
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        return md_content
