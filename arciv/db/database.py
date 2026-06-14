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

-- slug names the saved/<slug>/ folder on disk and is the id the backend
-- looks pages up by, so it must be unique. A unique index (rather than a
-- column UNIQUE constraint) also backfills the guarantee onto databases
-- created before it, on their next open, and speeds up slug lookups.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pages_slug ON pages(slug);

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

# Maps a coarse UI state (see Page.state) to the SQL predicate that selects it,
# so the row-level mapping in Page.state and the query-level filter in
# list_pages stay a single definition. The three are mutually exclusive: a
# parsed page is never also failed.
_STATE_PREDICATES: dict[str, str] = {
    "done": "parsed_at IS NOT NULL",
    "failed": "parsed_at IS NULL AND fail_reason IS NOT NULL",
    "pending": "parsed_at IS NULL AND fail_reason IS NULL",
}

# Columns list_pages may sort by, allow-listed so request input never reaches
# the SQL string directly. fetched_at and title may be NULL (pending/unparsed
# rows); SQLite orders NULLs first ascending, last descending.
_SORT_COLUMNS: dict[str, str] = {
    "fetched_at": "fetched_at",
    "title": "title",
    "word_count": "word_count",
}


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
        read_only: Open without writing: a ``mode=ro`` connection that skips
            schema creation, for the backend's concurrent read endpoints. The
            file must already exist. Defaults to False (the read-write path
            the CLI uses).
    """

    def __init__(self, db_path: Path, read_only: bool = False) -> None:
        self.db_path = db_path
        self.read_only = read_only
        if read_only:
            self._open_readonly(db_path)
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        # executescript commits and resets pragmas set before it
        self._conn.execute("PRAGMA foreign_keys=ON")
        # Wait briefly for a lock rather than failing outright: the web app's
        # archive worker writes while the API (and CLI) may also be open on the
        # same WAL database.
        self._conn.execute("PRAGMA busy_timeout=5000")

    def _open_readonly(self, db_path: Path) -> None:
        """Open a connection that can read but never write the database.

        Uses a ``mode=ro`` URI so the open leaves the file untouched: a normal
        open runs ``executescript`` (a write), and the backend must not write
        to the database the CLI owns. Meant for one short-lived connection per
        request. ``check_same_thread`` is off because FastAPI serves ``def``
        endpoints from a threadpool; a per-request connection is fine as long
        as it is not shared between threads at the same time.
        """
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")

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

    def get_by_slug(self, slug: str) -> Page | None:
        """Get a page by its slug (the ``saved/<slug>/`` folder name), or
        None if no page has it.

        The slug has a UNIQUE index, so this matches at most one row. The
        backend uses it to resolve ``/page/<slug>`` to a page.
        """
        row = self._conn.execute(
            "SELECT * FROM pages WHERE slug = ?", (slug,)
        ).fetchone()
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
        domain: str | None = None,
    ) -> list[Page]:
        """List fetched pages ordered by fetch time, newest first by
        default. A limit of None returns every row; a domain restricts
        the rows to that exact registered domain (e.g. ``medium.com``)."""
        order = "ASC" if oldest_first else "DESC"
        where = "WHERE fetched_at IS NOT NULL"
        params: list[object] = []
        if domain is not None:
            where += " AND domain = ?"
            params.append(domain)
        # SQLite treats a negative LIMIT as "no limit"
        params.append(-1 if limit is None else limit)
        rows = self._conn.execute(
            f"SELECT * FROM pages {where} ORDER BY fetched_at {order} LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_page(row) for row in rows]

    def list_pages(
        self,
        status: str | None = None,
        domain: str | None = None,
        sort: str = "fetched_at",
        order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Page]:
        """List pages for the browse view: filtered, sorted, and paged.

        Unlike list_fetched, this includes pending and failed pages, so the
        archive view can show a page the moment it is registered.

        Args:
            status: Restrict to one coarse state ("done", "failed", or
                "pending"; see Page.state). None returns every state.
            domain: Restrict to one exact registered domain (e.g. medium.com).
            sort: Column to order by: "fetched_at", "title", or "word_count".
            order: "asc" or "desc" (default, newest/highest first).
            limit: Maximum rows to return; None returns all matching rows.
            offset: Rows to skip before collecting, for paging.

        Returns:
            The matching pages. The primary key (url) breaks sort ties so
            paging stays stable across requests.

        Raises:
            ValueError: If status, sort, or order is not a recognized value.
        """
        if sort not in _SORT_COLUMNS:
            raise ValueError(f"Invalid sort column: {sort!r}")
        direction = order.lower()
        if direction not in ("asc", "desc"):
            raise ValueError(f"Invalid sort order: {order!r}")

        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            if status not in _STATE_PREDICATES:
                raise ValueError(f"Invalid status: {status!r}")
            clauses.append(f"({_STATE_PREDICATES[status]})")
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # sort and order are validated against fixed allow-lists above, so
        # they are safe to interpolate; user-supplied values are bound params.
        sql_dir = direction.upper()
        order_by = f"ORDER BY {_SORT_COLUMNS[sort]} {sql_dir}, url {sql_dir}"

        # SQLite reads a negative LIMIT as "no limit"; OFFSET still applies.
        params.append(-1 if limit is None else limit)
        params.append(offset)
        rows = self._conn.execute(
            f"SELECT * FROM pages {where} {order_by} LIMIT ? OFFSET ?",
            params,
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

    def domain_counts(self) -> list[tuple[str, int]]:
        """Count pages per domain, biggest groups first (domain name breaks
        ties). Covers every pipeline state, so the browse-by-domain view
        counts pending and failed pages too."""
        rows = self._conn.execute(
            "SELECT domain, COUNT(*) AS n FROM pages "
            "GROUP BY domain ORDER BY n DESC, domain ASC"
        ).fetchall()
        return [(row["domain"], row["n"]) for row in rows]

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

    def list_sources_with_counts(self) -> list[tuple[Source, int]]:
        """List sources, each paired with the number of distinct pages it
        indexed.

        Like list_sources, but every source carries a count of the distinct
        page URLs linked from it (0 if it has indexed nothing yet). Ordered by
        name; a LEFT JOIN keeps sources that have no links.
        """
        rows = self._conn.execute(
            "SELECT s.name, s.path, s.added_at, COUNT(DISTINCT l.url) AS n "
            "FROM sources s LEFT JOIN links l ON l.source_name = s.name "
            "GROUP BY s.name, s.path, s.added_at "
            "ORDER BY s.name"
        ).fetchall()
        return [
            (
                Source(name=row["name"], path=row["path"], added_at=row["added_at"]),
                row["n"],
            )
            for row in rows
        ]
