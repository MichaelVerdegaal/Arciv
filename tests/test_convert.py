"""Tests for HTML-to-markdown conversion and metadata extraction."""

import itertools

from arciv.core.parse.parser import (
    ConversionResult,
    code_inclusive_word_count,
    count_words,
    extract_metadata,
    html_to_markdown,
    parse_html,
)

# trafilatura keeps a global LRU and discards paragraphs it has seen before
# (deduplicate=True). Each test therefore needs unique body text.
_counter = itertools.count()


def _article(title: str = "My Title") -> str:
    tag = f"uniq{next(_counter)}"
    return (
        f"<html><head><title>{title}</title></head><body>"
        "<article><h1>Heading</h1>"
        f"<p>{(tag + ' ') * 60}</p>"
        "<pre><code>print('hello from code block')</code></pre>"
        f"<p>{(tag + 'b ') * 60}</p>"
        "</article></body></html>"
    )


class TestCountWords:
    def test_counts_words(self):
        assert count_words("one two three") == 3

    def test_empty_is_zero(self):
        assert count_words("") == 0

    def test_punctuation_not_counted(self):
        assert count_words("hello, world!") == 2


class TestHtmlToMarkdown:
    def test_basic_extraction(self):
        md = html_to_markdown(_article())
        assert md is not None
        assert "Heading" in md

    def test_strip_code_removes_code_blocks(self):
        md = html_to_markdown(_article(), strip_code=True)
        assert md is not None
        assert "print('hello from code block')" not in md

    def test_keep_code_preserves_code_blocks(self):
        md = html_to_markdown(_article(), strip_code=False)
        assert md is not None
        assert "hello from code block" in md

    def test_strip_code_yields_fewer_words(self):
        # The false-negative driver: stripping code lowers the word count,
        # which can push a real page below the length gate.
        html = _article()
        stripped = count_words(html_to_markdown(html, strip_code=True) or "")
        kept = count_words(html_to_markdown(html, strip_code=False) or "")
        assert kept >= stripped

    def test_next_data_script_is_removed(self):
        html = (
            "<html><body><article>"
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"leak": "</script> should not appear"}</script>'
            "<p>" + ("real " * 60) + "</p>"
            "</article></body></html>"
        )
        md = html_to_markdown(html)
        assert md is not None
        assert "should not appear" not in md

    def test_empty_returns_none(self):
        assert html_to_markdown("") is None

    def test_mediawiki_edit_links_dont_swallow_headings(self):
        # MediaWiki puts an "[edit]" link next to each heading inside a small
        # wrapper div; without pruning it, trafilatura's link-density check
        # deleted the whole div and every Wikipedia heading vanished.
        edit = (
            '<span class="mw-editsection">'
            '<span class="mw-editsection-bracket">[</span>'
            '<a href="/w/index.php?title=Moirai&amp;action=edit">'
            "<span>edit</span></a>"
            '<span class="mw-editsection-bracket">]</span></span>'
        )
        tag = f"uniq{next(_counter)}"
        html = (
            "<html><head><title>Moirai - Wikipedia</title></head><body>"
            '<main id="content" class="mw-body">'
            '<div id="bodyContent" class="vector-body">'
            '<div id="mw-content-text" class="mw-body-content">'
            '<div class="mw-content-ltr mw-parser-output">'
            f"<p>{(tag + 'a ') * 60}</p>"
            f'<div class="mw-heading mw-heading2"><h2 id="s1">Mythology</h2>{edit}</div>'
            f"<p>{(tag + 'b ') * 60}</p>"
            f'<div class="mw-heading mw-heading3"><h3 id="s2">Cult sites</h3>{edit}</div>'
            f"<p>{(tag + 'c ') * 60}</p>"
            "</div></div></div></main></body></html>"
        )
        md = html_to_markdown(html)
        assert md is not None
        assert "## Mythology" in md
        assert "### Cult sites" in md
        assert "[edit]" not in md


class TestExtractMetadata:
    def test_title_from_metadata(self):
        title, _ = extract_metadata(_article("My Title"))
        assert title == "My Title"

    def test_title_falls_back_to_title_tag(self):
        html = "<html><head><title>Fallback Title</title></head><body></body></html>"
        title, _ = extract_metadata(html)
        assert title == "Fallback Title"

    def test_missing_title_is_none(self):
        title, author = extract_metadata("<html><body></body></html>")
        assert title is None
        assert author is None


class TestParseHtml:
    def test_returns_conversion_result(self):
        # Unique body: trafilatura's deduplicate=True keeps a global LRU of
        # seen paragraphs, so reusing _ARTICLE here would be discarded.
        html = (
            "<html><head><title>Unique Title</title></head><body><article>"
            "<h1>Heading</h1><p>" + ("distinctword " * 80) + "</p>"
            "</article></body></html>"
        )
        result = parse_html(html)
        assert isinstance(result, ConversionResult)
        assert result.word_count > 0
        assert result.title == "Unique Title"

    def test_code_inclusive_count_exceeds_stripped_count(self):
        # Code-heavy page: most words live in the code block. The stored
        # word_count strips them, but the code-inclusive count keeps them so
        # the length gate doesn't wrongly reject the page as "too short".
        html = (
            "<html><head><title>Code Heavy</title></head><body><article>"
            "<p>Short intro paragraph here.</p>"
            "<pre><code>" + ("codetoken " * 200) + "</code></pre>"
            "</article></body></html>"
        )
        result = parse_html(html)
        assert result is not None
        assert code_inclusive_word_count(html) > result.word_count

    def test_returns_none_on_failure(self):
        assert parse_html("") is None

    def test_clean_flag_is_applied(self):
        # Inline code markers should be stripped when clean=True.
        html = (
            "<html><body><article>"
            "<p>Use the `config` flag " + ("padding " * 60) + "</p>"
            "</article></body></html>"
        )
        cleaned = parse_html(html, clean=True)
        assert cleaned is not None
        assert "`config`" not in cleaned.md_content
