"""Tests for note reading and URL extraction (the index stage's input)."""

import pytest

from arciv.core.notes import extract_urls, find_notes, read_note


class TestExtractUrls:
    def test_markdown_link(self):
        text = "Read [this post](https://example.com/post) today."
        assert extract_urls(text) == ["https://example.com/post"]

    def test_bare_url(self):
        text = "See https://example.com/article for details."
        assert extract_urls(text) == ["https://example.com/article"]

    def test_markdown_link_with_trailing_junk(self):
        # The closing paren must not drag following text into the URL
        text = "[link](https://example.com/post)seasonalities"
        assert extract_urls(text) == ["https://example.com/post"]

    def test_balanced_parens_in_url_kept(self):
        url = "https://en.wikipedia.org/wiki/Leakage_(machine_learning)"
        assert extract_urls(f"About {url} and more.") == [url]

    def test_concatenated_urls_are_split(self):
        assert extract_urls("https://example.com/ahttps://example.com/b") == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_trailing_punctuation_stripped_from_bare_url(self):
        assert extract_urls("Check https://example.com/post.") == [
            "https://example.com/post"
        ]

    def test_no_urls_returns_empty(self):
        assert extract_urls("Just a note without links.") == []

    def test_bare_url_strips_unbalanced_trailing_paren(self):
        # A bare URL wrapped in prose parens: the opening "(" isn't part of
        # the URL, so the trailing ")" is unbalanced and must be dropped.
        assert extract_urls("see (https://example.com/post) here") == [
            "https://example.com/post"
        ]


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
