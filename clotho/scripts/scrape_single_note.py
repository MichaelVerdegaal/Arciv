from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import Scraper

# Collect all links from notes
all_links: list[str] = [
    "https://learn.microsoft.com/en-us/media/open-graph-image.png",
    "https://learn.microsoft.com/en-us/azure/ai-services/personalizer",
    "https://learn.microsoft.com/en-us/azure/ai-services/anomaly-detector/",
]

# Scrape all links concurrently
scraper: Scraper = Scraper()
for url in all_links:
    note: MarkdownNote | None = scraper.scrape(url, refetch=True, reclean=True)
    if note:
        logger.info(f"{note.filename}: {note.text[:500]}...\n\n")
