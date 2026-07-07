"""Tests for link extraction (``arciv.core.index.links``): both extractors.

extract_urls scans note text with regexes. extract_links runs on any
Scrapling Selector-family object with a base URL, so its tests feed it a
Selector built from raw HTML — same code path as a live Response, no
network.
"""

from scrapling.parser import Selector

from arciv.core.index import extract_links, extract_urls


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


def _page(html: str, url: str = "https://book.example.com/toc") -> Selector:
    return Selector(f"<html><body>{html}</body></html>", url=url)


class TestExtractLinks:
    def test_relative_links_resolve_against_base(self):
        page = _page('<a href="/ch1">one</a><a href="ch2.html">two</a>')
        assert extract_links(page) == [
            "https://book.example.com/ch1",
            "https://book.example.com/ch2.html",
        ]

    def test_absolute_links_kept(self):
        page = _page('<a href="https://other.example.com/post">x</a>')
        assert extract_links(page) == ["https://other.example.com/post"]

    def test_pdf_links_survive(self):
        # LinkExtractor's default deny_extensions drops .pdf; papers are
        # exactly what arciv archives, so the extractor must keep them.
        page = _page('<a href="https://arxiv.org/pdf/2305.14406.pdf">paper</a>')
        assert extract_links(page) == ["https://arxiv.org/pdf/2305.14406.pdf"]

    def test_duplicates_collapse_preserving_order(self):
        page = _page('<a href="/ch1">a</a><a href="/ch2">b</a><a href="/ch1">again</a>')
        assert extract_links(page) == [
            "https://book.example.com/ch1",
            "https://book.example.com/ch2",
        ]

    def test_non_web_schemes_dropped(self):
        page = _page(
            '<a href="mailto:me@example.com">mail</a>'
            '<a href="javascript:void(0)">js</a>'
            '<a href="/real">real</a>'
        )
        assert extract_links(page) == ["https://book.example.com/real"]

    def test_no_links_yields_empty_list(self):
        assert extract_links(_page("<p>plain prose, no anchors</p>")) == []
