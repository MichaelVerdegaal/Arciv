"""Tests for the SQLite-backed PageDatabase."""

import sqlite3

import pytest

from arciv.db import Page, PageDatabase, Source
from arciv.scrape import slug_for_url


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
    def test_get_unfetched_is_pending_only(self, db):
        db.upsert(_page("https://example.com/fetched"))
        db.upsert(
            _page("https://example.com/failed", fetched_at=None, fail_reason="timeout")
        )
        db.upsert(_page("https://example.com/pending", fetched_at=None))
        assert {p.url for p in db.get_unfetched()} == {"https://example.com/pending"}

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

    def test_get_all(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        assert len(db.get_all()) == 2

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


class TestLinks:
    def test_replace_and_get_files_for_url(self, db):
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/note1.md", "/vault/note2.md"],
            [
                ("https://example.com/a", "/vault/note1.md", None, "t1"),
                ("https://example.com/a", "/vault/note2.md", None, "t1"),
            ],
        )
        assert db.get_files_for_url("https://example.com/a") == [
            "/vault/note1.md",
            "/vault/note2.md",
        ]

    def test_get_urls_for_file(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        db.replace_links_for_files(
            ["/vault/daily.md"],
            [
                ("https://example.com/a", "/vault/daily.md", None, "t1"),
                ("https://example.com/b", "/vault/daily.md", None, "t1"),
            ],
        )
        urls = db.get_urls_for_file("/vault/daily.md")
        assert set(urls) == {"https://example.com/a", "https://example.com/b"}

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
        assert db.get_urls_for_file("/vault/daily.md") == ["https://example.com/new"]

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
        assert db.get_files_for_url("https://example.com/a") == [
            "/vault/one.md",
            "/vault/two.md",
        ]

    def test_get_urls_for_source(self, db):
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
        assert db.get_urls_for_source("notes") == ["https://example.com/a"]

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
        assert db.get_files_for_url("https://example.com/a") == ["/vault/notes/x.md"]
        assert db.get_urls_for_source("notes") == []

    def test_list_sources_ordered_by_name(self, db):
        db.add_source(_source(name="zeta", path="/z"))
        db.add_source(_source(name="alpha", path="/a"))
        assert [s.name for s in db.list_sources()] == ["alpha", "zeta"]


class TestPageState:
    def test_parsed_page_is_done(self):
        page = _page("https://x.com/a", parsed_at="2026-06-11T00:00:00")
        assert page.state == "done"

    def test_fetch_failure_is_failed(self):
        page = _page("https://x.com/a", fetched_at=None, fail_reason="timeout")
        assert page.state == "failed"

    def test_parse_rejection_is_failed(self):
        # fetched but rejected: fetched_at set AND fail_reason set
        page = _page("https://x.com/a", fail_reason="too short")
        assert page.state == "failed"

    def test_unfetched_is_pending(self):
        assert _page("https://x.com/a", fetched_at=None).state == "pending"

    def test_awaiting_parse_is_pending(self):
        # fetched, not yet parsed, no failure
        assert _page("https://x.com/a").state == "pending"


class TestGetBySlug:
    def test_returns_page_with_matching_slug(self, db):
        db.upsert(_page("https://example.com/a", slug="example.com-slugaaaa"))
        found = db.get_by_slug("example.com-slugaaaa")
        assert found is not None
        assert found.url == "https://example.com/a"

    def test_unknown_slug_returns_none(self, db):
        assert db.get_by_slug("nope-00000000") is None


class TestListPages:
    def _seed_mixed(self, db):
        db.upsert(
            _page(
                "https://a.com/parsed",
                domain="a.com",
                fetched_at="2026-06-02T00:00:00",
                parsed_at="2026-06-11T00:00:00",
                word_count=300,
            )
        )
        db.upsert(_page("https://a.com/pending", domain="a.com", fetched_at=None))
        db.upsert(
            _page(
                "https://b.com/failed",
                domain="b.com",
                fetched_at=None,
                fail_reason="timeout",
            )
        )

    def test_includes_pending_and_failed(self, db):
        self._seed_mixed(db)
        assert {p.url for p in db.list_pages()} == {
            "https://a.com/parsed",
            "https://a.com/pending",
            "https://b.com/failed",
        }

    def test_status_done(self, db):
        self._seed_mixed(db)
        assert [p.url for p in db.list_pages(status="done")] == ["https://a.com/parsed"]

    def test_status_failed(self, db):
        self._seed_mixed(db)
        assert [p.url for p in db.list_pages(status="failed")] == [
            "https://b.com/failed"
        ]

    def test_status_pending(self, db):
        self._seed_mixed(db)
        assert [p.url for p in db.list_pages(status="pending")] == [
            "https://a.com/pending"
        ]

    def test_status_filter_matches_page_state(self, db):
        # The SQL filter and Page.state are one definition: every row a
        # status returns must report that same state.
        self._seed_mixed(db)
        for status in ("done", "failed", "pending"):
            for page in db.list_pages(status=status):
                assert page.state == status

    def test_domain_filter(self, db):
        self._seed_mixed(db)
        assert {p.url for p in db.list_pages(domain="a.com")} == {
            "https://a.com/parsed",
            "https://a.com/pending",
        }

    def test_sort_by_word_count_desc(self, db):
        db.upsert(_page("https://x.com/lo", word_count=10))
        db.upsert(_page("https://x.com/hi", word_count=900))
        db.upsert(_page("https://x.com/mid", word_count=100))
        ordered = [p.url for p in db.list_pages(sort="word_count", order="desc")]
        assert ordered == ["https://x.com/hi", "https://x.com/mid", "https://x.com/lo"]

    def test_sort_by_title_asc(self, db):
        db.upsert(_page("https://x.com/b", title="Banana"))
        db.upsert(_page("https://x.com/a", title="Apple"))
        ordered = [p.title for p in db.list_pages(sort="title", order="asc")]
        assert ordered == ["Apple", "Banana"]

    def test_limit_and_offset_page_through_results(self, db):
        for i in range(5):
            db.upsert(_page(f"https://x.com/{i}", word_count=i))
        page1 = db.list_pages(sort="word_count", order="asc", limit=2, offset=0)
        page2 = db.list_pages(sort="word_count", order="asc", limit=2, offset=2)
        assert [p.word_count for p in page1] == [0, 1]
        assert [p.word_count for p in page2] == [2, 3]

    def test_invalid_sort_raises(self, db):
        with pytest.raises(ValueError):
            db.list_pages(sort="url; DROP TABLE pages")

    def test_invalid_order_raises(self, db):
        with pytest.raises(ValueError):
            db.list_pages(order="sideways")

    def test_invalid_status_raises(self, db):
        with pytest.raises(ValueError):
            db.list_pages(status="bogus")


class TestDomainCounts:
    def test_counts_pages_per_domain_biggest_first(self, db):
        db.upsert(_page("https://a.com/1", domain="a.com"))
        db.upsert(_page("https://a.com/2", domain="a.com"))
        db.upsert(_page("https://b.com/1", domain="b.com"))
        assert db.domain_counts() == [("a.com", 2), ("b.com", 1)]

    def test_counts_every_state_not_just_done(self, db):
        db.upsert(_page("https://a.com/done", domain="a.com"))
        db.upsert(_page("https://a.com/pending", domain="a.com", fetched_at=None))
        db.upsert(
            _page(
                "https://a.com/failed",
                domain="a.com",
                fetched_at=None,
                fail_reason="x",
            )
        )
        assert db.domain_counts() == [("a.com", 3)]

    def test_empty_db_is_empty(self, db):
        assert db.domain_counts() == []


class TestListSourcesWithCounts:
    def test_counts_distinct_pages_per_source(self, db):
        db.add_source(_source("notes", "/vault/notes"))
        db.upsert(_page("https://a.com/1"))
        db.upsert(_page("https://a.com/2"))
        db.replace_links_for_files(
            ["/vault/notes/x.md", "/vault/notes/y.md"],
            [
                ("https://a.com/1", "/vault/notes/x.md", "notes", "t1"),
                # the same URL from a second file must not be double-counted
                ("https://a.com/1", "/vault/notes/y.md", "notes", "t1"),
                ("https://a.com/2", "/vault/notes/y.md", "notes", "t1"),
            ],
        )
        result = db.list_sources_with_counts()
        assert len(result) == 1
        source, count = result[0]
        assert source.name == "notes"
        assert source.path == "/vault/notes"
        assert count == 2

    def test_source_with_no_links_counts_zero(self, db):
        db.add_source(_source("empty", "/vault/empty"))
        assert db.list_sources_with_counts() == [(_source("empty", "/vault/empty"), 0)]

    def test_ordered_by_name(self, db):
        db.add_source(_source("zeta", "/z"))
        db.add_source(_source("alpha", "/a"))
        assert [s.name for s, _ in db.list_sources_with_counts()] == ["alpha", "zeta"]


class TestReadOnly:
    def test_reads_data_written_by_the_writer(self, tmp_path):
        db_path = tmp_path / "arciv.db"
        with PageDatabase(db_path) as writer:
            writer.upsert(_page("https://example.com/a", title="Hello"))
            # Open the reader while the writer (and its WAL) is live, the way
            # the backend reads alongside the running CLI.
            with PageDatabase(db_path, read_only=True) as reader:
                page = reader.get("https://example.com/a")
                assert page is not None
                assert page.title == "Hello"

    def test_read_only_connection_rejects_writes(self, tmp_path):
        db_path = tmp_path / "arciv.db"
        with PageDatabase(db_path):
            pass  # create the database file and schema
        with PageDatabase(db_path, read_only=True) as reader:
            with pytest.raises(sqlite3.OperationalError):
                reader.upsert(_page("https://example.com/a"))

    def test_read_only_open_does_not_create_a_missing_file(self, tmp_path):
        db_path = tmp_path / "missing.db"
        with pytest.raises(sqlite3.OperationalError):
            PageDatabase(db_path, read_only=True)
        assert not db_path.exists()
