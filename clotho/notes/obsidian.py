"""Obsidian-specific operations for note generation and linking.

This module provides functions to:
- Sanitize YAKE keywords into valid Obsidian tags
- Create markdown notes for extracted URLs
- Update source notes with backlinks to URL notes
"""

import re
from datetime import datetime, timezone
from pathlib import Path

# === Regex Patterns ===
# Characters allowed in Obsidian tags: alphanumeric, underscore, hyphen, forward slash
INVALID_TAG_CHARS_RE = re.compile(r"[^a-z0-9_\-/]")
CONSECUTIVE_HYPHENS_RE = re.compile(r"-{2,}")
URLS_SECTION_RE = re.compile(r"\n*# URLs\n.*", re.DOTALL)


def sanitize_tag(keyword: str) -> str:
    """Convert a YAKE keyword to a valid Obsidian tag.

    Valid Obsidian tag characters: alphanumeric, underscore (_), hyphen (-),
    forward slash (/).

    Sanitization rules:
    - Lowercase the keyword
    - Replace spaces with underscores
    - Preserve existing hyphens in valid positions
    - Remove any characters not in the allowed set
    - Collapse multiple consecutive hyphens into one
    - Strip leading/trailing hyphens

    Args:
        keyword: The raw YAKE keyword to sanitize.

    Returns:
        A valid Obsidian tag string (without the # prefix).
    """
    # Lowercase first
    tag = keyword.lower()

    # Replace spaces with underscores
    tag = tag.replace(" ", "_")

    # Remove invalid characters (keeps alphanumeric, underscore, hyphen, slash)
    tag = INVALID_TAG_CHARS_RE.sub("", tag)

    # Collapse multiple consecutive hyphens into one
    tag = CONSECUTIVE_HYPHENS_RE.sub("-", tag)

    # Strip leading/trailing hyphens
    tag = tag.strip("-")

    return tag


def create_url_note(
    output_dir: Path,
    filename: str,
    original_url: str,
    keywords: list[tuple[str, float]],
) -> Path:
    """Create an Obsidian-compatible markdown note for a URL.

    The note contains metadata (original URL, scrape date) and topic tags
    derived from YAKE keyword extraction.

    Args:
        output_dir: Directory where the note will be created.
        filename: Filename stem for the note (without .md extension).
        original_url: The original URL that was scraped.
        keywords: List of (keyword, score) tuples from YAKE extraction.
            Lower scores indicate better keywords.

    Returns:
        Path to the created note file.
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sort keywords by score (lower is better in YAKE) and take top N
    sorted_keywords = sorted(keywords, key=lambda x: x[1])

    # Generate tags from keywords
    tags = [sanitize_tag(kw) for kw, _ in sorted_keywords]
    # Filter out empty tags that might result from sanitization
    tags = [tag for tag in tags if tag]

    # Get current date in ISO format
    date_scraped = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build note content
    lines = [
        "# Info",
        f"original_url:: {original_url}",
        f"date_scraped:: {date_scraped}",
        "",
        "# Topics",
    ]
    lines.extend(f"#{tag}" for tag in tags)

    content = "\n".join(lines) + "\n"

    # Write the note
    note_path = output_dir / f"{filename}.md"
    note_path.write_text(content, encoding="utf-8")

    return note_path


def update_source_note_with_backlinks(
    note_path: Path,
    url_note_filenames: list[str],
) -> None:
    """Append or replace the URLs section in a source note with backlinks.

    If a `# URLs` section already exists in the note, it will be replaced.
    Otherwise, a new section is appended at the end of the note.

    Args:
        note_path: Path to the source note file to update.
        url_note_filenames: List of URL note filename stems (without .md extension)
            to link to.
    """
    if not url_note_filenames:
        return

    # Read existing content
    content = note_path.read_text(encoding="utf-8")

    # Build the URLs section (with leading blank line)
    backlinks = [f"- [[{filename}]]" for filename in url_note_filenames]
    urls_section = "\n\n# URLs\n" + "\n".join(backlinks) + "\n"

    # Check if URLs section already exists
    if URLS_SECTION_RE.search(content):
        # Replace existing section
        new_content = URLS_SECTION_RE.sub(urls_section, content)
    else:
        # Append new section (ensure one blank line before)
        content = content.rstrip()
        new_content = content + urls_section

    # Write updated content
    note_path.write_text(new_content, encoding="utf-8")
