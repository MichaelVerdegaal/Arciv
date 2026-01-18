"""HTML to Markdown conversion using trafilatura."""

from pathlib import Path

from loguru import logger
from trafilatura import extract


def html_to_markdown(
    html_content: str,
    include_tables: bool = True,
    include_links: bool = False,
    deduplicate: bool = False,
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
