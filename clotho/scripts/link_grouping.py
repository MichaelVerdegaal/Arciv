"""
Work in progress script for testing and development purposes.
"""

from pathlib import Path

import tldextract
from loguru import logger

from clotho.notes import MarkdownNote
from config import NOTES_PATH, configure_logger
from clotho.scrape import hash_filename, process_url
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

# Write notes to vault (3-level hierarchy: urls.md -> domain notes -> page notes)
VAULT_LINKS_DIR = Path(r"C:\Users\Michael\Documents\DevVault\links")
VAULT_DOMAINS_DIR = VAULT_LINKS_DIR / "domains"
VAULT_PAGES_DIR = VAULT_LINKS_DIR / "pages"
VAULT_DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
VAULT_PAGES_DIR.mkdir(parents=True, exist_ok=True)

domain_backlinks: list[str] = []

for domain, urls in domain_groups.items():
    page_backlinks: list[str] = []

    for url in urls:
        stem = hash_filename(url).removesuffix(".md")
        page_backlinks.append(f"- [[{stem}|{url}]]")

        # Create page note
        page_note_path = VAULT_PAGES_DIR / hash_filename(url)
        page_note_content = "\n".join([
            f"domain: [[{domain}]]",
            f"url: {url}"
            "",
        ])
        page_note_path.write_text(page_note_content, encoding="utf-8")

    # Create domain note with backlinks to urls index and all page notes
    domain_note_path = VAULT_DOMAINS_DIR / f"{domain}.md"
    domain_note_content = "\n".join([
        f"# {domain}",
        "",
        *page_backlinks,
        "",
    ])
    domain_note_path.write_text(domain_note_content, encoding="utf-8")
    logger.debug(f"Created domain note {domain}.md with {len(page_backlinks)} page notes")

    domain_backlinks.append(f"- [[{domain}]]")

# Create top-level urls index note
urls_note_path = VAULT_LINKS_DIR / "urls.md"
urls_note_content = "\n".join([
    "# URLs",
    "",
    *sorted(domain_backlinks),
    "",
])
urls_note_path.write_text(urls_note_content, encoding="utf-8")
logger.debug(f"Created urls.md with {len(domain_backlinks)} domain backlinks")

logger.info(
    f"Wrote {sum(len(u) for u in domain_groups.values())} page notes, "
    f"{len(domain_groups)} domain notes, and urls.md to {VAULT_LINKS_DIR}"
)
