"""HTML to Markdown conversion using trafilatura."""

import re
from pathlib import Path

from loguru import logger
from trafilatura import bare_extraction, extract

# Next.js __NEXT_DATA__ scripts can contain literal "</script>" inside JSON strings,
# causing the script to prematurely close and leak JSON into the document body.
# The lookahead ensures we capture until the real end.
NEXT_DATA_RE = re.compile(
    r"<script\s+id=[\"']__NEXT_DATA__[\"'][^>]*>.*?</script>(?=\s*<(?:script|/body|/html))",
    re.DOTALL | re.IGNORECASE,
)

WORD_RE = re.compile(r"\b\w+\b")

# Fallback regex for extracting <title> when trafilatura doesn't find it
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


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
    # Remove malformed __NEXT_DATA__ scripts before DOM parsing
    html_content = NEXT_DATA_RE.sub("", html_content)

    prune_xpath = None
    if strip_code:
        # Remove <pre> and <code> blocks to avoid extraction artifacts
        prune_xpath = ["//pre", "//code"]

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


def convert_html_file(
    html_path: Path,
    output_dir: Path,
    **kwargs,
) -> Path | None:
    """Convert an HTML file to Markdown and save to output directory.

    Args:
        html_path: Path to the HTML file to convert.
        output_dir: Directory where the Markdown file will be saved.
        **kwargs: Additional arguments passed to html_to_markdown.

    Returns:
        Path to the saved Markdown file, or None if conversion failed.
    """
    html_content = html_path.read_text(encoding="utf-8")
    md_content = html_to_markdown(html_content, **kwargs)

    if md_content is None:
        logger.warning(
            f"Failed to extract content from {html_path.name}. "
            f"Inspect the HTML at {html_path} to learn more."
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    md_filename = f"{html_path.stem}.md"
    md_path = output_dir / md_filename
    md_path.write_text(md_content, encoding="utf-8")

    return md_path
