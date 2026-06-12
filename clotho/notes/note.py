import re
from pathlib import Path

# Splits concatenated URLs on an embedded "https://" boundary.
# Only split when the boundary is not part of a query string value.
_CONCAT_SPLIT_RE = re.compile(r"(?<=[^\s?=&])(?=https?://)")

# File extensions treated as notes when indexing a directory
NOTE_EXTENSIONS = (".md", ".txt", ".rst")


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
        """Read the note file and store its text with YAML frontmatter stripped."""
        try:
            note_text = self.note_path.read_text(encoding="utf-8")
        except Exception as e:
            raise IOError(f"Note path {self.note_path} does not seem valid: {e}")

        # Remove traditional YAML frontmatter (--- at start, anything until next ---)
        frontmatter_pattern_re = r"^---\s*\n.*?\n---\s*\n"
        content = re.sub(frontmatter_pattern_re, "", note_text, flags=re.DOTALL)
        self.text = content.strip()

    @staticmethod
    def _validate_path(note_path: str | Path) -> Path:
        """Validate that a note path exists and normalize it to a Path.

        Args:
            note_path: Path to the note file

        Returns:
            The note path as a pathlib Path

        Raises:
            FileNotFoundError: If the path does not exist.
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

        Concatenated URLs (multiple ``https://`` in one match) are split.
        Trailing parens are only stripped when unbalanced (more ``)`` than
        ``(``) to preserve URLs like ``Leakage_(machine_learning)``.

        Returns:
            List of extracted URLs
        """
        raw_urls: list[str] = []

        # First pass: extract URLs from markdown links [text](url)
        # Balanced-paren group tried first so (machine_learning) stays intact
        _MD_LINK_RE = (
            r"\[(?:[^\[\]]|\[[^\]]*\])*\]\((https?://(?:\([^\s\)]*\)|[^\s\)])+)\)"
        )
        for match in re.finditer(_MD_LINK_RE, self.text):
            raw_urls.append(match.group(1))

        # Second pass: bare URLs not inside markdown link parens
        _BARE_URL_RE = r"(?<!\]\()https?://[^\s<>\[\]\"]+"
        for match in re.finditer(_BARE_URL_RE, self.text):
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
