"""HTML-to-Markdown parser for scraped pages."""

from datetime import datetime, timezone
from pathlib import Path

import brotli
from loguru import logger

from clotho.db import Page, PageDatabase

from .convert import ConversionResult, parse_html

DEFAULT_MIN_WORDS = 150


class Parser:
    """Parses scraped HTML archives into markdown content.

    Loads Brotli-compressed HTML from disk, converts to markdown via
    trafilatura, and stores results in the database. Runs independently
    from the scraper — use after fetching HTML with clotho.scrape.Scraper.

    Args:
        db: Database to read/store pages.
        html_dir: Directory containing compressed HTML archives.
        min_words: Minimum word count for a page to be considered valid.
    """

    def __init__(
        self,
        db: PageDatabase,
        html_dir: Path,
        min_words: int = DEFAULT_MIN_WORDS,
    ):
        self.db = db
        self.html_dir = html_dir
        self.min_words = min_words

    # -- helpers --

    def _load_html(self, page: Page) -> str | None:
        """Load and decompress HTML for a page.

        Args:
            page: The page whose HTML to load.

        Returns:
            Raw HTML string, or None if no HTML archive is available.
        """
        if not page.html_path:
            return None
        path = self.html_dir / page.html_path
        if not path.exists():
            return None
        return brotli.decompress(path.read_bytes()).decode("utf-8")

    def _store_result(
        self,
        page: Page,
        result: ConversionResult | None,
    ) -> Page | None:
        """Update a page with parse results and store in DB.

        Args:
            page: The page to update.
            result: Conversion result, or None if extraction failed.

        Returns:
            The page if parsing succeeded (status='scraped'), None otherwise.
        """
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
            logger.warning(f"Parse failed {page.url}: {page.fail_reason}")
            return None

        logger.info(f"Parsed {page.url} ({page.word_count} words)")
        return page

    # -- public API --

    def parse_page(self, page: Page, clean: bool = True) -> Page | None:
        """Parse a single page's HTML into markdown.

        Args:
            page: The page to parse. Must have html_path set.
            clean: Whether to apply markdown cleaning.

        Returns:
            The page with status 'scraped' if successful, None otherwise.
        """
        html_content = self._load_html(page)
        if html_content is None:
            logger.warning(f"No HTML available for {page.url}")
            return None

        result = parse_html(html_content, clean)
        return self._store_result(page, result)

    def parse_pages(self, pages: list[Page], clean: bool = True) -> list[Page]:
        """Parse multiple pages.

        Args:
            pages: Pages to parse.
            clean: Whether to apply markdown cleaning.

        Returns:
            List of successfully parsed pages.
        """
        results = []
        for page in pages:
            parsed = self.parse_page(page, clean)
            if parsed:
                results.append(parsed)
        return results

    def parse_unparsed(self, clean: bool = True) -> list[Page]:
        """Parse all pages with status 'fetched' (HTML available, not yet parsed).

        Args:
            clean: Whether to apply markdown cleaning.

        Returns:
            List of successfully parsed pages.
        """
        pages = self.db.get_by_status("fetched")
        logger.info(f"Found {len(pages)} unparsed pages")
        return self.parse_pages(pages, clean)

    def reparse_all(self, clean: bool = True) -> list[Page]:
        """Re-parse all pages that have HTML archives on disk.

        Overrides previous parse results. Useful when the conversion
        pipeline or cleaning rules change.

        Args:
            clean: Whether to apply markdown cleaning.

        Returns:
            List of successfully parsed pages.
        """
        pages = [p for p in self.db.get_all() if p.html_path]
        logger.info(f"Re-parsing {len(pages)} pages")
        return self.parse_pages(pages, clean)
