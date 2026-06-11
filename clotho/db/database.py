"""SQLite database for tracked pages, indexed links, and sources."""

import sqlite3
from pathlib import Path
from typing import Self

from .models import Page, Source

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    original_url    TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    slug            TEXT NOT NULL DEFAULT '',
    fetched         INTEGER NOT NULL DEFAULT 0,
    fail_reason     TEXT,
    title           TEXT,
    author          TEXT,
    word_count      INTEGER NOT NULL DEFAULT 0,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS links (
    url        TEXT NOT NULL REFERENCES pages(url),
    file_path  TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (url, file_path)
);

CREATE TABLE IF NOT EXISTS sources (
    name     TEXT PRIMARY KEY,
    path     TEXT NOT NULL,
    added_at TEXT NOT NULL
);
"""

_UPSERT_SQL = """\
INSERT INTO pages (
    url, original_url, domain, slug,
    fetched, fail_reason, title, author,
    word_count, fetched_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    original_url = excluded.original_url,
    domain       = excluded.domain,
    slug         = excluded.slug,
    fetched      = excluded.fetched,
    fail_reason  = excluded.fail_reason,
    title        = excluded.title,
    author       = excluded.author,
    word_count   = excluded.word_count,
    fetched_at   = excluded.fetched_at;
"""


class PageDatabase:
    """SQLite-backed storage for pages, indexed links, and sources.

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
        self._migrate()
        self._conn.executescript(_SCHEMA)

    def _migrate(self) -> None:
        """Upgrade a v1 database in place before applying the schema.

        v1 named the fetch timestamp ``scraped_at`` and tracked note names
        in ``page_sources``. Link rows are rebuilt by re-indexing, so
        ``page_sources`` is simply dropped.
        """
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(pages)")
        }
        if "scraped_at" in columns:
            self._conn.execute(
                "ALTER TABLE pages RENAME COLUMN scraped_at TO fetched_at"
            )
        self._conn.execute("DROP TABLE IF EXISTS page_sources")
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
            domain=row["domain"],
            slug=row["slug"],
            fetched=bool(row["fetched"]),
            fail_reason=row["fail_reason"],
            title=row["title"],
            author=row["author"],
            word_count=row["word_count"],
            fetched_at=row["fetched_at"],
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
                page.slug,
                int(page.fetched),
                page.fail_reason,
                page.title,
                page.author,
                page.word_count,
                page.fetched_at,
            ),
        )
        self._conn.commit()

    def ensure_pages(self, url_entries: list[tuple[str, str, str, str]]) -> None:
        """Create pending page entries for URLs not yet in the database.

        Existing pages are left unchanged.

        Args:
            url_entries: List of (url, original_url, domain, slug) tuples.
        """
        self._conn.executemany(
            "INSERT OR IGNORE INTO pages (url, original_url, domain, slug) "
            "VALUES (?, ?, ?, ?)",
            url_entries,
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

    def get_unfetched(self) -> list[Page]:
        """Get all pages that haven't been attempted yet.

        Returns:
            Pages with fetched=0 and no fail_reason (pending).
        """
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE fetched = 0 AND fail_reason IS NULL"
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def get_all(self) -> list[Page]:
        """Get all pages in the database."""
        rows = self._conn.execute("SELECT * FROM pages").fetchall()
        return [self._row_to_page(row) for row in rows]

    def count(self) -> int:
        """Count total pages."""
        row = self._conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        return row["n"]

    def fail_summary(self) -> list[tuple[str | None, str, int]]:
        """Summarize failures grouped by domain and reason.

        Returns:
            List of (domain, fail_reason, count) tuples, ordered by count
            descending.
        """
        rows = self._conn.execute(
            "SELECT domain, fail_reason, COUNT(*) AS n "
            "FROM pages WHERE fetched = 0 AND fail_reason IS NOT NULL "
            "GROUP BY domain, fail_reason ORDER BY n DESC"
        ).fetchall()
        return [(row["domain"], row["fail_reason"], row["n"]) for row in rows]

    # -- indexed links --

    def replace_links_for_files(
        self,
        file_paths: list[str],
        link_entries: list[tuple[str, str, str]],
    ) -> None:
        """Replace the link rows of re-indexed files with fresh entries.

        Deletes every link row belonging to the given files, then inserts
        the freshly extracted entries. Links found in files outside this
        set are untouched, so indexing one source never clobbers another.

        Args:
            file_paths: Full normalized paths of the files that were indexed.
            link_entries: List of (url, file_path, indexed_at) tuples.
        """
        self._conn.executemany(
            "DELETE FROM links WHERE file_path = ?",
            [(path,) for path in file_paths],
        )
        self._conn.executemany(
            "INSERT OR REPLACE INTO links (url, file_path, indexed_at) "
            "VALUES (?, ?, ?)",
            link_entries,
        )
        self._conn.commit()

    def get_files_for_url(self, url: str) -> list[str]:
        """Get the files a URL was indexed from.

        Args:
            url: The processed/normalized URL.

        Returns:
            Sorted list of full normalized file paths containing the URL.
        """
        rows = self._conn.execute(
            "SELECT file_path FROM links WHERE url = ? ORDER BY file_path",
            (url,),
        ).fetchall()
        return [row["file_path"] for row in rows]

    def get_urls_for_file(self, file_path: str) -> list[str]:
        """Get all URLs indexed from a specific file.

        Args:
            file_path: Full normalized path of the file.

        Returns:
            Sorted list of processed URLs found in the file.
        """
        rows = self._conn.execute(
            "SELECT url FROM links WHERE file_path = ? ORDER BY url",
            (file_path,),
        ).fetchall()
        return [row["url"] for row in rows]

    # -- sources --

    def add_source(self, source: Source) -> bool:
        """Register a source.

        Args:
            source: The source to register.

        Returns:
            True if added, False if a source with that name already exists.
        """
        try:
            self._conn.execute(
                "INSERT INTO sources (name, path, added_at) VALUES (?, ?, ?)",
                (source.name, source.path, source.added_at),
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def remove_source(self, name: str) -> bool:
        """Remove a source by name.

        Indexed links and pages are untouched — removing a source only
        stops it from being indexed in the future.

        Args:
            name: The source name.

        Returns:
            True if a source was removed, False if the name was unknown.
        """
        cursor = self._conn.execute("DELETE FROM sources WHERE name = ?", (name,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_source(self, name: str) -> Source | None:
        """Get a source by name.

        Args:
            name: The source name.

        Returns:
            The Source if found, None otherwise.
        """
        row = self._conn.execute(
            "SELECT * FROM sources WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return Source(name=row["name"], path=row["path"], added_at=row["added_at"])

    def list_sources(self) -> list[Source]:
        """List all registered sources, ordered by name."""
        rows = self._conn.execute("SELECT * FROM sources ORDER BY name").fetchall()
        return [
            Source(name=row["name"], path=row["path"], added_at=row["added_at"])
            for row in rows
        ]
