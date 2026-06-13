"""Tests for the SQLite-backed PageDatabase."""

import pytest

from arciv.db import Page, PageDatabase, Source


@pytest.fixture
def db(tmp_path):
    """A fresh database backed by a temp file, closed after the test."""
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


def _page(url: str, **overrides) -> Page:
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug="example.com-abc12345",
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
        import sqlite3

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
