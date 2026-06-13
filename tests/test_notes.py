"""Tests for note reading and URL extraction (the index stage's input)."""

import pytest

from arciv.notes import MarkdownNote, Note, load_note, load_notes


@pytest.fixture
def make_note(tmp_path):
    """Factory writing a markdown note to disk and returning a MarkdownNote."""

    def _make(body: str, name: str = "note.md") -> MarkdownNote:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return MarkdownNote(path)

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


class TestNoteContent:
    def test_frontmatter_is_stripped(self, make_note):
        note = make_note(
            "---\ntags: [daily]\nurl: https://frontmatter.example.com\n---\n"
            "# Daily\nhttps://example.com/real"
        )
        assert note.extract_urls() == ["https://example.com/real"]

    def test_content_before_first_h1_is_ignored(self, make_note):
        note = make_note(
            "preamble https://example.com/preamble\n# Heading\nhttps://example.com/body"
        )
        assert note.extract_urls() == ["https://example.com/body"]

    def test_non_markdown_file_is_rejected(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("text", encoding="utf-8")
        with pytest.raises(ValueError):
            MarkdownNote(path)


class TestLoadNotes:
    def test_load_note_dispatches_by_extension(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text("# Title\ntext", encoding="utf-8")
        txt = tmp_path / "note.txt"
        txt.write_text("text", encoding="utf-8")

        assert isinstance(load_note(md), MarkdownNote)
        assert type(load_note(txt)) is Note

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
