"""Tests for the archive orchestration (index -> batch fetch -> parse).

The real fetch launches a browser, so these replace ``fetch_urls`` and
``parse_pending`` in the archive module with fakes and assert the wiring:
URLs are fetched as one batch, parse runs after, and a source is indexed
before its URLs are archived.
"""

import pytest

import arciv.core.pipeline.archive_pipeline as archive_module
from arciv.core.db import Page, PageDatabase, Source
from arciv.core.urls import slug_for_url
from arciv.core.pipeline import archive_source, archive_urls


@pytest.fixture
def db(tmp_path):
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


def _page(url: str, **overrides) -> Page:
    defaults = dict(original_url=url, domain="example.com", slug=slug_for_url(url))
    defaults.update(overrides)
    return Page(url=url, **defaults)


def test_archive_urls_batches_fetch_then_parses(db, monkeypatch):
    calls = {}

    def fake_fetch_urls(database, urls, refetch=False):
        calls["fetch"] = (list(urls), refetch)
        return [_page(u, fetched_at="t") for u in urls]

    def fake_parse_pending(database):
        calls["parse"] = True
        return 2

    monkeypatch.setattr(archive_module, "fetch_urls", fake_fetch_urls)
    monkeypatch.setattr(archive_module, "parse_pending", fake_parse_pending)

    urls = ["https://a.com/1", "https://a.com/2"]
    result = archive_urls(db, urls)

    # One batch of all URLs, then a single parse pass.
    assert calls["fetch"] == (urls, False)
    assert calls["parse"] is True
    assert result.urls == urls
    assert len(result.fetched) == 2
    assert result.parsed == 2


def test_archive_source_indexes_then_archives(db, tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("[x](https://example.com/post)", encoding="utf-8")
    db.add_source(Source("notes", str(notes), "2026-06-11T00:00:00+00:00"))

    captured = {}

    def fake_fetch_urls(database, urls, refetch=False):
        captured["urls"] = list(urls)
        return [_page(u, fetched_at="t") for u in urls]

    monkeypatch.setattr(archive_module, "fetch_urls", fake_fetch_urls)
    monkeypatch.setattr(archive_module, "parse_pending", lambda database: 1)

    result = archive_source(db, "notes")

    # The note's link was indexed (and attributed to the source) before fetch.
    assert captured["urls"] == ["https://example.com/post"]
    attributed = db._conn.execute(
        "SELECT url FROM links WHERE source_name = 'notes'"
    ).fetchall()
    assert [row["url"] for row in attributed] == ["https://example.com/post"]
    assert result.parsed == 1


def test_archive_source_unknown_raises(db):
    with pytest.raises(KeyError):
        archive_source(db, "ghost")
