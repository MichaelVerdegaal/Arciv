"""Data model for scraped pages."""

import json
from dataclasses import dataclass, field


@dataclass
class Page:
    """A scraped web page stored in the database.

    Attributes:
        url: The processed/normalized URL (primary key).
        original_url: Pre-normalization URL (before rewrites).
        source_notes: Daily note filenames that referenced this URL.
        domain: tldextract registered domain.
        status: One of 'pending', 'scraped', 'failed', 'too_short'.
        fail_reason: Why scraping failed, if applicable.
        md_content: Extracted markdown content.
        html_path: Relative path to compressed .html.br archive file.
        title: HTML page title.
        author: Page author, if extractable.
        word_count: Number of words in markdown content.
        scraped_at: ISO timestamp of when the page was scraped.
        embedding: Embedding vector as bytes (for later use).
    """

    url: str
    original_url: str
    source_notes: list[str] = field(default_factory=list)
    domain: str = ""
    status: str = "pending"
    fail_reason: str | None = None
    md_content: str | None = None
    html_path: str | None = None
    title: str | None = None
    author: str | None = None
    word_count: int = 0
    scraped_at: str | None = None
    embedding: bytes | None = None

    def source_notes_json(self) -> str:
        """Serialize source_notes to a JSON string for database storage."""
        return json.dumps(sorted(set(self.source_notes)))

    @staticmethod
    def parse_source_notes(json_str: str) -> list[str]:
        """Deserialize source_notes from a JSON string."""
        return json.loads(json_str) if json_str else []
