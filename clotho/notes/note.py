import re
from datetime import datetime, timezone
from pathlib import Path


class Note:
    """Base class for a 'Note' object, containing metadata and text content."""

    def __init__(
        self,
        note_path: str | Path,
    ) -> None:
        # Validate provided filepath
        self.note_path: Path = self._validate_path(note_path)

        # Set attributes
        self.filename: str = self.note_path.stem
        self.extension: str = self.note_path.suffix
        self.creation_date, self.modification_date = self._file_dates(self.note_path)

        # Read file text content
        self.text: str = ""
        self._read_content()

    def __repr__(self) -> str:
        return f"Note({self.filename}{self.extension})"

    def _read_content(self) -> None:
        """Reads text content and strips YAML frontmatter.

        Returns:
            Text content from note file
        """
        try:
            note_text = self.note_path.read_text(encoding="utf-8")
        except Exception as e:
            raise IOError(f"Note path {self.note_path} does not seem valid: {e}")

        # Remove traditional YAML frontmatter (--- at start, anything until next ---)
        frontmatter_pattern_re = r"^---\s*\n.*?\n---\s*\n"
        content = re.sub(frontmatter_pattern_re, "", note_text, flags=re.DOTALL)
        self.text = content.strip()

    @staticmethod
    def _file_dates(filepath: Path) -> tuple[str, str]:
        """Get the file creation and modification dates as ISO format strings.

        Args:
            filepath: Path to the file

        Returns:
            Tuple of (creation_date_iso, modification_date_iso)
        """
        tz = timezone.utc
        created_date = datetime.fromtimestamp(filepath.stat().st_mtime, tz=tz)
        modified_date = datetime.fromtimestamp(filepath.stat().st_mtime, tz=tz)
        return created_date.isoformat(), modified_date.isoformat()

    @classmethod
    def get_note_files(cls, note_dir: Path) -> list[Path]:
        """Get all markdown files in the given directory.

        Args:
            note_dir: Directory to search for markdown files

        Returns:
            List of paths to markdown files found recursively
        """
        return list(note_dir.glob("**/*.md"))

    @staticmethod
    def _validate_path(note_path: str | Path) -> Path:
        """Create a Note instance from a file path.

        The creation and modification dates are returned as RFC3339 strings.

        Args:
            note_path: Path to the note file

        Returns:
            Note instance with filename, content, and dates
        """
        # Convert to Pathlib Path
        if isinstance(note_path, str):
            try:
                note_path = Path(note_path)
            except Exception as e:
                raise ValueError(f"Filepath {note_path} does not seem valid: {e}")

        # Verify path exists
        if not note_path.exists():
            raise FileNotFoundError(f"Note path {note_path} does not exist")

        # TODO: Verify note not empty (filesize > 0.0)

        return note_path

    def extract_links(self) -> list[str]:
        """Extract all URLs from the note content.

        Returns:
            List of extracted URLs
        """
        link_pattern_re = r"https?://[^\s<>\[\]\"]+"
        cleaned = []

        for url in re.findall(link_pattern_re, self.text):
            url = url.rstrip(".,;:!?'")
            while url.endswith(")") and url.count(")") > url.count("("):
                url = url[:-1]
            cleaned.append(url)

        return cleaned
