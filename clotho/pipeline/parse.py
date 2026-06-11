"""Parse stage: convert fetched raw content (HTML/PDF) into markdown.

Reads the raw files the fetch stage archived under ``saved/<slug>/``,
validates them (block pages, minimum length), converts them to markdown
via trafilatura (HTML) or liteparse (PDF), writes ``page.md`` next to the
raw file, and fills in title/author/word count on the page row. Rejected
pages get ``fetched=0`` plus a ``fail_reason`` so they don't pose as valid
archive entries; their raw files stay on disk for debugging.
"""

from pathlib import Path

from loguru import logger

from clotho.settings import SAVED_DIR
from clotho.convert import check_html, parse_html, pdf_to_text
from clotho.db import Page, PageDatabase
from clotho.scrape import is_raw_text_url

DEFAULT_MIN_WORDS = 150


def _accept(
    db: PageDatabase,
    page: Page,
    md_path: Path,
    markdown: str,
    title: str | None,
    author: str | None,
    word_count: int,
) -> Page:
    """Write the markdown file and record the parse result on the page row."""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    page.title = title
    page.author = author
    page.word_count = word_count
    page.fail_reason = None
    db.upsert(page)
    return page


def _reject(db: PageDatabase, page: Page, reason: str) -> None:
    """Mark a page as rejected; the raw file stays on disk for debugging."""
    page.fetched = False
    page.fail_reason = reason
    db.upsert(page)
    logger.warning(f"Rejected {page.url}: {reason}")


def parse_page(
    db: PageDatabase,
    page: Page,
    saved_dir: Path = SAVED_DIR,
    min_words: int = DEFAULT_MIN_WORDS,
) -> Page | None:
    """Parse one fetched page from its raw file on disk.

    Args:
        db: Page database.
        page: A page with ``fetched=True`` and raw content on disk.
        saved_dir: Root directory for archived page folders.
        min_words: Minimum word count for a page to be accepted.

    Returns:
        The updated Page on success, None if the page was rejected.
    """
    slug_dir = saved_dir / page.slug
    md_path = slug_dir / "page.md"
    pdf_path = slug_dir / "page.pdf"
    html_path = slug_dir / "page.html"

    if pdf_path.exists():
        return _parse_pdf(db, page, pdf_path, md_path, min_words)
    if html_path.exists():
        return _parse_html(db, page, html_path, md_path, min_words)

    _reject(db, page, "no raw content on disk")
    return None


def _parse_pdf(
    db: PageDatabase,
    page: Page,
    pdf_path: Path,
    md_path: Path,
    min_words: int,
) -> Page | None:
    """Convert an archived PDF to text and record the result."""
    try:
        text = pdf_to_text(pdf_path.read_bytes())
    except Exception as e:
        _reject(db, page, f"PDF parse error: {e}")
        return None

    word_count = len(text.split())
    if word_count < min_words:
        _reject(db, page, f"too short ({word_count} words)")
        return None

    result = _accept(db, page, md_path, text, None, None, word_count)
    logger.info(f"Parsed {page.url} (PDF, {word_count} words)")
    return result


def _parse_html(
    db: PageDatabase,
    page: Page,
    html_path: Path,
    md_path: Path,
    min_words: int,
) -> Page | None:
    """Validate archived HTML, convert it to markdown, and record the result.

    Raw text URLs (.md, .txt, .rst) skip validation and conversion — the
    fetched content is stored as markdown directly.
    """
    html = html_path.read_text(encoding="utf-8")

    if is_raw_text_url(page.url):
        word_count = len(html.split())
        if word_count < min_words:
            _reject(db, page, f"too short ({word_count} words)")
            return None
        result = _accept(db, page, md_path, html, None, None, word_count)
        logger.info(f"Parsed {page.url} (raw text, {word_count} words)")
        return result

    block_reason = check_html(html)
    if block_reason:
        _reject(db, page, block_reason)
        return None

    conversion = parse_html(html, clean=True)
    if conversion is None:
        _reject(db, page, "extraction failed")
        return None

    # Gate on the code-inclusive word count (max of stored vs. full) so
    # code-heavy pages with real prose aren't rejected as "too short".
    gate_count = max(conversion.word_count, conversion.full_word_count)
    if gate_count < min_words:
        _reject(db, page, f"too short ({gate_count} words)")
        return None

    result = _accept(
        db,
        page,
        md_path,
        conversion.md_content,
        conversion.title,
        conversion.author,
        conversion.word_count,
    )
    logger.info(f"Parsed {page.url} ({conversion.word_count} words)")
    return result


def parse_pending(
    db: PageDatabase,
    saved_dir: Path = SAVED_DIR,
    reparse: bool = False,
    min_words: int = DEFAULT_MIN_WORDS,
) -> int:
    """Parse every fetched page that doesn't have markdown yet.

    Args:
        db: Page database.
        saved_dir: Root directory for archived page folders.
        reparse: Re-parse every fetched page, even ones with markdown.
            Useful after changing trafilatura settings or cleanup rules —
            no network traffic, everything is read from disk.
        min_words: Minimum word count for a page to be accepted.

    Returns:
        Number of pages successfully parsed.
    """
    count = 0
    for page in db.get_all():
        if not page.fetched:
            continue
        if (saved_dir / page.slug / "page.md").exists() and not reparse:
            continue
        if parse_page(db, page, saved_dir, min_words) is not None:
            count += 1
    logger.info(f"Parsed {count} pages")
    return count
