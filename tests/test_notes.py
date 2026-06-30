"""Tests for note reading and URL extraction (the index stage's input)."""

import pytest

from arciv.core.notes import Note, load_note, load_notes


@pytest.fixture
def make_note(tmp_path):
    """Factory writing a note to disk and returning a Note."""

    def _make(body: str, name: str = "note.txt") -> Note:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return Note(path)

    return _make


class TestExtractUrls:
    def test_markdown_link(self, make_note):
        note = make_note("Read [this post](https://example.com/post) today.")
        assert note.extract_urls() == ["https://example.com/post"]

    def test_bare_url(self, make_note):
        note = make_note("See https://example.com/article for details.")
        assert note.extract_urls() == ["https://example.com/article"]

    def test_markdown_link_with_trailing_junk(self, make_note):
        # The closing paren must not drag following text into the URL
        note = make_note("[link](https://example.com/post)seasonalities")
        assert note.extract_urls() == ["https://example.com/post"]

    def test_balanced_parens_in_url_kept(self, make_note):
        url = "https://en.wikipedia.org/wiki/Leakage_(machine_learning)"
        note = make_note(f"About {url} and more.")
        assert note.extract_urls() == [url]

    def test_concatenated_urls_are_split(self, make_note):
        note = make_note("https://example.com/ahttps://example.com/b")
        assert note.extract_urls() == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_trailing_punctuation_stripped_from_bare_url(self, make_note):
        note = make_note("Check https://example.com/post.")
        assert note.extract_urls() == ["https://example.com/post"]

    def test_no_urls_returns_empty(self, make_note):
        note = make_note("Just a note without links.")
        assert note.extract_urls() == []

    def test_bare_url_strips_unbalanced_trailing_paren(self, make_note):
        # A bare URL wrapped in prose parens: the opening "(" isn't part of
        # the URL, so the trailing ")" is unbalanced and must be dropped.
        note = make_note("see (https://example.com/post) here")
        assert note.extract_urls() == ["https://example.com/post"]


class TestNoteErrors:
    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Note(tmp_path / "does-not-exist.md")

    def test_unreadable_path_raises_ioerror(self, tmp_path):
        # A directory passes the exists() check but can't be read as text.
        with pytest.raises(IOError):
            Note(tmp_path)

    def test_repr_shows_filename_and_extension(self, make_note):
        note = make_note("body", name="daily.md")
        assert repr(note) == "Note(daily.md)"


class TestLoadNotes:
    def test_txt_note_extracts_urls(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("See https://example.com/article today.", encoding="utf-8")
        assert load_note(path).extract_urls() == ["https://example.com/article"]

    def test_rst_note_extracts_urls(self, tmp_path):
        path = tmp_path / "note.rst"
        path.write_text(
            "Heading\n=======\n\nSee https://example.com/docs here.",
            encoding="utf-8",
        )
        assert load_note(path).extract_urls() == ["https://example.com/docs"]

    def test_load_notes_finds_supported_files_recursively(self, tmp_path):
        (tmp_path / "a.md").write_text("# A", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.rst").write_text("c", encoding="utf-8")
        (tmp_path / "ignored.pdf").write_text("nope", encoding="utf-8")

        notes = load_notes(tmp_path)
        assert sorted(n.filename + n.extension for n in notes) == [
            "a.md",
            "b.txt",
            "c.rst",
        ]
