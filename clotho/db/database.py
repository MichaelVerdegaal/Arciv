"""SQLite database for storing scraped page data."""

import json
import sqlite3
from pathlib import Path
from typing import Self

from .models import Page

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    original_url    TEXT NOT NULL,
    source_notes    TEXT NOT NULL DEFAULT '[]',
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
"""

_UPSERT_SQL = """\
INSERT INTO pages (
    url, original_url, source_notes, domain, status,
    fail_reason, md_content, html_path, title, author,
    word_count, scraped_at, embedding
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    original_url = excluded.original_url,
    source_notes = excluded.source_notes,
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
    """SQLite-backed storage for scraped pages.

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
        self._conn.execute(_SCHEMA)
        self._conn.commit()

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
            source_notes=Page.parse_source_notes(row["source_notes"]),
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

    # -- CRUD operations --

    def upsert(self, page: Page) -> None:
        """Insert or update a page, merging source_notes with any existing record.

        Args:
            page: The page to insert or update. If the URL already exists,
                source_notes are merged (union) rather than replaced.
        """
        existing_row = self._conn.execute(
            "SELECT source_notes FROM pages WHERE url = ?", (page.url,)
        ).fetchone()
        if existing_row:
            existing_notes = Page.parse_source_notes(existing_row["source_notes"])
            page.source_notes = sorted(set(existing_notes) | set(page.source_notes))

        self._conn.execute(
            _UPSERT_SQL,
            (
                page.url,
                page.original_url,
                page.source_notes_json(),
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

    def merge_source_notes(self, url: str, new_notes: list[str]) -> None:
        """Add source notes to an existing page without modifying other fields.

        No-op if the URL doesn't exist in the database.

        Args:
            url: The page URL (primary key).
            new_notes: Note filenames to add.
        """
        row = self._conn.execute(
            "SELECT source_notes FROM pages WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return

        existing = Page.parse_source_notes(row["source_notes"])
        merged = sorted(set(existing) | set(new_notes))
        self._conn.execute(
            "UPDATE pages SET source_notes = ? WHERE url = ?",
            (json.dumps(merged), url),
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
            status: One of 'pending', 'scraped', 'failed', 'too_short'.

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
