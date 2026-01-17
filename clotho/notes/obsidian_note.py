import re
from pathlib import Path

from .note import Note

# Regex patterns
TIMESTAMP_PATTERN_RE = r"^\d{8}\s+\d{4}\s*\n\s*Status:\s*#\w+\s*\n"
MARKDOWN_H1_PATTERN_RE = r"^#\s+.+$"

# Url prefixes to skip
DEFAULT_SKIP_PREFIXES = (
    "http://localhost",
    "https://localhost",
    "http://127.0.0.1",
    "https://127.0.0.1",
    "https://app.fabric.microsoft.com/",
    "https://app.powerbi.com/",
)


class ObsidanNote(Note):
    def __init__(self, note_path: str | Path):
        super().__init__(note_path)

        # Verify is markdown file
        if not self.extension == ".md":
            raise ValueError(f"Note path {note_path} is not a markdown file")

    # @staticmethod
    # def _read_content(content: str) -> str:
    #     """Remove metadata headers and content before first H1 header.
    #
    #     Handlestimestamp/status patterns found in Obsidian daily notes.
    #
    #     Args:
    #         content: Raw note content with potential frontmatter
    #
    #     Returns:
    #         Cleaned content starting from first H1 header
    #     """
    #     # Remove timestamp pattern (e.g., "20251121 1011") and Status line
    #     # This handles lines like "20241101 1111" followed by "Status: #daily"
    #     content = re.sub(TIMESTAMP_PATTERN_RE, "", content, flags=re.MULTILINE)
    #
    #     # Find first H1 header (# Heading)
    #     h1_match = re.search(MARKDOWN_H1_PATTERN_RE, content, flags=re.MULTILINE)
    #
    #     if h1_match:
    #         # Return content starting from first H1, stripped of leading/trailing whitespace
    #         return content[h1_match.start() :].strip()
    #
    #     # If no H1 found, return cleaned content
    #     return content.strip()

    def extract_links(
        self, skip_prefixes: tuple[str, ...] = DEFAULT_SKIP_PREFIXES
    ) -> list[str]:
        """Extract all URLs (http/https) from the note content.

        Args:
            skip_prefixes: URL prefixes to filter out.

        Returns:
            List of extracted URLs
        """
        link_pattern_re = r"https?://[^\s<>\[\]\"]+"
        extracted_urls = []

        for url in re.findall(link_pattern_re, self.text):
            # Strip trailing punctuation
            url = url.rstrip(".,;:!?'")
            # Handle trailing ) from markdown [text](url) syntax
            while url.endswith(")") and url.count(")") > url.count("("):
                url = url[:-1]

            if not url.startswith(skip_prefixes):
                extracted_urls.append(url)

        return extracted_urls
