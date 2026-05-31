"""Tests for the SQLite-backed PageDatabase."""

import pytest

from clotho.db import Page, PageDatabase


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

    def test_url_exists(self, db):
        db.upsert(_page("https://example.com/a"))
        assert db.url_exists("https://example.com/a")
        assert not db.url_exists("https://example.com/missing")


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


class TestSources:
    def test_rebuild_and_get_sources(self, db):
        db.upsert(_page("https://example.com/a"))
        db.rebuild_sources({"https://example.com/a": ["note1.md", "note2.md"]})
        assert db.get_sources("https://example.com/a") == ["note1.md", "note2.md"]

    def test_get_urls_for_note(self, db):
        db.upsert(_page("https://example.com/a"))
        db.upsert(_page("https://example.com/b"))
        db.rebuild_sources(
            {
                "https://example.com/a": ["daily.md"],
                "https://example.com/b": ["daily.md"],
            }
        )
        urls = db.get_urls_for_note("daily.md")
        assert set(urls) == {"https://example.com/a", "https://example.com/b"}

    def test_rebuild_replaces_old_sources(self, db):
        db.upsert(_page("https://example.com/a"))
        db.rebuild_sources({"https://example.com/a": ["old.md"]})
        db.rebuild_sources({"https://example.com/a": ["new.md"]})
        assert db.get_sources("https://example.com/a") == ["new.md"]


class TestPruning:
    def test_prune_removes_stale_failures(self, db):
        db.upsert(
            _page("https://example.com/gone", fetched=False, fail_reason="timeout")
        )
        db.upsert(
            _page("https://example.com/kept", fetched=False, fail_reason="timeout")
        )
        pruned = db.prune_orphans({"https://example.com/kept"})
        assert pruned == 1
        assert not db.url_exists("https://example.com/gone")
        assert db.url_exists("https://example.com/kept")

    def test_prune_never_touches_fetched_pages(self, db):
        db.upsert(_page("https://example.com/archived", fetched=True))
        pruned = db.prune_orphans(set())
        assert pruned == 0
        assert db.url_exists("https://example.com/archived")

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
        assert db.url_exists("https://example.com/a")
