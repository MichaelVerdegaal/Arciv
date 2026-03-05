"""Test script for scraping individual URLs."""

from loguru import logger

from clotho.db import Page, PageDatabase
from clotho.parse import Parser
from clotho.scrape import Scraper
from config import DB_PATH, HTML_DIR, configure_logger

configure_logger()

# Test URLs
test_urls: list[str] = [
    "https://learn.microsoft.com/en-us/media/open-graph-image.png",
    "https://learn.microsoft.com/en-us/azure/ai-services/personalizer",
    "https://learn.microsoft.com/en-us/azure/ai-services/anomaly-detector/",
]

# Scrape and parse each URL individually (sync, for debugging)
with PageDatabase(DB_PATH) as db:
    scraper = Scraper(db, html_dir=HTML_DIR)
    parser = Parser(db, html_dir=HTML_DIR)
    for url in test_urls:
        page: Page | None = scraper.scrape(url, refetch=True)
        if page:
            page = parser.parse_page(page)
        if page:
            logger.info(f"{page.title}: {page.md_content[:500]}...\n\n")
