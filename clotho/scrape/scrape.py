import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
from loguru import logger
from playwright.async_api import Browser, async_playwright

from config import SCRAPED_DOCS_DIR

TIMEOUT_MS = 50000  # 50 seconds


def _cache_filename(url: str) -> str:
    """Generate a cache filename from URL: {domain}-{hash}.html

    Args:
        url: The URL to generate the filename for

    Returns:
        A string filename based on the URL
    """
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

    domain = urlparse(url).netloc
    # Remove www. prefix and get main domain
    domain = domain.removeprefix("www.")
    # Take just the domain name without TLD (e.g., "thedataexchange" from "thedataexchange.media")
    domain_name = domain.split(".")[0]

    return f"{domain_name}-{url_hash}"


async def _fetch_html(
    browser: Browser, url: str, sem: asyncio.Semaphore
) -> tuple[Path | None, str]:
    """Fetches the HTML page of a URL using Playwright and writes it to file.

    Args:
        browser: Playwright browser instance
        url: The URL to fetch
        sem: Semaphore to limit concurrent fetches

    Returns:
        The filename where HTML is saved, or None if failed
    """
    # Check if cached file already exists
    filename = f"{_cache_filename(url)}.html"
    file_path = SCRAPED_DOCS_DIR / filename

    if file_path.exists():
        return file_path, url

    async with sem:
        page = await browser.new_page()

        try:
            logger.info(f"Fetching {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            html = await page.content()
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as file:
                await file.write(html)
            return file_path, url
        except Exception as e:
            logger.error(f"Failed to fetch HTML for {url}: {e}")
            return None, url
        finally:
            await page.close()


async def batch_fetch_html(urls: list[str]) -> dict[str, Path] | None:
    """Fetch HTML content for a batch of URLs using Playwright.

    Args:
        urls: List of URLs to fetch

    Returns:
        Dictionary mapping URLs to their saved HTML filenames
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        sem = asyncio.Semaphore(10)

        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(_fetch_html(browser, url, sem))
                    for url in urls
                    if not url.endswith(".pdf")  # TODO: we cannot handle PDFs yet
                ]
            task_results = [task.result() for task in tasks]
            saved_pages = {
                url: file_path for file_path, url in task_results if file_path
            }
            return saved_pages
        finally:
            await browser.close()
