"""Tests for the index stage (link extraction into the database)."""

import pytest

from arciv.core.db import PageDatabase, Source
from arciv.core.index import (
    index_all,
    index_directory,
    index_file,
    index_source,
    register_urls,
)


@pytest.fixture
def db(tmp_path):
    """A fresh database backed by a temp file, closed after the test."""
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


def _write_note(directory, name: str, body: str):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _link_rows(db) -> list[tuple[str, str, str | None]]:
    """(url, file_path, source_name) link rows, read straight from the table
    since links have no public read API (test observation only)."""
    rows = db._conn.execute(
        "SELECT url, file_path, source_name FROM links ORDER BY file_path, url"
    ).fetchall()
    return [(row["url"], row["file_path"], row["source_name"]) for row in rows]


class TestIndexFile:
    def test_registers_pending_pages(self, db, tmp_path):
        note = _write_note(
            tmp_path, "daily.md", "Read [this](https://example.com/post) today."
        )
        urls = index_file(db, note)
        assert urls == ["https://example.com/post"]
        page = db.get("https://example.com/post")
        assert page is not None
        assert page.fetched is False

    def test_stores_normalized_path_and_timestamp(self, db, tmp_path):
        note = _write_note(tmp_path, "daily.md", "https://example.com/post")
        index_file(db, note)
        assert _link_rows(db) == [
            ("https://example.com/post", str(note.resolve()), None)
        ]

    def test_reindex_drops_removed_links(self, db, tmp_path):
        note = _write_note(tmp_path, "daily.md", "https://example.com/old")
        index_file(db, note)
        note.write_text("https://example.com/new", encoding="utf-8")
        index_file(db, note)
        assert _link_rows(db) == [
            ("https://example.com/new", str(note.resolve()), None)
        ]


class TestIndexDirectory:
    def test_indexes_all_markdown_files_recursively(self, db, tmp_path):
        _write_note(tmp_path, "a.md", "https://example.com/a")
        _write_note(tmp_path, "sub/b.md", "https://example.com/b")
        urls = index_directory(db, tmp_path)
        assert set(urls) == {"https://example.com/a", "https://example.com/b"}

    def test_same_url_in_two_files_yields_two_link_rows(self, db, tmp_path):
        _write_note(tmp_path, "a.md", "https://example.com/shared")
        _write_note(tmp_path, "b.md", "https://example.com/shared")
        urls = index_directory(db, tmp_path)
        assert urls == ["https://example.com/shared"]
        assert len(_link_rows(db)) == 2


class TestIndexSource:
    def test_indexes_registered_directory(self, db, tmp_path):
        _write_note(tmp_path, "a.md", "https://example.com/a")
        db.add_source(Source(name="notes", path=str(tmp_path), added_at="t"))
        urls = index_source(db, "notes")
        assert urls == ["https://example.com/a"]

    def test_links_are_attributed_to_the_source(self, db, tmp_path):
        _write_note(tmp_path, "a.md", "https://example.com/a")
        db.add_source(Source(name="notes", path=str(tmp_path), added_at="t"))
        index_source(db, "notes")
        assert [(url, name) for url, _, name in _link_rows(db)] == [
            ("https://example.com/a", "notes")
        ]

    def test_adhoc_directory_links_have_no_source(self, db, tmp_path):
        _write_note(tmp_path, "a.md", "https://example.com/a")
        db.add_source(Source(name="notes", path=str(tmp_path), added_at="t"))
        index_directory(db, tmp_path)  # ad-hoc, not via the source
        assert [(url, name) for url, _, name in _link_rows(db)] == [
            ("https://example.com/a", None)
        ]

    def test_unknown_source_raises(self, db):
        with pytest.raises(KeyError):
            index_source(db, "nope")

    def test_index_all_covers_every_source(self, db, tmp_path):
        dir_a, dir_b = tmp_path / "a", tmp_path / "b"
        _write_note(dir_a, "x.md", "https://example.com/a")
        _write_note(dir_b, "y.md", "https://example.com/b")
        db.add_source(Source(name="a", path=str(dir_a), added_at="t"))
        db.add_source(Source(name="b", path=str(dir_b), added_at="t"))
        urls = index_all(db)
        assert set(urls) == {"https://example.com/a", "https://example.com/b"}


class TestRegisterUrls:
    def test_registers_direct_url_without_link_row(self, db):
        urls = register_urls(db, ["https://example.com/direct"])
        assert urls == ["https://example.com/direct"]
        assert db.get("https://example.com/direct") is not None
        assert _link_rows(db) == []

    def test_skipped_urls_are_excluded(self, db):
        urls = register_urls(db, ["https://example.com/image.png"])
        assert urls == []
        assert db.count() == 0
