import asyncio
import hashlib
from pathlib import Path

import aiofiles
from loguru import logger
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from clotho.notes import MarkdownNote
from config import HTML_DIR, MARKDOWN_DIR

from .clean_markdown import clean_markdown
from .convert import count_words, html_to_markdown
from .url_processor import process_url, split_url

TIMEOUT_MS = 10000
DEFAULT_CONCURRENCY = 5
DEFAULT_MIN_WORDS = 200


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
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.page_timeout = page_timeout
        self.max_concurrency = max_concurrency
        self.min_words = min_words

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

    def _convert_and_save(
        self,
        html_content: str,
        md_path: Path,
        clean: bool,
    ) -> tuple[MarkdownNote | None, str]:
        """Convert HTML to Markdown and save to disk.

        Args:
            html_content: Raw HTML string.
            md_path: Destination path for the Markdown file.
            clean: Whether to apply markdown cleaning.

        Returns:
            Tuple of (MarkdownNote or None, failure_reason or empty string).
        """
        md_content = html_to_markdown(html_content)
        if md_content is None:
            return None, "extraction failed"

        word_count = count_words(md_content)
        if word_count < self.min_words:
            return None, f"too short ({word_count} < {self.min_words} words)"

        if clean:
            md_content = clean_markdown(md_content)

        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
        return MarkdownNote(md_path), ""

    def _format_fetch_error(self, error: Exception) -> str:
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
                        return None
                    finally:
                        await page.close()

            tasks = [fetch_one(url, hp, mp) for url, hp, mp in to_fetch]
            fetched = await asyncio.gather(*tasks)
            await browser.close()

        return [note for note in fetched if note is not None]
