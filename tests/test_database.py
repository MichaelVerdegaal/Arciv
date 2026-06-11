"""Tests for the SQLite-backed PageDatabase."""

import pytest

from clotho.db import Page, PageDatabase, Source


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
        fetched=True,
        word_count=500,
    )
    defaults.update(overrides)
    return Page(url=url, **defaults)


def _source(name: str = "notes", path: str = "/vault/notes") -> Source:
    return Source(name=name, path=path, added_at="2026-06-11T00:00:00+00:00")


class TestCrud:
    def test_upsert_and_get(self, db):
        page = _page("https://example.com/a", title="Hello")
        db.upsert(page)
        fetched = db.get("https://example.com/a")
        assert fetched is not None
        assert fetched.title == "Hello"
        assert fetched.fetched is True

    def test_get_missing_returns_none(self, db):
        assert db.get("https://nope.com") is None

    def test_upsert_updates_existing(self, db):
        db.upsert(_page("https://example.com/a", word_count=100))
        db.upsert(_page("https://example.com/a", word_count=999))
        assert db.get("https://example.com/a").word_count == 999
        assert db.count() == 1

    def test_count(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        assert db.count() == 2

    def test_ensure_pages_inserts_new(self, db):
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
        assert db.get("https://example.com/a") is not None

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


class TestQueries:
    def test_get_unfetched(self, db):
        db.upsert(_page("https://example.com/ok", fetched=True))
        db.upsert(
            _page("https://example.com/bad", fetched=False, fail_reason="timeout")
        )
        db.upsert(_page("https://example.com/pending", fetched=False))
        unfetched_urls = {p.url for p in db.get_unfetched()}
        assert "https://example.com/ok" not in unfetched_urls
        assert "https://example.com/pending" in unfetched_urls

    def test_get_all(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        assert len(db.get_all()) == 2

    def test_fail_summary(self, db):
        db.upsert(
            _page(
                "https://a.com/1", domain="a.com", fetched=False, fail_reason="timeout"
            )
        )
        db.upsert(
            _page(
                "https://a.com/2", domain="a.com", fetched=False, fail_reason="timeout"
            )
        )
        summary = db.fail_summary()
        assert ("a.com", "timeout", 2) in summary


class TestLinks:
    def test_replace_and_get_files_for_url(self, db):
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/note1.md", "/vault/note2.md"],
            [
                ("https://example.com/a", "/vault/note1.md", "2026-06-11T00:00:00"),
                ("https://example.com/a", "/vault/note2.md", "2026-06-11T00:00:00"),
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
                ("https://example.com/a", "/vault/daily.md", "2026-06-11T00:00:00"),
                ("https://example.com/b", "/vault/daily.md", "2026-06-11T00:00:00"),
            ],
        )
        urls = db.get_urls_for_file("/vault/daily.md")
        assert set(urls) == {"https://example.com/a", "https://example.com/b"}

    def test_reindex_replaces_links_of_same_file(self, db):
        db.upsert(_page("https://example.com/old"))
        db.upsert(_page("https://example.com/new"))
        db.replace_links_for_files(
            ["/vault/daily.md"],
            [("https://example.com/old", "/vault/daily.md", "t1")],
        )
        db.replace_links_for_files(
            ["/vault/daily.md"],
            [("https://example.com/new", "/vault/daily.md", "t2")],
        )
        assert db.get_urls_for_file("/vault/daily.md") == ["https://example.com/new"]

    def test_reindex_leaves_other_files_alone(self, db):
        db.upsert(_page("https://example.com/a"))
        db.replace_links_for_files(
            ["/vault/one.md"],
            [("https://example.com/a", "/vault/one.md", "t1")],
        )
        db.replace_links_for_files(
            ["/vault/two.md"],
            [("https://example.com/a", "/vault/two.md", "t2")],
        )
        assert db.get_files_for_url("https://example.com/a") == [
            "/vault/one.md",
            "/vault/two.md",
        ]


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

    def test_list_sources_ordered_by_name(self, db):
        db.add_source(_source(name="zeta", path="/z"))
        db.add_source(_source(name="alpha", path="/a"))
        assert [s.name for s in db.list_sources()] == ["alpha", "zeta"]
