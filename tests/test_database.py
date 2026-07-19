"""Tests for the SQLite-backed PageDatabase."""

import sqlite3

import pytest

from arciv.core.db import Page, PageDatabase, Source
from arciv.core.urls import slug_for_url


@pytest.fixture
def db(tmp_path):
    """A fresh database backed by a temp file, closed after the test."""
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


def _page(url: str, **overrides) -> Page:
    # slug is unique per URL (slug_for_url is deterministic), matching
    # production and satisfying the slug UNIQUE constraint when a test
    # seeds several pages at once.
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug=slug_for_url(url),
        content_type="html",
        word_count=500,
        fetched_at="2026-06-11T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Page(url=url, **defaults)


def _source(name: str = "notes", path: str = "/vault/notes") -> Source:
    return Source(name=name, path=path, added_at="2026-06-11T00:00:00+00:00")


def _link_rows(db) -> list[tuple[str, str, str | None]]:
    """(url, file_path, source_name) link rows, read straight from the table
    since links have no public read API (test observation only)."""
    rows = db._conn.execute(
        "SELECT url, file_path, source_name FROM links ORDER BY file_path, url"
    ).fetchall()
    return [(row["url"], row["file_path"], row["source_name"]) for row in rows]


class TestCrud:
    def test_upsert_and_get(self, db):
        page = _page("https://example.com/a", title="Hello")
        db.upsert(page)
        stored = db.get("https://example.com/a")
        assert stored is not None
        assert stored.title == "Hello"
        assert stored.fetched is True
        assert stored.content_type == "html"

    def test_get_missing_returns_none(self, db):
        assert db.get("https://nope.com") is None

    def test_upsert_updates_existing(self, db):
        db.upsert(_page("https://example.com/a", word_count=100))
        db.upsert(_page("https://example.com/a", word_count=999))
        assert db.get("https://example.com/a").word_count == 999
        assert db.count() == 1

    def test_upsert_sets_added_at_once(self, db):
        db.upsert(_page("https://example.com/a", added_at="2026-01-01T00:00:00"))
        # A refetch-style upsert without added_at must not erase the original
        db.upsert(_page("https://example.com/a", added_at=None))
        assert db.get("https://example.com/a").added_at == "2026-01-01T00:00:00"

    def test_upsert_fills_added_at_when_missing(self, db):
        db.upsert(_page("https://example.com/a", added_at=None))
        assert db.get("https://example.com/a").added_at is not None

    def test_count(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        assert db.count() == 2

    def test_ensure_pages_inserts_pending_with_added_at(self, db):
        db.ensure_pages(
            [
                (
                    "https://example.com/a",
                    "https://example.com/a",
                    "example.com",
                    "example.com-aaaaaaaa",
                ),
            ]
        )
        page = db.get("https://example.com/a")
        assert page is not None
        assert page.fetched is False
        assert page.parsed is False
        assert page.added_at is not None

    def test_ensure_pages_keeps_existing(self, db):
        db.upsert(_page("https://example.com/a", title="Kept"))
        db.ensure_pages(
            [
                (
                    "https://example.com/a",
                    "https://example.com/a",
                    "example.com",
                    "example.com-aaaaaaaa",
                ),
            ]
        )
        assert db.get("https://example.com/a").title == "Kept"

    def test_ensure_pages_slug_collision_is_loud(self, db):
        # A new URL whose slug collides with a different URL's slug must
        # raise, not be silently dropped (INSERT OR IGNORE would swallow it).
        db.upsert(_page("https://example.com/a", slug="example.com-collide0"))
        with pytest.raises(RuntimeError, match="[Ss]lug collision"):
            db.ensure_pages(
                [
                    (
                        "https://example.com/b",
                        "https://example.com/b",
                        "example.com",
                        "example.com-collide0",
                    ),
                ]
            )


class TestSlugConstraint:
    def test_duplicate_slug_is_rejected(self, db):
        db.upsert(_page("https://example.com/a", slug="example.com-dup00000"))
        # A different URL may not reuse a slug: the two would collide on the
        # same saved/<slug>/ folder and break slug-keyed lookups.
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert(_page("https://example.com/b", slug="example.com-dup00000"))

    def test_index_is_added_to_a_db_created_before_the_constraint(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        # A database from before the constraint: a pages table, no slug index.
        legacy = sqlite3.connect(db_path)
        legacy.executescript(
            "CREATE TABLE pages (url TEXT PRIMARY KEY, slug TEXT NOT NULL DEFAULT '');"
        )
        legacy.executemany(
            "INSERT INTO pages (url, slug) VALUES (?, ?)",
            [("https://a", "s1"), ("https://b", "s2")],
        )
        legacy.commit()
        legacy.close()

        # Opening re-runs the schema script, which adds the index in place:
        # CREATE UNIQUE INDEX IF NOT EXISTS migrates the existing table.
        with PageDatabase(db_path):
            pass

        check = sqlite3.connect(db_path)
        index_names = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        check.close()
        assert "idx_pages_slug" in index_names

    def test_preexisting_duplicate_slugs_raise_a_clear_error(self, tmp_path):
        # An archive whose rows already collide on slug must fail to open with
        # an actionable message, not a bare IntegrityError that hides the cause.
        db_path = tmp_path / "legacy.db"
        legacy = sqlite3.connect(db_path)
        legacy.executescript(
            "CREATE TABLE pages (url TEXT PRIMARY KEY, slug TEXT NOT NULL DEFAULT '');"
        )
        legacy.executemany(
            "INSERT INTO pages (url, slug) VALUES (?, ?)",
            [("https://a", "dup"), ("https://b", "dup")],
        )
        legacy.commit()
        legacy.close()

        with pytest.raises(RuntimeError, match="unique page slugs"):
            PageDatabase(db_path)


class TestStateQueries:
    def test_get_unfetched_urls_is_pending_only(self, db):
        db.upsert(_page("https://example.com/fetched"))
        db.upsert(
            _page("https://example.com/failed", fetched_at=None, fail_reason="timeout")
        )
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert db.get_unfetched_urls() == ["https://example.com/pending"]

    def test_get_unparsed_excludes_rejected_and_parsed(self, db):
        db.upsert(_page("https://example.com/todo"))
        db.upsert(_page("https://example.com/done", parsed_at="2026-06-11T01:00:00"))
        db.upsert(_page("https://example.com/rejected", fail_reason="too short"))
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert {p.url for p in db.get_unparsed()} == {"https://example.com/todo"}

    def test_get_fetched_includes_parse_rejected(self, db):
        db.upsert(_page("https://example.com/rejected", fail_reason="too short"))
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert {p.url for p in db.get_fetched()} == {"https://example.com/rejected"}

    def test_get_many_returns_only_known_urls(self, db):
        db.upsert(_page("https://example.com/a", title="A"))
        db.upsert(_page("https://example.com/b", title="B"))
        pages = db.get_many(
            ["https://example.com/a", "https://example.com/b", "https://nope.com"]
        )
        assert set(pages) == {"https://example.com/a", "https://example.com/b"}
        assert pages["https://example.com/a"].title == "A"

    def test_get_many_empty_input(self, db):
        assert db.get_many([]) == {}

    def test_get_many_spans_chunks(self, db):
        # More URLs than one IN (...) chunk holds still resolve in full.
        urls = [f"https://example.com/{i}" for i in range(501 + 10)]
        for url in urls:
            db.upsert(_page(url))
        assert set(db.get_many(urls)) == set(urls)

    def test_url_variants_select_the_right_states(self, db):
        db.upsert(_page("https://example.com/todo"))
        db.upsert(_page("https://example.com/done", parsed_at="2026-06-11T01:00:00"))
        db.upsert(_page("https://example.com/rejected", fail_reason="too short"))
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert db.get_unfetched_urls() == ["https://example.com/pending"]
        assert set(db.get_unparsed_urls()) == {p.url for p in db.get_unparsed()}
        assert set(db.get_fetched_urls()) == {p.url for p in db.get_fetched()}
        assert set(db.get_all_urls()) == {
            "https://example.com/todo",
            "https://example.com/done",
            "https://example.com/rejected",
            "https://example.com/pending",
        }

    def test_count_unfetched(self, db):
        db.upsert(_page("https://example.com/fetched"))
        db.upsert(
            _page("https://example.com/failed", fetched_at=None, fail_reason="timeout")
        )
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert db.count_unfetched() == 1

    def test_failures_for_scopes_to_given_urls(self, db):
        db.upsert(
            _page(
                "https://a.com/1",
                domain="a.com",
                fetched_at=None,
                fail_reason="timeout",
            )
        )
        db.upsert(_page("https://b.com/2", domain="b.com", fail_reason="too short"))
        db.upsert(_page("https://c.com/3", domain="c.com"))  # no failure
        failures = db.failures_for(["https://a.com/1", "https://c.com/3"])
        assert failures == [("a.com", "timeout")]

    def test_fail_summary_covers_fetch_and_parse_failures(self, db):
        # fetch failure: never fetched
        db.upsert(
            _page(
                "https://a.com/1",
                domain="a.com",
                fetched_at=None,
                fail_reason="timeout",
            )
        )
        # parse rejection: fetched but rejected
        db.upsert(_page("https://a.com/2", domain="a.com", fail_reason="too short"))
        summary = db.fail_summary()
        assert ("a.com", "timeout", 1) in summary
        assert ("a.com", "too short", 1) in summary

    def test_status_counts_covers_every_state(self, db):
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        db.upsert(
            _page(
                "https://example.com/fetch-failed",
                fetched_at=None,
                fail_reason="timeout",
            )
        )
        db.upsert(_page("https://example.com/awaiting-parse"))
        db.upsert(_page("https://example.com/parse-rejected", fail_reason="too short"))
        db.upsert(_page("https://example.com/parsed", parsed_at="2026-06-11T01:00:00"))
        assert db.status_counts() == {
            "total": 5,
            "pending": 1,
            "fetch_failed": 1,
            "awaiting_parse": 1,
            "parse_rejected": 1,
            "parsed": 1,
        }

    def test_status_counts_empty_db_is_all_zero(self, db):
        assert db.status_counts() == {
            "total": 0,
            "pending": 0,
            "fetch_failed": 0,
            "awaiting_parse": 0,
            "parse_rejected": 0,
            "parsed": 0,
        }

    def test_list_fetched_newest_first_with_limit(self, db):
        db.upsert(_page("https://example.com/old", fetched_at="2026-06-01T00:00:00"))
        db.upsert(_page("https://example.com/mid", fetched_at="2026-06-05T00:00:00"))
        db.upsert(_page("https://example.com/new", fetched_at="2026-06-10T00:00:00"))
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        fetched = db.list_fetched(limit=2)
        assert [p.url for p in fetched] == [
            "https://example.com/new",
            "https://example.com/mid",
        ]

    def test_list_fetched_no_limit_returns_all_but_pending(self, db):
        db.upsert(_page("https://example.com/old", fetched_at="2026-06-01T00:00:00"))
        db.upsert(_page("https://example.com/new", fetched_at="2026-06-10T00:00:00"))
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        fetched = db.list_fetched()
        assert [p.url for p in fetched] == [
            "https://example.com/new",
            "https://example.com/old",
        ]

    def test_list_fetched_oldest_first(self, db):
        db.upsert(_page("https://example.com/old", fetched_at="2026-06-01T00:00:00"))
        db.upsert(_page("https://example.com/mid", fetched_at="2026-06-05T00:00:00"))
        db.upsert(_page("https://example.com/new", fetched_at="2026-06-10T00:00:00"))
        fetched = db.list_fetched(oldest_first=True)
        assert [p.url for p in fetched] == [
            "https://example.com/old",
            "https://example.com/mid",
            "https://example.com/new",
        ]

    def test_list_fetched_filters_by_domain(self, db):
        db.upsert(_page("https://a.com/1", domain="a.com"))
        db.upsert(_page("https://b.com/1", domain="b.com"))
        db.upsert(_page("https://a.com/2", domain="a.com"))
        fetched = db.list_fetched(domain="a.com")
        assert {p.url for p in fetched} == {"https://a.com/1", "https://a.com/2"}

    def test_list_fetched_domain_filter_excludes_pending(self, db):
        db.upsert(_page("https://a.com/fetched", domain="a.com"))
        db.upsert(_page("https://a.com/pending", domain="a.com", fetched_at=None))
        fetched = db.list_fetched(domain="a.com")
        assert [p.url for p in fetched] == ["https://a.com/fetched"]

    def test_list_fetched_domain_with_no_matches_is_empty(self, db):
        db.upsert(_page("https://a.com/1", domain="a.com"))
        assert db.list_fetched(domain="nope.com") == []


class TestBulkCommits:
    def _visible_rows(self, db) -> int:
        """Count committed rows through a second connection, so uncommitted
        writes on the main connection stay invisible."""
        other = sqlite3.connect(db.db_path)
        try:
            return other.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        finally:
            other.close()

    def test_bulk_defers_commits_until_exit(self, db):
        with db.bulk():
            db.upsert(_page("https://example.com/a"))
            db.upsert(_page("https://example.com/b"))
            assert self._visible_rows(db) == 0
        assert self._visible_rows(db) == 2

    def test_bulk_commits_every_n_writes(self, db, monkeypatch):
        monkeypatch.setattr("arciv.core.db.database._BULK_COMMIT_EVERY", 2)
        with db.bulk():
            db.upsert(_page("https://example.com/a"))
            db.upsert(_page("https://example.com/b"))
            assert self._visible_rows(db) == 2
            db.upsert(_page("https://example.com/c"))
            assert self._visible_rows(db) == 2
        assert self._visible_rows(db) == 3

    def test_bulk_flushes_completed_work_on_error(self, db):
        with pytest.raises(RuntimeError):
            with db.bulk():
                db.upsert(_page("https://example.com/a"))
                raise RuntimeError("boom")
        assert self._visible_rows(db) == 1

    def test_upsert_outside_bulk_commits_immediately(self, db):
        db.upsert(_page("https://example.com/a"))
        assert self._visible_rows(db) == 1


class TestLinks:
    def test_replace_inserts_link_rows(self, db):
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/note1.md", "/vault/note2.md"],
            [
                ("https://example.com/a", "/vault/note1.md", None, "t1"),
                ("https://example.com/a", "/vault/note2.md", None, "t1"),
            ],
        )
        assert _link_rows(db) == [
            ("https://example.com/a", "/vault/note1.md", None),
            ("https://example.com/a", "/vault/note2.md", None),
        ]

    def test_reindex_replaces_links_of_same_file(self, db):
        db.upsert(_page("https://example.com/old"))
        db.upsert(_page("https://example.com/new"))
        db.replace_links_for_files(
            ["/vault/daily.md"],
            [("https://example.com/old", "/vault/daily.md", None, "t1")],
        )
        db.replace_links_for_files(
            ["/vault/daily.md"],
            [("https://example.com/new", "/vault/daily.md", None, "t2")],
        )
        assert _link_rows(db) == [
            ("https://example.com/new", "/vault/daily.md", None),
        ]

    def test_reindex_leaves_other_files_alone(self, db):
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/one.md"],
            [("https://example.com/a", "/vault/one.md", None, "t1")],
        )
        db.replace_links_for_files(
            ["/vault/two.md"],
            [("https://example.com/a", "/vault/two.md", None, "t2")],
        )
        assert _link_rows(db) == [
            ("https://example.com/a", "/vault/one.md", None),
            ("https://example.com/a", "/vault/two.md", None),
        ]

    def test_links_carry_source_attribution(self, db):
        db.add_source(_source("notes"))
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        db.replace_links_for_files(
            ["/vault/notes/x.md"],
            [
                ("https://example.com/a", "/vault/notes/x.md", "notes", "t1"),
                ("https://example.com/b", "/vault/notes/x.md", None, "t1"),
            ],
        )
        assert _link_rows(db) == [
            ("https://example.com/a", "/vault/notes/x.md", "notes"),
            ("https://example.com/b", "/vault/notes/x.md", None),
        ]

    def test_link_requires_existing_page(self, db):
        # foreign_keys=ON: links cannot point at unknown pages
        with pytest.raises(sqlite3.IntegrityError):
            db.replace_links_for_files(
                [],
                [("https://example.com/ghost", "/vault/x.md", None, "t1")],
            )


class TestSources:
    def test_add_and_get(self, db):
        assert db.add_source(_source()) is True
        source = db.get_source("notes")
        assert source is not None
        assert source.path == "/vault/notes"

    def test_add_duplicate_name_fails(self, db):
        db.add_source(_source())
        assert db.add_source(_source(path="/elsewhere")) is False
        assert db.get_source("notes").path == "/vault/notes"

    def test_remove(self, db):
        db.add_source(_source())
        assert db.remove_source("notes") is True
        assert db.get_source("notes") is None

    def test_remove_unknown_returns_false(self, db):
        assert db.remove_source("nope") is False

    def test_remove_source_keeps_links_but_clears_attribution(self, db):
        db.add_source(_source("notes"))
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/notes/x.md"],
            [("https://example.com/a", "/vault/notes/x.md", "notes", "t1")],
        )
        db.remove_source("notes")
        # Link row survives, but no longer attributed to the source
        assert _link_rows(db) == [
            ("https://example.com/a", "/vault/notes/x.md", None),
        ]

    def test_list_sources_ordered_by_name(self, db):
        db.add_source(_source(name="zeta", path="/z"))
        db.add_source(_source(name="alpha", path="/a"))
        assert [s.name for s in db.list_sources()] == ["alpha", "zeta"]

    def test_prune_source_pages_spans_parameter_chunks(self, db):
        # More exclusively-linked pages than one IN (...) statement may bind
        # on old SQLite builds; the deletes must run chunked.
        db.add_source(_source("notes"))
        urls = [f"https://example.com/{i}" for i in range(501)]
        for url in urls:
            db.upsert(_page(url))
        db.replace_links_for_files(
            ["/vault/notes/x.md"],
            [(url, "/vault/notes/x.md", "notes", "t1") for url in urls],
        )
        slugs = db.prune_source_pages("notes")
        assert len(slugs) == 501
        assert db.count() == 0
        assert _link_rows(db) == []


class TestPrune:
    def _seed(self, db):
        # parsed (kept by everything but "all")
        db.upsert(_page("https://a.com/ok", parsed_at="2026-06-11T00:00:00"))
        # failed and still indexed (a link points at it)
        db.upsert(_page("https://a.com/failed-linked", fail_reason="timeout"))
        db.replace_links_for_files(
            ["/notes/a.md"],
            [("https://a.com/failed-linked", "/notes/a.md", None, "2026-06-11")],
        )
        # failed and no longer indexed (no link)
        db.upsert(
            _page(
                "https://a.com/failed-orphan",
                fail_reason="too short (3 words from 1 KB html)",
            )
        )

    def test_missing_drops_only_unlinked_failures(self, db):
        self._seed(db)
        slugs = db.prune_pages("missing")
        assert slugs == [slug_for_url("https://a.com/failed-orphan")]
        assert set(db.get_all_urls()) == {
            "https://a.com/ok",
            "https://a.com/failed-linked",
        }

    def test_failed_drops_all_failures_and_their_links(self, db):
        self._seed(db)
        slugs = db.prune_pages("failed")
        assert set(slugs) == {
            slug_for_url("https://a.com/failed-linked"),
            slug_for_url("https://a.com/failed-orphan"),
        }
        assert db.get_all_urls() == ["https://a.com/ok"]
        # the link to the deleted page is gone too (FK has no cascade)
        assert _link_rows(db) == []

    def test_all_drops_everything(self, db):
        self._seed(db)
        slugs = db.prune_pages("all")
        assert len(slugs) == 3
        assert db.get_all_urls() == []

    def test_dry_run_deletes_nothing(self, db):
        self._seed(db)
        before = set(db.get_all_urls())
        slugs = db.prune_pages("failed", dry_run=True)
        assert set(slugs) == {
            slug_for_url("https://a.com/failed-linked"),
            slug_for_url("https://a.com/failed-orphan"),
        }
        assert set(db.get_all_urls()) == before

    def test_invalid_mode_raises(self, db):
        with pytest.raises(ValueError):
            db.prune_pages("everything")
