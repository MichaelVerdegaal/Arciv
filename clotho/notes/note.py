import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Self

LINK_PATTERN_RE = r"https?://[^\s<>\[\]\"]+"
FRONTMATTER_PATTERN_RE = r"^---\s*\n.*?\n---\s*\n"
TIMESTAMP_PATTERN_RE = r"^\d{8}\s+\d{4}\s*\n\s*Status:\s*#\w+\s*\n"
MARKDOWN_H1_PATTERN_RE = r"^#\s+.+$"

DEFAULT_SKIP_PREFIXES = (
    "http://localhost",
    "https://localhost",
    "http://127.0.0.1",
    "https://127.0.0.1",
    "https://app.fabric.microsoft.com/",
    "https://app.powerbi.com/",
)


class Note:
    """Metadata and content for a single note file."""

    def __init__(
        self,
        filename: str,
        extension: str,
        content: str,
        creation_date: str,
        modification_date: str,
    ) -> None:
        self.filename = filename
        self.extension = extension
        self.content = content
        self.creation_date = creation_date
        self.modification_date = modification_date

    def __repr__(self) -> str:
        return (
            f"Note(filename={self.filename}, "
            f"extension={self.extension}, "
            f"creation_date={self.creation_date[:10]}, "
            f"modification_date={self.modification_date[:10]})"
        )

    @staticmethod
    def _process_note_content(content: str) -> str:
        """Remove metadata headers and content before first H1 header.

        Handles both traditional YAML frontmatter (---...---) and
        timestamp/status patterns found in Obsidian daily notes.

        Args:
            content: Raw note content with potential frontmatter

        Returns:
            Cleaned content starting from first H1 header
        """
        # Remove traditional YAML frontmatter (--- at start, anything until next ---)
        content = re.sub(FRONTMATTER_PATTERN_RE, "", content, flags=re.DOTALL)

        # Remove timestamp pattern (e.g., "20251121 1011") and Status line
        # This handles lines like "20241101 1111" followed by "Status: #daily"
        content = re.sub(TIMESTAMP_PATTERN_RE, "", content, flags=re.MULTILINE)

        # Find first H1 header (# Heading)
        h1_match = re.search(MARKDOWN_H1_PATTERN_RE, content, flags=re.MULTILINE)

        if h1_match:
            # Return content starting from first H1, stripped of leading/trailing whitespace
            return content[h1_match.start() :].strip()

        # If no H1 found, return cleaned content
        return content.strip()

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

    @classmethod
    def from_path(cls, note: Path) -> Self:
        """Create a Note instance from a file path.

        The creation and modification dates are returned as RFC3339 strings.

        Args:
            note: Path to the note file

        Returns:
            Note instance with filename, content, and dates
        """
        filename = note.stem
        extension = note.suffix
        creation_date, modification_date = cls._file_dates(note)
        note_content = note.read_text(encoding="utf-8")
        note_content_processed = cls._process_note_content(note_content)

        return cls(
            filename=filename,
            extension=extension,
            content=note_content_processed,
            creation_date=creation_date,
            modification_date=modification_date,
        )

    def extract_links(
        self, skip_prefixes: tuple[str, ...] = DEFAULT_SKIP_PREFIXES
    ) -> list[str]:
        """Extract all URLs (http/https) from the note content.

        Args:
            skip_prefixes: Tuple of URL prefixes to filter out.
                Defaults to DEFAULT_SKIP_PREFIXES (localhost and Power BI/Fabric URLs).

        Returns:
            List of extracted URLs with filtered prefixes removed
        """
        matches = re.findall(LINK_PATTERN_RE, self.content)

        # Clean up trailing punctuation and markdown artifacts
        cleaned = []
        for url in matches:
            # Strip trailing punctuation
            url = url.rstrip(".,;:!?'")

            # Handle trailing ) from markdown [text](url) syntax
            # Only strip if unbalanced
            while url.endswith(")") and url.count(")") > url.count("("):
                url = url[:-1]

            # Filter out URLs matching skip prefixes
            if url.startswith(skip_prefixes):
                continue

            cleaned.append(url)

        return cleaned
