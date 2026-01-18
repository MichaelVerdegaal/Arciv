import re
from pathlib import Path

from .note import Note


class MarkdownNote(Note):
    def __init__(self, note_path: str | Path):
        super().__init__(note_path)

        # Verify is markdown file
        if not self.extension == ".md":
            raise ValueError(f"Note path {note_path} is not a markdown file")

        # Get main note content (first H1 header and below)
        h1_pos: tuple | None = self.find_headers(level=1, first=True)
        if h1_pos:
            self.text: str = self.text[h1_pos[0] :]

    def find_headers(
        self,
        level: int,
        first: bool = False,
    ) -> tuple[int, int] | list[tuple[int, int]] | None:
        """Find markdown headers of a specific level.

        Args:
            level: Header level (1-6)
            first: If True, return only first match

        Returns:
            - If first=True: (start, end) tuple or None if no match
            - If first=False: List of (start, end) tuples (may be empty)

        Raises:
            ValueError: If level not in 1-6
        """
        if not 1 <= level <= 6:
            raise ValueError(f"Header level must be 1-6, got {level}")

        header_re = rf"^#{{{level}}}\s+.+$"

        if first:
            match = re.search(header_re, self.text, flags=re.MULTILINE)
            return (match.start(), match.end()) if match else None

        return [
            (m.start(), m.end())
            for m in re.finditer(header_re, self.text, flags=re.MULTILINE)
        ]
