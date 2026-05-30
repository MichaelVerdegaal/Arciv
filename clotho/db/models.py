"""Data model for scraped pages."""

from dataclasses import dataclass


@dataclass
class Page:
    """A scraped web page tracked in the database.

    Content lives on disk at ``saved/<slug>/page.html`` and
    ``saved/<slug>/page.md``. The database holds pointers and minimal state.

    Attributes:
        url: The processed/normalized URL (primary key).
        original_url: Pre-normalization URL (before rewrites).
        domain: tldextract registered domain.
        slug: Folder name under ``saved/``, e.g. ``github.com-a1b2c3d4``.
        fetched: Whether valid HTML has been archived on disk.
        fail_reason: Why fetching/parsing failed, if applicable.
        title: HTML page title.
        author: Page author, if extractable.
        word_count: Number of words in markdown content.
        scraped_at: ISO timestamp of when the page was scraped.
    """

    url: str
    original_url: str
    domain: str = ""
    slug: str = ""
    fetched: bool = False
    fail_reason: str | None = None
    title: str | None = None
    author: str | None = None
    word_count: int = 0
    scraped_at: str | None = None
