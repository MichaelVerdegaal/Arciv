"""HTML to Markdown conversion using trafilatura."""

import re
from dataclasses import dataclass

from trafilatura import bare_extraction, extract

from .clean_markdown import clean_markdown
from .html_fixes import PRUNE_XPATHS, fix_html

WORD_RE = re.compile(r"\b\w+\b")

# Fallback regex for extracting <title> when trafilatura doesn't find it
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


@dataclass
class ConversionResult:
    """Result of HTML-to-markdown conversion.

    Attributes:
        md_content: Extracted markdown content (code blocks stripped).
        word_count: Number of words in the stored markdown content.
        full_word_count: Number of words in a code-inclusive extraction. Used
            for the length gate so code-heavy pages (e.g. GitHub READMEs) with
            real prose aren't rejected just because their code was stripped.
        title: HTML page title, if extractable.
        author: Page author, if extractable.
    """

    md_content: str
    word_count: int
    full_word_count: int
    title: str | None = None
    author: str | None = None


def count_words(text: str) -> int:
    """Count the number of words in text using regex.

    Args:
        text: The text to count words in.

    Returns:
        The number of words found.
    """
    words = WORD_RE.findall(text)
    return len(words)


def html_to_markdown(
    html_content: str,
    include_tables: bool = True,
    include_links: bool = False,
    deduplicate: bool = True,
    favor_precision: bool = True,
    strip_code: bool = True,
) -> str | None:
    """Convert HTML content to Markdown using trafilatura.

    Args:
        html_content: Raw HTML string to convert.
        include_tables: Whether to preserve tables in output.
        include_links: Whether to preserve hyperlinks in output.
        deduplicate: Whether to remove duplicate content.
        favor_precision: Whether to favor precision over recall in extraction.
        strip_code: If true, removes <pre> and <code> elements before extraction.

    Returns:
        Extracted Markdown content, or None if extraction failed.
    """
    # Site-specific cleanup: broken markup and extraction-hostile chrome
    # (see html_fixes.py for the rules and why each exists)
    html_content = fix_html(html_content)

    prune_xpath = [*PRUNE_XPATHS]
    if strip_code:
        # Remove <pre> and <code> blocks to avoid extraction artifacts
        prune_xpath += ["//pre", "//code"]

    return extract(
        html_content,
        output_format="markdown",
        include_tables=include_tables,
        include_links=include_links,
        deduplicate=deduplicate,
        favor_precision=favor_precision,
        prune_xpath=prune_xpath,
    )


def extract_metadata(html_content: str) -> tuple[str | None, str | None]:
    """Extract title and author from HTML content.

    Uses trafilatura's bare_extraction for metadata parsing.

    Args:
        html_content: Raw HTML string.

    Returns:
        Tuple of (title, author). Either may be None if not found.
    """
    try:
        result = bare_extraction(html_content)
    except Exception:
        return _title_from_tag(html_content), None

    if not result:
        return _title_from_tag(html_content), None

    # trafilatura 2.x returns a Document object with attributes
    title = getattr(result, "title", None)
    author = getattr(result, "author", None)

    # Fall back to <title> tag if trafilatura didn't extract one
    if not title:
        title = _title_from_tag(html_content)

    return title or None, author or None


def _title_from_tag(html_content: str) -> str | None:
    """Extract title from the HTML <title> tag as a fallback.

    Args:
        html_content: Raw HTML string.

    Returns:
        The title text, or None if no <title> tag found.
    """
    match = TITLE_TAG_RE.search(html_content)
    if match:
        title = match.group(1).strip()
        return title if title else None
    return None


def parse_html(html_content: str, clean: bool = True) -> ConversionResult | None:
    """Convert HTML to markdown and extract metadata.

    This is the main entry point for parsing scraped HTML into structured
    markdown content with metadata.

    Args:
        html_content: Raw HTML string.
        clean: Whether to apply markdown cleaning.

    Returns:
        Conversion result with markdown content, word count, and metadata.
        None if extraction failed entirely.
    """
    md_content = html_to_markdown(html_content)
    if md_content is None:
        return None

    # The length gate runs on a code-inclusive extraction so that code-heavy
    # pages with real prose aren't rejected as "too short" just because their
    # <pre>/<code> blocks were stripped from the stored markdown.
    full_md = html_to_markdown(html_content, strip_code=False)
    full_word_count = count_words(full_md) if full_md else 0

    if clean:
        md_content = clean_markdown(md_content)

    title, author = extract_metadata(html_content)
    return ConversionResult(
        md_content=md_content,
        word_count=count_words(md_content),
        full_word_count=full_word_count,
        title=title,
        author=author,
    )
