"""Export all database entries to markdown files with YAML frontmatter."""

from pathlib import Path

from loguru import logger

from clotho.db import PageDatabase
from clotho.db.models import Page
from config import DATA_DIR, DB_PATH, HTML_DIR, configure_logger

MARKDOWN_DIR = DATA_DIR / "markdown"


def _md_path_from_html_path(html_path: str) -> Path:
    """Derive the markdown output path from an html_path.

    Converts e.g. ``github.com/github.com-bb3a2481.html.br``
    to ``data/markdown/github.com/github.com-bb3a2481.md``.

    Args:
        html_path: Relative html subpath stored in the database.

    Returns:
        Absolute path for the markdown file.
    """
    # Strip .html.br (or just .html) suffix and replace with .md
    stem = html_path
    if stem.endswith(".html.br"):
        stem = stem[: -len(".html.br")]
    elif stem.endswith(".html"):
        stem = stem[: -len(".html")]
    return MARKDOWN_DIR / f"{stem}.md"


def _yaml_escape(value: str) -> str:
    """Wrap a string in quotes if it contains YAML-special characters.

    Args:
        value: The string to escape.

    Returns:
        Escaped string safe for YAML frontmatter.
    """
    if any(ch in value for ch in (":", "#", "'", '"', "[", "]", "{", "}", "\n")):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _build_frontmatter(page: Page) -> str:
    """Build YAML frontmatter block for a page.

    Args:
        page: The Page to generate frontmatter for.

    Returns:
        Complete YAML frontmatter string including ``---`` delimiters.
    """
    html_abs_path = str(HTML_DIR / page.html_path) if page.html_path else ""

    fields: list[tuple[str, str | int | None]] = [
        ("url", page.url),
        ("original_url", page.original_url),
        ("domain", page.domain),
        ("status", page.status),
        ("fail_reason", page.fail_reason),
        ("html_path", html_abs_path),
        ("title", page.title),
        ("author", page.author),
        ("word_count", page.word_count),
        ("scraped_at", page.scraped_at),
    ]

    lines = ["---"]
    for key, value in fields:
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml_escape(value)}")
    lines.append("---")

    return "\n".join(lines)


def export_page(page: Page) -> Path | None:
    """Write a single page to a markdown file.

    Args:
        page: The database Page to export.

    Returns:
        The path written, or None if the page has no html_path.
    """
    if not page.html_path:
        logger.debug(f"Skipping {page.url} — no html_path")
        return None

    md_path = _md_path_from_html_path(page.html_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = _build_frontmatter(page)

    if page.status == "scraped" and page.md_content:
        content = f"{frontmatter}\n\n{page.md_content}\n"
    else:
        content = f"{frontmatter}\n"

    md_path.write_text(content, encoding="utf-8")
    return md_path


def main() -> None:
    """Export all database pages to markdown files."""
    configure_logger()

    with PageDatabase(DB_PATH) as db:
        pages = db.get_all()

    logger.info(f"Exporting {len(pages)} pages to {MARKDOWN_DIR}")

    written = 0
    skipped = 0
    for page in pages:
        result = export_page(page)
        if result:
            written += 1
        else:
            skipped += 1

    logger.info(f"Done: {written} written, {skipped} skipped (no html_path)")


if __name__ == "__main__":
    main()
