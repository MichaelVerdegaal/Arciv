"""Test script for scraping individual URLs."""

from loguru import logger

from clotho.db import Page, PageDatabase
from clotho.scrape import Scraper
from config import DB_PATH, configure_logger

configure_logger()

# Test URLs
test_urls: list[str] = [
    "https://learn.microsoft.com/en-us/media/open-graph-image.png",
    "https://learn.microsoft.com/en-us/azure/ai-services/personalizer",
    "https://learn.microsoft.com/en-us/azure/ai-services/anomaly-detector/",
]

# Scrape each URL individually (sync, for debugging)
with PageDatabase(DB_PATH) as db:
    scraper = Scraper(db)
    for url in test_urls:
        page: Page | None = scraper.scrape(url, refetch=True, reclean=True)
        if page:
            logger.info(f"{page.title}: {page.md_content[:500]}...\n\n")
