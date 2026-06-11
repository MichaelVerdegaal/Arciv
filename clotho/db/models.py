"""Data models for tracked pages and registered sources."""

from dataclasses import dataclass


@dataclass
class Page:
    """A tracked web page in the database.

    Content lives on disk at ``saved/<slug>/page.html`` (or ``page.pdf``)
    and ``saved/<slug>/page.md``. The database holds pointers and minimal
    state. A missing ``page.md`` for a fetched page means the parse stage
    still has to run.

    Attributes:
        url: The processed/normalized URL (primary key).
        original_url: Pre-normalization URL (before rewrites).
        domain: tldextract registered domain.
        slug: Folder name under ``saved/``, e.g. ``github.com-a1b2c3d4``.
        fetched: Whether raw content (HTML/PDF) has been archived on disk.
        fail_reason: Why fetching/parsing failed, if applicable.
        title: HTML page title (filled in by the parse stage).
        author: Page author, if extractable (filled in by the parse stage).
        word_count: Number of words in markdown content (parse stage).
        fetched_at: ISO timestamp of when the page was fetched.
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
    fetched_at: str | None = None


@dataclass
class Source:
    """A registered source: a named directory of files to index.

    Attributes:
        name: User-chosen unique name (primary key).
        path: Full normalized path of the directory.
        added_at: ISO timestamp of when the source was registered.
    """

    name: str
    path: str
    added_at: str
