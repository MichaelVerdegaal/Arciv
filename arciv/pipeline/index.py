"""Index stage: extract links from files and register them in the database.

For every link found, a row is stored with the processed URL, the full
normalized path of the file it was found in, and the time it was indexed.
Pages are created in pending state; downloading them is the fetch stage's
job (see ``arciv.pipeline.fetch``).
"""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from arciv.db import PageDatabase
from arciv.notes import Note, load_note, load_notes
from arciv.scrape import process_url, registered_domain, slug_for_url, split_url


def _page_entry(processed_url: str, original_url: str) -> tuple[str, str, str, str]:
    """Build the (url, original_url, domain, slug) tuple for ensure_pages."""
    domain = registered_domain(processed_url) or split_url(processed_url)[0]
    return (processed_url, original_url, domain, slug_for_url(processed_url))


def _index_notes(
    db: PageDatabase,
    notes: list[Note],
    source_name: str | None = None,
) -> list[str]:
    """Extract, normalize, and register the links of the given notes.

    Creates pending page rows for new URLs and replaces the link rows of
    each note file with the freshly extracted set, stamped with the
    current time. Returns all unique processed URLs found in the notes.
    source_name is the registered source the notes belong to, if any.
    """
    indexed_at = datetime.now(timezone.utc).isoformat()
    file_paths: list[str] = []
    original_urls: dict[str, str] = {}
    link_entries: list[tuple[str, str, str | None, str]] = []
    seen_links: set[tuple[str, str]] = set()

    for note in notes:
        file_path = str(note.note_path.resolve())
        file_paths.append(file_path)
        for link in note.extract_urls():
            processed, _ = process_url(link)
            if processed is None:
                continue
            if (processed, file_path) in seen_links:
                continue
            seen_links.add((processed, file_path))
            link_entries.append((processed, file_path, source_name, indexed_at))
            if processed not in original_urls:
                original_urls[processed] = link

    db.ensure_pages(
        [_page_entry(url, original) for url, original in original_urls.items()]
    )
    db.replace_links_for_files(file_paths, link_entries)

    logger.info(f"Indexed {len(original_urls)} unique URLs from {len(notes)} file(s)")
    return list(original_urls)


def index_file(db: PageDatabase, file_path: Path) -> list[str]:
    """Index all links within a single note file (.md, .txt, or .rst)
    and return the unique processed URLs found."""
    return _index_notes(db, [load_note(file_path)])


def index_directory(
    db: PageDatabase,
    dir_path: Path,
    source_name: str | None = None,
) -> list[str]:
    """Index all links of all note files within a directory (recursive)
    and return the unique processed URLs found. source_name is the
    registered source the directory belongs to, if any."""
    notes = load_notes(dir_path)
    logger.info(f"Found {len(notes)} notes in {dir_path}")
    return _index_notes(db, notes, source_name=source_name)


def index_source(db: PageDatabase, name: str) -> list[str]:
    """Index a registered source by name and return the unique processed
    URLs found. Raises KeyError if no source with that name is registered."""
    source = db.get_source(name)
    if source is None:
        raise KeyError(f"No source named '{name}'")
    return index_directory(db, Path(source.path), source_name=source.name)


def index_all(db: PageDatabase) -> list[str]:
    """Index every registered source and return the unique processed URLs
    found across all of them."""
    urls: dict[str, None] = {}
    for source in db.list_sources():
        logger.info(f"Indexing source '{source.name}' ({source.path})")
        for url in index_directory(db, Path(source.path), source_name=source.name):
            urls[url] = None
    return list(urls)


def register_urls(db: PageDatabase, urls: list[str]) -> list[str]:
    """Register directly-provided URLs (no source file, so no link rows).

    Used by ``arciv get <URL>``, where the URL doesn't come from a file.
    Returns the processed URLs that were registered; skipped URLs excluded.
    """
    registered: dict[str, None] = {}
    for url in urls:
        processed, skip_reason = process_url(url)
        if processed is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            continue
        registered[processed] = None
        db.ensure_pages([_page_entry(processed, url)])
    return list(registered)
