import re
from pathlib import Path
from typing import Self


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

        # Read file text content
        self.text: str = ""
        self._read_content()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.filename}{self.extension})"

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

    @classmethod
    def get_note_files(cls, note_dir: Path) -> list[Self]:
        """Get all markdown files in the given directory.

        Args:
            note_dir: Directory to search for markdown files

        Returns:
            List of paths to markdown files found recursively
        """
        return [cls(note_path) for note_path in note_dir.glob("**/*.md")]

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

    def extract_urls(self) -> list[str]:
        """Extract all URLs from the note content.

        Handles both markdown links ``[text](url)`` and bare URLs. Markdown
        links are matched first to avoid capturing trailing junk after the
        closing paren (e.g. ``[link](https://example.com)seasonalities``).

        Returns:
            List of extracted URLs
        """
        urls: list[str] = []

        # First pass: extract URLs from markdown links [text](url)
        _MD_LINK_RE = r"\[(?:[^\[\]]|\[[^\]]*\])*\]\((https?://[^\s\)]+)\)"
        for match in re.finditer(_MD_LINK_RE, self.text):
            urls.append(match.group(1))

        # Second pass: bare URLs not inside markdown link parens
        _BARE_URL_RE = r"(?<!\]\()https?://[^\s<>\[\]\"\)]+"
        for match in re.finditer(_BARE_URL_RE, self.text):
            url = match.group(0).rstrip(".,;:!?'")
            urls.append(url)

        return urls
