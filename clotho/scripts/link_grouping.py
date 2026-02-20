"""
Work in progress script for testing and development purposes.
"""

import tldextract
from loguru import logger

from clotho.notes import MarkdownNote
from config import NOTES_PATH, configure_logger
from clotho.scrape import process_url
configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Collect all links from notes
all_links: list[str] = []
for note in note_files:
    extracted_links = note.extract_links()
    if extracted_links:
        logger.debug(
            f"Extracted {len(extracted_links)} links from {note.note_path.name}"
        )
        all_links.extend(extracted_links)

logger.info(f"Collected {len(all_links)} total links")


# Remove duplicates
all_links = list(set(all_links))
logger.info(f"{len(all_links)} unique links after removing duplicates")

# Apply url rules
filtered_links: list[str] = []
for url in all_links:
    processed_url, skip_reason = process_url(url)
    if processed_url is None:
        logger.warning(f"Skipped {url}: {skip_reason}")
    else:
        filtered_links.append(processed_url)

logger.info(f"{len(filtered_links)} links after applying URL rules")

# Group filtered links by registered domain using tldextract
domain_groups: dict[str, list[str]] = {}
for url in filtered_links:
    top_domain = tldextract.extract(url).top_domain_under_public_suffix
    if not top_domain:
        logger.warning(f"Skipped {url}: no valid public suffix")
        continue
    domain_groups.setdefault(top_domain, []).append(url)

logger.info(f"Found {len(domain_groups)} domain groups")

# Log each group sorted by URL count descending
for domain, urls in sorted(domain_groups.items(), key=lambda item: len(item[1]), reverse=True):
    logger.info(f"  {domain}: {len(urls)} URLs")
    f.write(f"{domain}: {len(urls)} URLs\n")
