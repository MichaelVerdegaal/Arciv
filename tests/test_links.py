"""Tests for live-page link discovery (the ``get --no-save`` engine).

extract_links runs on any Scrapling Selector-family object with a base URL,
so these tests feed it a Selector built from raw HTML — same code path as a
live Response, no network.
"""

from scrapling.parser import Selector

from arciv.core.fetch import extract_links


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
