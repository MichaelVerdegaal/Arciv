"""Note reading and URL extraction: the index stage's input."""

import re
from pathlib import Path

# Splits concatenated URLs on an embedded "https://" boundary.
# Only split when the boundary is not part of a query string value.
_CONCAT_SPLIT_RE = re.compile(r"(?<=[^\s?=&])(?=https?://)")

# Markdown link ``[text](url)``. The balanced-paren group in the URL keeps
# forms like ``(machine_learning)`` intact instead of stopping at the first ")".
_MD_LINK_RE = re.compile(
    r"\[(?:[^\[\]]|\[[^\]]*\])*\]\((https?://(?:\([^\s\)]*\)|[^\s\)])+)\)"
)

# Bare URL not already inside a markdown link's parens.
_BARE_URL_RE = re.compile(r"(?<!\]\()https?://[^\s<>\[\]\"]+")

# Traditional YAML frontmatter: --- at the start, anything until the next ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)

# File extensions treated as notes when indexing a directory
NOTE_EXTENSIONS = frozenset({".md", ".txt", ".rst"})


def read_note(note_path: Path) -> str:
    """Read a note file's text with YAML frontmatter stripped.

    Args:
        note_path: Path to the note file.

    Returns:
        The note's text content, frontmatter removed, surrounding
        whitespace trimmed.

    Raises:
        OSError: If the file is missing, unreadable, or a directory.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    text = note_path.read_text(encoding="utf-8")
    return _FRONTMATTER_RE.sub("", text).strip()


def find_notes(note_dir: Path) -> list[Path]:
    """Find every note file under a directory, recursively, sorted by path.

    Args:
        note_dir: Directory to search.

    Returns:
        The paths of all ``.md``/``.txt``/``.rst`` files found.
    """
    # Filter by suffix before sorting so only note paths are materialized,
    # not every image/attachment in the vault.
    return sorted(
        path
        for path in note_dir.rglob("*")
        if path.suffix in NOTE_EXTENSIONS and path.is_file()
    )


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from note text.

    Handles both markdown links ``[text](url)`` and bare URLs. Markdown
    links are matched first to avoid capturing trailing junk after the
    closing paren (e.g. ``[link](https://example.com)seasonalities``).

    Concatenated URLs (multiple ``https://`` in one match) are split.
    Trailing parens are only stripped when unbalanced (more ``)`` than
    ``(``) to preserve URLs like ``Leakage_(machine_learning)``.

    Args:
        text: The note text to scan.

    Returns:
        List of extracted URLs.
    """
    raw_urls: list[str] = []

    # First pass: extract URLs from markdown links [text](url), tried first
    # so trailing junk after the closing paren isn't captured.
    for match in _MD_LINK_RE.finditer(text):
        raw_urls.append(match.group(1))

    # Second pass: bare URLs not inside markdown link parens
    for match in _BARE_URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?'")
        # Strip trailing parens only when unbalanced
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        raw_urls.append(url)

    # Split concatenated URLs (e.g. "...7405d51cd839https://medium.com/...")
    urls: list[str] = []
    for url in raw_urls:
        parts = _CONCAT_SPLIT_RE.split(url)
        urls.extend(p for p in parts if p)

    return urls
