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
from config import CONVERTED_DOCS_DIR, NOTES_PATH, SCRAPED_PAGES_DIR

CATEGORY = "DAILY"
NOTE_SELECTION = ["2025-12-09", "2025-12-22"]

# Directory for generated URL notes (sibling to the notes folder)
EXTRACTED_URLS_DIR = NOTES_PATH.parent / "extracted-urls"


if __name__ == "__main__":
    # Load notes
    note_files = Note.get_note_files(NOTES_PATH)
    logger.info(f"Retrieved {len(note_files)} notes...")

    # Get metadata for each note
    notes_processed: list[Note] = [Note._validate_path() for note in note_files]
    logger.info(f"Retrieved metadata for {len(notes_processed)} notes...")

    # Filter to notes in selection
    # selections: list[NoteInfo] = [
    #     note for note in notes_processed if note.filename in NOTE_SELECTION
    # ]
    selections = notes_processed
    for note_selection in selections:
        logger.debug(f"Note info: {note_selection}")

        # Extract links from the note
        logger.info(f"Extracting links from note {note_selection.filename}...")
        links = note_selection.extract_links()
        logger.debug(links)

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

        # Load fetched HTML content
        for url, file_path in saved_pages.items():
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

            # Extract keywords (preprocessing is handled internally)
            logger.info(f"\n\nExtracting keywords from {md_filename}...")
            keywords = topic_extractor.extract_top(md_page, n=10)
            for kw in keywords:
                logger.info(f"\t`{kw.text}`: {kw.score:.4f}")

            # Save cleaned markdown for debugging
            cleaned_save_path: Path = SCRAPED_PAGES_DIR / md_filename
            cleaned_save_path.write_text(
                topic_extractor.preprocess(md_page), encoding="utf-8"
            )

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
            source_note_path = NOTES_PATH / f"{note_selection.filename}.md"
            update_source_note_with_backlinks(source_note_path, url_note_filenames)
            logger.info(
                f"Updated source note {note_selection.filename} with {len(url_note_filenames)} backlinks"
            )
