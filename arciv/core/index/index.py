"""Index stage: extract links from files and register them in the database.

For every link found, a row is stored with the processed URL, the full
normalized path of the file it was found in, and the time it was indexed.
Pages are created in pending state; downloading them is the fetch stage's
job (see ``arciv.core.pipeline.fetch_pipeline``).
"""

from collections.abc import Iterable
from pathlib import Path

from loguru import logger

from arciv.core.clock import utc_now_iso
from arciv.core.db import PageDatabase
from arciv.core.notes import find_notes, read_note
from arciv.core.urls import domain_for_url, load_rules, process_url, slug_for_url
from arciv.settings import USER_RULES_PATH

from .links import extract_urls


def _page_entry(processed_url: str, original_url: str) -> tuple[str, str, str, str]:
    """Build the (url, original_url, domain, slug) tuple for ensure_pages."""
    domain = domain_for_url(processed_url)
    return (processed_url, original_url, domain, slug_for_url(processed_url, domain))


def _index_notes(
    db: PageDatabase,
    note_paths: Iterable[Path],
    source_name: str | None = None,
) -> list[str]:
    """Extract, normalize, and register the links of the given note files.

    Creates pending page rows for new URLs and replaces the link rows of
    each note file with the freshly extracted set, stamped with the
    current time. Returns all unique processed URLs found in the notes.
    source_name is the registered source the notes belong to, if any.

    An unreadable file (permissions, not UTF-8) is skipped with a warning
    so one stray binary in a vault never aborts the whole run; its
    previously indexed links are left untouched.
    """
    indexed_at = utc_now_iso()
    rules = load_rules(USER_RULES_PATH)
    file_paths: list[str] = []
    original_urls: dict[str, str] = {}
    link_entries: list[tuple[str, str, str | None, str]] = []
    seen_links: set[tuple[str, str]] = set()

    for note_path in note_paths:
        try:
            text = read_note(note_path)
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Skipping unreadable note {note_path}: {e}")
            continue
        file_path = str(note_path.resolve())
        file_paths.append(file_path)
        for link in extract_urls(text):
            processed, skip_reason = process_url(link, rules)
            if processed is None:
                logger.debug(f"Skipped {link} ({note_path.name}): {skip_reason}")
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

    logger.info(
        f"Indexed {len(original_urls)} unique URLs from {len(file_paths)} file(s)"
    )
    return list(original_urls)


def index_file(db: PageDatabase, file_path: Path) -> list[str]:
    """Index all links within a single note file (.md, .txt, or .rst)
    and return the unique processed URLs found."""
    return _index_notes(db, [file_path])


def index_directory(
    db: PageDatabase,
    dir_path: Path,
    source_name: str | None = None,
) -> list[str]:
    """Index all links of all note files within a directory (recursive)
    and return the unique processed URLs found. source_name is the
    registered source the directory belongs to, if any."""
    logger.info(f"Indexing notes in {dir_path}")
    return _index_notes(db, find_notes(dir_path), source_name=source_name)


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
    rules = load_rules(USER_RULES_PATH)
    registered: dict[str, str] = {}  # processed URL -> first original input
    for url in urls:
        processed, skip_reason = process_url(url, rules)
        if processed is None:
            logger.warning(f"Skipped {url}: {skip_reason}")
            continue
        registered.setdefault(processed, url)
    db.ensure_pages(
        [_page_entry(processed, original) for processed, original in registered.items()]
    )
    return list(registered)
