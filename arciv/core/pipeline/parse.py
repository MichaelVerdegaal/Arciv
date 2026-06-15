"""Parse stage: convert fetched raw content (HTML/PDF) into markdown.

Reads the raw files the fetch stage archived under ``saved/<slug>/``,
validates them (block pages, minimum length), converts them to markdown
via trafilatura (HTML) or liteparse (PDF), writes ``page.md`` next to the
raw file, and stamps the page row with ``parsed_at`` plus title/author/word
count. Rejected pages get a ``fail_reason`` (with ``parsed_at`` left empty)
so they don't pose as valid archive entries; their raw files stay on disk
for debugging.
"""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from arciv.core.parse import check_html, parse_html, pdf_to_text
from arciv.core.db import Page, PageDatabase
from arciv.core.fetch import is_raw_text_url
from arciv.settings import SAVED_DIR

DEFAULT_MIN_WORDS = 150


def _too_short_reason(words: int, raw_bytes: int, kind: str) -> str:
    """Build the rejection reason for below-threshold content.

    Pairs the extracted word count with the raw source size so a skip can be
    judged at a glance: a large raw size yielding few words points to a
    fetch/parse miss (paywall, JS-only page), while a small raw size is just
    genuinely short. ``kind`` labels the source (e.g. "html", "pdf").
    """
    if raw_bytes < 1024:
        size = f"{raw_bytes} B"
    else:
        size = f"{raw_bytes // 1024} KB"
    return f"too short ({words} words from {size} {kind})"


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
    page.parsed_at = datetime.now(timezone.utc).isoformat()
    db.upsert(page)
    return page


def _reject(db: PageDatabase, page: Page, reason: str) -> None:
    """Mark a page as rejected; the raw file stays on disk for debugging."""
    page.fail_reason = reason
    page.parsed_at = None
    db.upsert(page)
    logger.warning(f"Rejected {page.url}: {reason}")


def parse_page(
    db: PageDatabase,
    page: Page,
    saved_dir: Path = SAVED_DIR,
    min_words: int = DEFAULT_MIN_WORDS,
) -> Page | None:
    """Parse one fetched page (``fetched_at`` set, raw content on disk)
    from its raw file. Returns the updated Page on success, or None if the
    page was rejected (e.g. fewer than min_words words)."""
    slug_dir = saved_dir / page.slug
    md_path = slug_dir / "page.md"

    raw_name = "page.pdf" if page.content_type == "pdf" else "page.html"
    raw_path = slug_dir / raw_name
    if not raw_path.exists():
        _reject(db, page, f"raw file missing on disk ({raw_name})")
        return None

    if page.content_type == "pdf":
        return _parse_pdf(db, page, raw_path, md_path, min_words)
    return _parse_html(db, page, raw_path, md_path, min_words)


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
        _reject(db, page, _too_short_reason(word_count, pdf_path.stat().st_size, "pdf"))
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

    Raw text URLs (.md, .txt, .rst) skip validation and conversion; the
    fetched content is stored as markdown directly.
    """
    html = html_path.read_text(encoding="utf-8")

    raw_bytes = len(html.encode("utf-8"))

    if is_raw_text_url(page.url):
        word_count = len(html.split())
        if word_count < min_words:
            _reject(db, page, _too_short_reason(word_count, raw_bytes, "text"))
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
        _reject(db, page, _too_short_reason(gate_count, raw_bytes, "html"))
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
    """Parse every fetched page that doesn't have markdown yet and return
    how many parsed successfully.

    With reparse, every fetched page is re-parsed, including already-parsed
    and previously rejected ones. Useful after changing trafilatura settings
    or cleanup rules; no network traffic, everything is read from disk.
    """
    pages = db.get_fetched() if reparse else db.get_unparsed()
    count = 0
    for page in pages:
        if parse_page(db, page, saved_dir, min_words) is not None:
            count += 1
    logger.info(f"Parsed {count} pages")
    return count
