"""Tests for note reading and URL extraction (the index stage's input)."""

import pytest

from clotho.notes import MarkdownNote


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
