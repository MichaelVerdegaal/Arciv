"""Single-note link extraction script for development and testing."""

import asyncio
from pathlib import Path

from loguru import logger

from clotho.notes import (
    Note,
    create_url_note,
    update_source_note_with_backlinks,
)
from clotho.scrape import batch_fetch_html, html_to_markdown, normalize_url
from clotho.topic import TopicExtractor
from config import CLEANED_DOCS_DIR, CONVERTED_DOCS_DIR, NOTES_PATH

# Directory for generated URL notes (sibling to the notes folder)
EXTRACTED_URLS_DIR = NOTES_PATH.parent / "extracted-urls"
NOTE_PATH = Path("C:/Users/Michael.Verdegaal/Documents/DevVault/Test note.md")


def process_single_note() -> None:
    """Process a single Obsidian note: extract links, fetch content, and create URL notes."""

    # Load the note
    note = Note._validate_path()
    logger.info(f"Processing note: {note.filename}")
    logger.debug(f"Note info: {note}")

    # Extract links from the note
    logger.info(f"Extracting links from note {note.filename}...")
    links = note.extract_links()
    logger.info(f"Found {len(links)} links")
    for link in links:
        logger.debug(f"  - {link}")

    if not links:
        logger.warning("No links found in note. Exiting.")
        return

    # Normalize URLs (e.g., GitHub file URLs → repo roots)
    normalized_links: list[str] = [normalize_url(link) for link in links]

    # Fetch HTML for each link
    saved_pages: dict[str, Path] = asyncio.run(batch_fetch_html(normalized_links))

    # Init topic extractor
    topic_extractor = TopicExtractor(top_n=20, max_ngram=3)
    logger.debug(
        f"Loaded topic extractor with {len(topic_extractor.stopwords)} stopwords"
    )

    # Track generated URL note filenames for backlinks
    url_note_filenames: list[str] = []

    # Track file paths for different processing stages
    scraped_paths: list[Path] = []
    converted_paths: list[Path] = []
    cleaned_paths: list[Path] = []

    # Load fetched HTML content
    for url, file_path in saved_pages.items():
        # Track scraped HTML file
        scraped_paths.append(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Convert HTML to Markdown
        md_filename = f"{file_path.stem}.md"
        md_page = html_to_markdown(html_content)

        if md_page is None:
            logger.warning(
                f"Failed to extract content from {url}. Inspect the HTML at {file_path} to learn more."
            )
            continue

        # Save converted markdown
        converted_save_path: Path = CONVERTED_DOCS_DIR / md_filename
        converted_save_path.write_text(md_page, encoding="utf-8")
        converted_paths.append(converted_save_path)

        # Extract keywords (preprocessing is handled internally)
        logger.info(f"\n\nExtracting keywords from {md_filename}...")
        keywords = topic_extractor.extract_top(md_page, n=20)
        for kw in keywords:
            logger.info(f"\t`{kw.text}`: {kw.score:.4f}")

        # Save cleaned markdown for debugging
        cleaned_save_path: Path = CLEANED_DOCS_DIR / md_filename
        cleaned_save_path.write_text(
            topic_extractor.preprocess(md_page), encoding="utf-8"
        )
        cleaned_paths.append(cleaned_save_path)

        # Create URL note in extracted-urls folder
        url_note_path = create_url_note(
            output_dir=EXTRACTED_URLS_DIR,
            filename=file_path.stem,
            original_url=url,
            keywords=[(kw.text, kw.score) for kw in keywords],
        )
        url_note_filenames.append(file_path.stem)
        logger.info(f"Created URL note: {url_note_path}")

    # Update source note with backlinks to all processed URL notes
    if url_note_filenames:
        update_source_note_with_backlinks(NOTES_PATH, url_note_filenames)
        logger.info(
            f"Updated source note {note.filename} with {len(url_note_filenames)} backlinks"
        )

    # Add sections with file paths for scraped, converted, and cleaned files
    if scraped_paths or converted_paths or cleaned_paths:
        with open(NOTES_PATH, "a", encoding="utf-8") as f:
            f.write("\n\n---\n\n")

            if scraped_paths:
                f.write("## Scraped HTML Files\n\n")
                for path in scraped_paths:
                    f.write(f"- `{path}`\n")
                f.write("\n")

            if converted_paths:
                f.write("## Converted Markdown Files\n\n")
                for path in converted_paths:
                    f.write(f"- `{path}`\n")
                f.write("\n")

            if cleaned_paths:
                f.write("## Cleaned Markdown Files\n\n")
                for path in cleaned_paths:
                    f.write(f"- `{path}`\n")

        logger.info(f"Added file path sections to source note {note.filename}")


if __name__ == "__main__":
    process_single_note()
