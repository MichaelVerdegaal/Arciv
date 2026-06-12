"""SQLite database for tracked pages, indexed links, and sources."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Self

from .models import Page, Source

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS pages (
    url          TEXT PRIMARY KEY,
    original_url TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT '',
    slug         TEXT NOT NULL DEFAULT '',
    content_type TEXT,
    title        TEXT,
    author       TEXT,
    word_count   INTEGER NOT NULL DEFAULT 0,
    fail_reason  TEXT,
    added_at     TEXT NOT NULL,
    fetched_at   TEXT,
    parsed_at    TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    name     TEXT PRIMARY KEY,
    path     TEXT NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    url         TEXT NOT NULL REFERENCES pages(url),
    file_path   TEXT NOT NULL,
    source_name TEXT REFERENCES sources(name) ON DELETE SET NULL,
    indexed_at  TEXT NOT NULL,
    PRIMARY KEY (url, file_path)
);

CREATE INDEX IF NOT EXISTS idx_links_file_path ON links(file_path);
"""

# added_at is deliberately absent from the update clause: it marks when the
# URL first entered the database and must survive refetches.
_UPSERT_SQL = """\
INSERT INTO pages (
    url, original_url, domain, slug, content_type,
    title, author, word_count, fail_reason,
    added_at, fetched_at, parsed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    original_url = excluded.original_url,
    domain       = excluded.domain,
    slug         = excluded.slug,
    content_type = excluded.content_type,
    title        = excluded.title,
    author       = excluded.author,
    word_count   = excluded.word_count,
    fail_reason  = excluded.fail_reason,
    fetched_at   = excluded.fetched_at,
    parsed_at    = excluded.parsed_at;
"""


def _now() -> str:
    """Current UTC time as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


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
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        # executescript commits and resets pragmas set before it
        self._conn.execute("PRAGMA foreign_keys=ON")

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
            content_type=row["content_type"],
            title=row["title"],
            author=row["author"],
            word_count=row["word_count"],
            fail_reason=row["fail_reason"],
            added_at=row["added_at"],
            fetched_at=row["fetched_at"],
            parsed_at=row["parsed_at"],
        )

    # -- page CRUD --

    def upsert(self, page: Page) -> None:
        """Insert or update a page. ``added_at`` is only written on first
        insert; updates keep the original value."""
        self._conn.execute(
            _UPSERT_SQL,
            (
                page.url,
                page.original_url,
                page.domain,
                page.slug,
                page.content_type,
                page.title,
                page.author,
                page.word_count,
                page.fail_reason,
                page.added_at or _now(),
                page.fetched_at,
                page.parsed_at,
            ),
        )
        self._conn.commit()

    def ensure_pages(self, url_entries: list[tuple[str, str, str, str]]) -> None:
        """Create pending page entries for (url, original_url, domain, slug)
        tuples not yet in the database. Existing pages are left unchanged;
        new pages get ``added_at`` set to the current time."""
        added_at = _now()
        self._conn.executemany(
            "INSERT OR IGNORE INTO pages "
            "(url, original_url, domain, slug, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [entry + (added_at,) for entry in url_entries],
        )
        self._conn.commit()

    def get(self, url: str) -> Page | None:
        """Get a page by its processed/normalized URL (primary key)."""
        row = self._conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
        return self._row_to_page(row) if row else None

    def get_unfetched(self) -> list[Page]:
        """Get all pending pages: no fetched_at and no fail_reason."""
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE fetched_at IS NULL AND fail_reason IS NULL"
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def get_unparsed(self) -> list[Page]:
        """Get pages awaiting parse: fetched_at set, no parsed_at, no
        fail_reason."""
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE fetched_at IS NOT NULL "
            "AND parsed_at IS NULL AND fail_reason IS NULL"
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def get_fetched(self) -> list[Page]:
        """Get all pages with raw content on disk (fetched_at set),
        parse-rejected included."""
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE fetched_at IS NOT NULL"
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

    def status_counts(self) -> dict[str, int]:
        """Count pages per pipeline state (see Page docstring for states):
        total, pending, fetch_failed, awaiting_parse, parse_rejected, parsed."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(fetched_at IS NULL AND fail_reason IS NULL), 0) "
            "  AS pending, "
            "COALESCE(SUM(fetched_at IS NULL AND fail_reason IS NOT NULL), 0) "
            "  AS fetch_failed, "
            "COALESCE(SUM(fetched_at IS NOT NULL AND parsed_at IS NULL "
            "  AND fail_reason IS NULL), 0) AS awaiting_parse, "
            "COALESCE(SUM(fetched_at IS NOT NULL AND parsed_at IS NULL "
            "  AND fail_reason IS NOT NULL), 0) AS parse_rejected, "
            "COALESCE(SUM(parsed_at IS NOT NULL), 0) AS parsed "
            "FROM pages"
        ).fetchone()
        return {key: row[key] for key in row.keys()}

    def list_fetched(
        self,
        limit: int | None = None,
        oldest_first: bool = False,
    ) -> list[Page]:
        """List fetched pages ordered by fetch time, newest first by
        default. A limit of None returns every row."""
        order = "ASC" if oldest_first else "DESC"
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE fetched_at IS NOT NULL "
            f"ORDER BY fetched_at {order} LIMIT ?",
            # SQLite treats a negative LIMIT as "no limit"
            (-1 if limit is None else limit,),
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def fail_summary(self) -> list[tuple[str | None, str, int]]:
        """Summarize failures as (domain, fail_reason, count) tuples,
        biggest groups first."""
        rows = self._conn.execute(
            "SELECT domain, fail_reason, COUNT(*) AS n "
            "FROM pages WHERE fail_reason IS NOT NULL "
            "GROUP BY domain, fail_reason ORDER BY n DESC"
        ).fetchall()
        return [(row["domain"], row["fail_reason"], row["n"]) for row in rows]

    # -- indexed links --

    def replace_links_for_files(
        self,
        file_paths: list[str],
        link_entries: list[tuple[str, str, str | None, str]],
    ) -> None:
        """Replace the link rows of re-indexed files with fresh entries.

        Deletes every link row belonging to the given files, then inserts
        the freshly extracted (url, file_path, source_name, indexed_at)
        entries; source_name is None for ad-hoc files outside any registered
        source. Links found in files outside this set are untouched, so
        indexing one source never clobbers another.
        """
        self._conn.executemany(
            "DELETE FROM links WHERE file_path = ?",
            [(path,) for path in file_paths],
        )
        self._conn.executemany(
            "INSERT OR REPLACE INTO links "
            "(url, file_path, source_name, indexed_at) "
            "VALUES (?, ?, ?, ?)",
            link_entries,
        )
        self._conn.commit()

    def get_files_for_url(self, url: str) -> list[str]:
        """Get the sorted, full normalized paths of files the URL was
        indexed from."""
        rows = self._conn.execute(
            "SELECT file_path FROM links WHERE url = ? ORDER BY file_path",
            (url,),
        ).fetchall()
        return [row["file_path"] for row in rows]

    def get_urls_for_file(self, file_path: str) -> list[str]:
        """Get the sorted processed URLs indexed from a file (full
        normalized path)."""
        rows = self._conn.execute(
            "SELECT url FROM links WHERE file_path = ? ORDER BY url",
            (file_path,),
        ).fetchall()
        return [row["url"] for row in rows]

    def get_urls_for_source(self, source_name: str) -> list[str]:
        """Get the sorted, distinct processed URLs indexed from a
        registered source."""
        rows = self._conn.execute(
            "SELECT DISTINCT url FROM links WHERE source_name = ? ORDER BY url",
            (source_name,),
        ).fetchall()
        return [row["url"] for row in rows]

    # -- sources --

    def add_source(self, source: Source) -> bool:
        """Register a source. Returns False if the name is already taken."""
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
        """Remove a source by name; returns False if the name was unknown.

        Indexed links and pages are kept; their ``source_name`` is set to
        NULL via the foreign key. Removing a source only stops it from
        being indexed in the future.
        """
        cursor = self._conn.execute("DELETE FROM sources WHERE name = ?", (name,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_source(self, name: str) -> Source | None:
        """Get a source by name, or None if unknown."""
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
