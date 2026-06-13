"""Data models for tracked pages and registered sources."""

from dataclasses import dataclass


@dataclass
class Page:
    """A tracked web page in the database.

    Raw content lives on disk at ``saved/<slug>/page.html`` (or
    ``page.pdf``), parsed markdown at ``saved/<slug>/page.md``. The
    database holds pointers and pipeline state.

    Pipeline state is carried by the timestamps plus ``fail_reason``:

    - pending:        ``fetched_at`` NULL, ``fail_reason`` NULL
    - fetch failed:   ``fetched_at`` NULL, ``fail_reason`` set
    - fetched:        ``fetched_at`` set, ``parsed_at`` NULL
    - parse rejected: ``fetched_at`` set, ``parsed_at`` NULL, ``fail_reason`` set
    - parsed:         ``parsed_at`` set

    Attributes:
        url: The processed/normalized URL (primary key).
        original_url: Pre-normalization URL (before rewrites).
        domain: tldextract registered domain.
        slug: Folder name under ``saved/``, e.g. ``github.com-a1b2c3d4``.
        content_type: Raw file format on disk: "html" or "pdf". Set by the
            fetch stage; None while pending.
        title: HTML page title (filled in by the parse stage).
        author: Page author, if extractable (filled in by the parse stage).
        word_count: Number of words in markdown content (parse stage).
        fail_reason: Why fetching/parsing failed, if applicable.
        added_at: ISO timestamp of when the URL first entered the database.
        fetched_at: ISO timestamp of the last successful fetch.
        parsed_at: ISO timestamp of the last successful parse.
    """

    url: str
    original_url: str
    domain: str = ""
    slug: str = ""
    content_type: str | None = None
    title: str | None = None
    author: str | None = None
    word_count: int = 0
    fail_reason: str | None = None
    added_at: str | None = None
    fetched_at: str | None = None
    parsed_at: str | None = None

    @property
    def fetched(self) -> bool:
        """Whether raw content has been archived on disk."""
        return self.fetched_at is not None

    @property
    def parsed(self) -> bool:
        """Whether the raw content has been converted to markdown."""
        return self.parsed_at is not None


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
