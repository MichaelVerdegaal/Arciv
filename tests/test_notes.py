"""Tests for note reading (the index stage's file input)."""

import pytest

from arciv.core.index import extract_urls
from arciv.core.notes import find_notes, read_note


class TestReadNote:
    def test_reads_text(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("body text", encoding="utf-8")
        assert read_note(path) == "body text"

    def test_strips_yaml_frontmatter(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("---\ntags: [x]\n---\nreal body", encoding="utf-8")
        assert read_note(path) == "real body"

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_note(tmp_path / "does-not-exist.md")

    def test_directory_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            read_note(tmp_path)

    def test_non_utf8_raises_decode_error(self, tmp_path):
        path = tmp_path / "latin1.txt"
        path.write_bytes("caf\xe9 https://example.com/a".encode("latin-1"))
        with pytest.raises(UnicodeDecodeError):
            read_note(path)


class TestFindNotes:
    def test_finds_supported_files_recursively(self, tmp_path):
        (tmp_path / "a.md").write_text("# A", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.rst").write_text("c", encoding="utf-8")
        (tmp_path / "ignored.pdf").write_text("nope", encoding="utf-8")

        assert [p.name for p in find_notes(tmp_path)] == ["a.md", "b.txt", "c.rst"]

    def test_txt_and_rst_notes_extract_urls(self, tmp_path):
        (tmp_path / "note.txt").write_text(
            "See https://example.com/article today.", encoding="utf-8"
        )
        (tmp_path / "note.rst").write_text(
            "Heading\n=======\n\nSee https://example.com/docs here.",
            encoding="utf-8",
        )
        urls = [
            url
            for path in find_notes(tmp_path)
            for url in extract_urls(read_note(path))
        ]
        assert sorted(urls) == [
            "https://example.com/article",
            "https://example.com/docs",
        ]
