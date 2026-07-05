"""SQLite database for tracked pages, indexed links, and sources."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Self

from .models import SKIP_REASON_PREFIX, Page, Source

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

# Matches the fail_reason of a "skipped" page (too-short content). Kept next to
# the predicates so the SQL filter and Page.state classify identically; the
# trailing % lets it match the full "too short (12 words ...)" message.
_SKIP_LIKE = f"{SKIP_REASON_PREFIX}%"

# Maps a coarse UI state (see Page.state) to the SQL predicate that selects it,
# so the row-level mapping in Page.state and the query-level filter in
# list_pages stay a single definition. The five are mutually exclusive: a
# parsed page is never also failed, "skipped" carves the too-short rejections
# out of "failed", and "fetched" (raw content on disk, still unparsed) is split
# from "pending" (not fetched yet).
_STATE_PREDICATES: dict[str, str] = {
    "done": "parsed_at IS NOT NULL",
    "skipped": f"parsed_at IS NULL AND fail_reason LIKE '{_SKIP_LIKE}'",
    "failed": (
        "parsed_at IS NULL AND fail_reason IS NOT NULL "
        f"AND fail_reason NOT LIKE '{_SKIP_LIKE}'"
    ),
    "fetched": "fetched_at IS NOT NULL AND parsed_at IS NULL AND fail_reason IS NULL",
    "pending": "fetched_at IS NULL AND fail_reason IS NULL",
}

# Maps an `arciv prune` mode to the WHERE clause selecting the rows it removes.
# "missing" is the narrow, safe default (dead failed rows with no surviving
# link); "all" is the wipe. Fixed strings, never built from user input, so they
# are safe to interpolate into the prune statements.
_PRUNE_PREDICATES: dict[str, str] = {
    "missing": ("fail_reason IS NOT NULL AND url NOT IN (SELECT url FROM links)"),
    "failed": "fail_reason IS NOT NULL",
    "all": "1 = 1",
}

# Columns list_pages may sort by, allow-listed so request input never reaches
# the SQL string directly. fetched_at and title may be NULL (pending/unparsed
# rows); SQLite orders NULLs first ascending, last descending.
_SORT_COLUMNS: dict[str, str] = {
    "fetched_at": "fetched_at",
    "title": "title",
    "word_count": "word_count",
}


# SQLite caps the number of bound parameters per statement (999 in older
# builds), so ``IN (...)`` queries over arbitrary URL lists run in chunks
# comfortably under that floor.
_SQL_VAR_LIMIT = 500

# How many deferred writes a bulk() block accumulates before committing.
# Each commit is a WAL fsync, so this trades a bounded amount of redoable
# work on a crash against thousands of per-row fsyncs in a batch run.
_BULK_COMMIT_EVERY = 50


def _now() -> str:
    """Current UTC time as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _chunked(items: list[str], size: int = _SQL_VAR_LIMIT) -> Iterator[list[str]]:
    """Split a list into chunks that fit SQLite's bound-parameter cap."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


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
        # Bulk-commit state (see bulk()): depth of nested bulk() blocks and
        # how many per-row writes are awaiting a commit.
        self._bulk_depth = 0
        self._pending_writes = 0
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        # executescript commits and resets pragmas set before it
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_unique_slug_index()

    def _ensure_unique_slug_index(self) -> None:
        """Enforce one page per slug, with an actionable error on collision.

        The slug names the ``saved/<slug>/`` folder, so it must be unique; a
        unique index also backfills
        the guarantee onto databases created before it, since this runs on every
        open. Created here rather than in ``_SCHEMA`` so that if existing rows
        already share a slug (a hash collision, or a legacy blank slug) the
        operator gets a clear message naming the duplicates instead of a bare
        ``IntegrityError`` that would leave the database un-openable.
        """
        try:
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pages_slug ON pages(slug)"
            )
        except sqlite3.IntegrityError as exc:
            dupes = self._conn.execute(
                "SELECT slug, COUNT(*) AS n FROM pages "
                "GROUP BY slug HAVING n > 1 ORDER BY n DESC"
            ).fetchall()
            examples = ", ".join(f"{row['slug']!r}×{row['n']}" for row in dupes[:5])
            raise RuntimeError(
                f"Cannot enforce unique page slugs: {len(dupes)} slug(s) are "
                f"shared by multiple URLs ({examples}). This is most likely a "
                "slug hash collision; resolve the duplicate rows before upgrading."
            ) from exc

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- helpers --

    def _commit(self) -> None:
        """Commit now, unless an enclosing bulk() block is deferring commits;
        then only commit once _BULK_COMMIT_EVERY writes have accumulated."""
        if self._bulk_depth == 0:
            self._conn.commit()
            return
        self._pending_writes += 1
        if self._pending_writes >= _BULK_COMMIT_EVERY:
            self._conn.commit()
            self._pending_writes = 0

    @contextmanager
    def bulk(self) -> Iterator[None]:
        """Batch the commits of per-row writes made inside the block.

        Every ``upsert`` normally commits immediately (a WAL fsync each),
        which dominates batch fetch/parse loops. Inside a ``bulk()`` block
        those commits are deferred and flushed every ``_BULK_COMMIT_EVERY``
        writes, so a crash loses at most that many rows' progress. The
        remainder is committed when the block exits — also on error, since
        the rows already written record completed work.
        """
        self._bulk_depth += 1
        try:
            yield
        finally:
            self._bulk_depth -= 1
            if self._bulk_depth == 0 and self._pending_writes:
                self._conn.commit()
                self._pending_writes = 0

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
        self._commit()

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

    def get_many(self, urls: list[str]) -> dict[str, Page]:
        """Get pages for the given URLs in one query per chunk, keyed by URL.

        URLs with no page row are simply absent from the result, so callers
        use ``.get(url)`` where they would have checked ``get(url) is None``.
        """
        pages: dict[str, Page] = {}
        for chunk in _chunked(urls):
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT * FROM pages WHERE url IN ({placeholders})", chunk
            ).fetchall()
            pages.update((row["url"], self._row_to_page(row)) for row in rows)
        return pages

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

    def _urls(self, where: str) -> list[str]:
        """URLs of the pages matching a fixed WHERE clause (never user input),
        without building Page objects."""
        rows = self._conn.execute(f"SELECT url FROM pages WHERE {where}").fetchall()
        return [row["url"] for row in rows]

    def get_unfetched_urls(self) -> list[str]:
        """URLs of all pending pages (see get_unfetched), URLs only."""
        return self._urls("fetched_at IS NULL AND fail_reason IS NULL")

    def get_unparsed_urls(self) -> list[str]:
        """URLs of pages awaiting parse (see get_unparsed), URLs only."""
        return self._urls(
            "fetched_at IS NOT NULL AND parsed_at IS NULL AND fail_reason IS NULL"
        )

    def get_fetched_urls(self) -> list[str]:
        """URLs of all fetched pages (see get_fetched), URLs only."""
        return self._urls("fetched_at IS NOT NULL")

    def get_all_urls(self) -> list[str]:
        """URLs of every page in the database."""
        return self._urls("1 = 1")

    def count(self) -> int:
        """Count total pages."""
        row = self._conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        return row["n"]

    def count_unfetched(self) -> int:
        """Count pending pages (no fetched_at, no fail_reason) without
        materializing their rows."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM pages "
            "WHERE fetched_at IS NULL AND fail_reason IS NULL"
        ).fetchone()
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
        source: str | None = None,
    ) -> list[Page]:
        """List fetched pages ordered by fetch time, newest first by
        default. A limit of None returns every row; a domain restricts
        the rows to that exact registered domain (e.g. ``medium.com``);
        a source restricts them to the pages indexed from that registered
        source (joined via the links table, so a page linked from several
        of the source's files still appears once)."""
        order = "ASC" if oldest_first else "DESC"
        joins = ""
        # When filtering by source the join can return a page once per link
        # row, so DISTINCT collapses those duplicates back to one row.
        select = "SELECT pages.* FROM pages"
        clauses = ["pages.fetched_at IS NOT NULL"]
        params: list[object] = []
        if source is not None:
            select = "SELECT DISTINCT pages.* FROM pages"
            joins = " JOIN links ON links.url = pages.url"
            clauses.append("links.source_name = ?")
            params.append(source)
        if domain is not None:
            clauses.append("pages.domain = ?")
            params.append(domain)
        where = " AND ".join(clauses)
        # SQLite treats a negative LIMIT as "no limit"
        params.append(-1 if limit is None else limit)
        rows = self._conn.execute(
            f"{select}{joins} WHERE {where} ORDER BY pages.fetched_at {order} LIMIT ?",
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

    def prune_pages(self, mode: str, dry_run: bool = False) -> list[str]:
        """Delete page rows (and their link rows) selected by ``mode``.

        Modes:

        - ``missing``: failed pages no longer indexed in any note, rows with a
          ``fail_reason`` that no ``links`` row points at (the dead rows that
          accumulate when a URL is removed from the notes and re-indexing drops
          its link).
        - ``failed``: every page with a ``fail_reason`` set (fetch or parse
          failures, including the too-short "skipped" ones).
        - ``all``: every page in the database.

        Link rows are removed first because ``links.url`` is a foreign key into
        ``pages`` with no cascade, so a referenced page cannot be deleted while
        its link survives.

        Args:
            mode: One of "missing", "failed", or "all".
            dry_run: If True, return the slugs that would be deleted without
                touching the database. Used to preview/confirm before deleting.

        Returns:
            The slugs of the affected pages, so the caller can delete the
            matching ``saved/<slug>/`` folders on disk.

        Raises:
            ValueError: If mode is not a recognized value.
        """
        if mode not in _PRUNE_PREDICATES:
            raise ValueError(f"Invalid prune mode: {mode!r}")
        where = _PRUNE_PREDICATES[mode]

        slugs = [
            row["slug"]
            for row in self._conn.execute(
                f"SELECT slug FROM pages WHERE {where}"
            ).fetchall()
        ]
        if dry_run:
            return slugs

        self._conn.execute(
            f"DELETE FROM links WHERE url IN (SELECT url FROM pages WHERE {where})"
        )
        self._conn.execute(f"DELETE FROM pages WHERE {where}")
        self._conn.commit()
        return slugs

    def failures_for(self, urls: list[str]) -> list[tuple[str, str]]:
        """The (domain, fail_reason) of each given URL that currently has a
        failure recorded, in one query per chunk.

        Backs the run-scoped failure reports: callers pass the URLs a run
        touched and count or group the failures among them, instead of a
        ``get()`` round-trip per URL.
        """
        failures: list[tuple[str, str]] = []
        for chunk in _chunked(urls):
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                "SELECT domain, fail_reason FROM pages "
                f"WHERE fail_reason IS NOT NULL AND url IN ({placeholders})",
                chunk,
            ).fetchall()
            failures.extend((row["domain"], row["fail_reason"]) for row in rows)
        return failures

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

    def list_source_links(self, source_name: str) -> list[tuple[str, Page]]:
        """List a source's indexed links as (file_path, Page) pairs.

        Joins each link row of the source to its page, ordered by file path
        then URL, so the web source-detail view can group links by the note
        file they were found in and show each page's archival state. A URL
        linked from two files in the source appears once per file.
        """
        rows = self._conn.execute(
            "SELECT l.file_path AS file_path, p.* "
            "FROM links l JOIN pages p ON p.url = l.url "
            "WHERE l.source_name = ? "
            "ORDER BY l.file_path, p.url",
            (source_name,),
        ).fetchall()
        return [(row["file_path"], self._row_to_page(row)) for row in rows]

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

    def prune_source_pages(self, name: str) -> list[str]:
        """Delete the pages linked *only* by source ``name``; return their slugs.

        A page is removed only when every link referencing it belongs to this
        source: no link from another source and none from an ad-hoc file
        (``source_name`` NULL). Pages also linked elsewhere are kept untouched
        here, so removing one source never orphans a page another source — or a
        loose ``get --file`` run — still points at; ``remove_source`` later
        drops just this source's attribution from those shared links.

        Must be called *before* ``remove_source`` so the source's links still
        carry its name. Link rows are deleted before page rows because
        ``links.url`` is a foreign key into ``pages`` with no cascade.

        Returns the slugs of the deleted pages so the caller can delete the
        matching ``saved/<slug>/`` folders on disk.
        """
        # `source_name IS NOT ?` is NULL-safe in SQLite: an ad-hoc link
        # (NULL) and a link from another source both count as "another link",
        # so a page with any such link is excluded from the exclusive set.
        rows = self._conn.execute(
            "SELECT DISTINCT pages.url AS url, pages.slug AS slug "
            "FROM pages JOIN links ON links.url = pages.url "
            "WHERE links.source_name = ? "
            "AND pages.url NOT IN "
            "(SELECT url FROM links WHERE source_name IS NOT ?)",
            (name, name),
        ).fetchall()
        urls = [row["url"] for row in rows]
        slugs = [row["slug"] for row in rows]
        if not urls:
            return []
        placeholders = ",".join("?" * len(urls))
        self._conn.execute(f"DELETE FROM links WHERE url IN ({placeholders})", urls)
        self._conn.execute(f"DELETE FROM pages WHERE url IN ({placeholders})", urls)
        self._conn.commit()
        return slugs

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
