from pathlib import Path

from .note import NOTE_EXTENSIONS, Note
from .markdown_note import MarkdownNote

__all__ = [
    "NOTE_EXTENSIONS",
    "Note",
    "MarkdownNote",
    "load_note",
    "load_notes",
]


def load_note(note_path: str | Path) -> Note:
    """Create a note from a file, picking the class by extension.

    Lives here (not on Note) because Note can't reference its own
    subclasses without a circular import.

    Args:
        note_path: Path to the note file.

    Returns:
        A MarkdownNote for ``.md`` files, a plain Note otherwise.
    """
    note_path = Path(note_path)
    if note_path.suffix == ".md":
        return MarkdownNote(note_path)
    return Note(note_path)


def load_notes(note_dir: Path) -> list[Note]:
    """Load every supported note file in a directory, recursively.

    Args:
        note_dir: Directory to search.

    Returns:
        Note instances for every ``.md``/``.txt``/``.rst`` file found.
    """
    return [
        load_note(path)
        for path in sorted(note_dir.glob("**/*"))
        if path.is_file() and path.suffix in NOTE_EXTENSIONS
    ]
