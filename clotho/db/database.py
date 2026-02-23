"""SQLite database for storing scraped page data."""

import sqlite3
from pathlib import Path
from typing import Self

from .models import Page

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    original_url    TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    fail_reason     TEXT,
    md_content      TEXT,
    html_path       TEXT,
    title           TEXT,
    author          TEXT,
    word_count      INTEGER NOT NULL DEFAULT 0,
    scraped_at      TEXT,
    embedding       BLOB
);

CREATE TABLE IF NOT EXISTS page_sources (
    url       TEXT NOT NULL REFERENCES pages(url),
    note_name TEXT NOT NULL,
    PRIMARY KEY (url, note_name)
);
"""

_UPSERT_SQL = """\
INSERT INTO pages (
    url, original_url, domain, status,
    fail_reason, md_content, html_path, title, author,
    word_count, scraped_at, embedding
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    original_url = excluded.original_url,
    domain       = excluded.domain,
    status       = excluded.status,
    fail_reason  = excluded.fail_reason,
    md_content   = excluded.md_content,
    html_path    = excluded.html_path,
    title        = excluded.title,
    author       = excluded.author,
    word_count   = excluded.word_count,
    scraped_at   = excluded.scraped_at,
    embedding    = excluded.embedding;
"""


class PageDatabase:
    """SQLite-backed storage for scraped pages and their source notes.

    Use as a context manager to ensure the connection is closed:

        with PageDatabase(path) as db:
            db.upsert(page)

    Args:
        db_path: Path to the SQLite database file. Created if it doesn't exist.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- helpers --

    @staticmethod
    def _row_to_page(row: sqlite3.Row) -> Page:
        """Convert a database row to a Page object."""
        return Page(
            url=row["url"],
            original_url=row["original_url"],
            domain=row["domain"],
            status=row["status"],
            fail_reason=row["fail_reason"],
            md_content=row["md_content"],
            html_path=row["html_path"],
            title=row["title"],
            author=row["author"],
            word_count=row["word_count"],
            scraped_at=row["scraped_at"],
            embedding=row["embedding"],
        )

    # -- page CRUD --

    def upsert(self, page: Page) -> None:
        """Insert or update a page.

        Args:
            page: The page to insert or update.
        """
        self._conn.execute(
            _UPSERT_SQL,
            (
                page.url,
                page.original_url,
                page.domain,
                page.status,
                page.fail_reason,
                page.md_content,
                page.html_path,
                page.title,
                page.author,
                page.word_count,
                page.scraped_at,
                page.embedding,
            ),
        )
        self._conn.commit()

    def ensure_pages(self, url_map: dict[str, tuple[str, str]]) -> None:
        """Create pending page entries for URLs not yet in the database.

        Existing pages are left unchanged.

        Args:
            url_map: Mapping of processed_url -> (original_url, domain).
        """
        self._conn.executemany(
            "INSERT OR IGNORE INTO pages (url, original_url, domain) VALUES (?, ?, ?)",
            [(url, orig, domain) for url, (orig, domain) in url_map.items()],
        )
        self._conn.commit()

    def get(self, url: str) -> Page | None:
        """Get a page by its processed URL (primary key).

        Args:
            url: The processed/normalized URL.

        Returns:
            The Page if found, None otherwise.
        """
        row = self._conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
        return self._row_to_page(row) if row else None

    def get_by_status(self, status: str) -> list[Page]:
        """Get all pages with a given status.

        Args:
            status: One of 'pending', 'fetched', 'scraped', 'failed', 'too_short'.

        Returns:
            List of matching Pages.
        """
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE status = ?", (status,)
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def get_all(self) -> list[Page]:
        """Get all pages in the database."""
        rows = self._conn.execute("SELECT * FROM pages").fetchall()
        return [self._row_to_page(row) for row in rows]

    def get_scraped(self) -> list[Page]:
        """Get all successfully scraped pages (shortcut for status='scraped')."""
        return self.get_by_status("scraped")

    def count(self, status: str | None = None) -> int:
        """Count pages, optionally filtered by status.

        Args:
            status: If provided, count only pages with this status.

        Returns:
            Number of matching pages.
        """
        if status:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM pages WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        return row["n"]

    def url_exists(self, url: str) -> bool:
        """Check if a URL exists in the database.

        Args:
            url: The processed/normalized URL.

        Returns:
            True if the URL has a record in the database.
        """
        row = self._conn.execute(
            "SELECT 1 FROM pages WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
        return row is not None

    # -- source notes --

    def rebuild_sources(self, url_to_notes: dict[str, list[str]]) -> None:
        """Replace all page_sources with the current note-to-URL mapping.

        Clears the entire page_sources table and repopulates from the
        provided mapping. This ensures removed links in notes are reflected
        in the database.

        Args:
            url_to_notes: Mapping of processed_url -> list of note filenames.
        """
        self._conn.execute("DELETE FROM page_sources")
        self._conn.executemany(
            "INSERT OR IGNORE INTO page_sources (url, note_name) VALUES (?, ?)",
            [(url, note) for url, notes in url_to_notes.items() for note in notes],
        )
        self._conn.commit()

    def get_sources(self, url: str) -> list[str]:
        """Get source note filenames for a URL.

        Args:
            url: The processed/normalized URL.

        Returns:
            Sorted list of note filenames that reference this URL.
        """
        rows = self._conn.execute(
            "SELECT note_name FROM page_sources WHERE url = ? ORDER BY note_name",
            (url,),
        ).fetchall()
        return [row["note_name"] for row in rows]

    def get_urls_for_note(self, note_name: str) -> list[str]:
        """Get all URLs referenced by a specific note.

        Args:
            note_name: The note filename.

        Returns:
            List of processed URLs referenced by the note.
        """
        rows = self._conn.execute(
            "SELECT url FROM page_sources WHERE note_name = ? ORDER BY url",
            (note_name,),
        ).fetchall()
        return [row["url"] for row in rows]
