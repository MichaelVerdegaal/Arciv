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
        h1_pos = self.find_first_header(level=1)
        if h1_pos:
            self.text: str = self.text[h1_pos[0] :]

    def find_first_header(self, level: int) -> tuple[int, int] | None:
        """Find the first markdown header of a specific level.

        Args:
            level: Header level (1-6)

        Returns:
            (start, end) span of the first match, or None if no match

        Raises:
            ValueError: If level not in 1-6
        """
        if not 1 <= level <= 6:
            raise ValueError(f"Header level must be 1-6, got {level}")

        header_re = rf"^#{{{level}}}\s+.+$"
        match = re.search(header_re, self.text, flags=re.MULTILINE)
        return (match.start(), match.end()) if match else None
