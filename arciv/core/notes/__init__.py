from pathlib import Path

from .note import NOTE_EXTENSIONS, Note

__all__ = [
    "NOTE_EXTENSIONS",
    "Note",
    "load_note",
    "load_notes",
]


def load_note(note_path: str | Path) -> Note:
    """Create a Note from a file.

    Args:
        note_path: Path to the note file.

    Returns:
        A Note instance.
    """
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
