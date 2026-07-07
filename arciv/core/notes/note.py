"""Note reading: the index stage's file input."""

import re
from pathlib import Path

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
