"""Tests for the crawl orchestration (depth-limited BFS over the batch pipeline).

The real fetch launches a browser, so ``fetch_urls`` is replaced with a fake
that writes ``page.html`` files to a temp saved dir and records success in
the database, mirroring what the Fetcher does. The crawl then reads those
files back to build the next frontier, exactly as in production.
"""

import pytest

import arciv.core.pipeline.archive_pipeline as archive_module
import arciv.core.pipeline.crawl_pipeline as crawl_module
from arciv.core.clock import utc_now_iso
from arciv.core.db import Page, PageDatabase
from arciv.core.pipeline import crawl_urls
from arciv.core.urls import registered_domain, slug_for_url


@pytest.fixture
def db(tmp_path):
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def saved_dir(tmp_path, monkeypatch):
    saved = tmp_path / "saved"
    monkeypatch.setattr(crawl_module, "SAVED_DIR", saved)
    return saved


@pytest.fixture
def fake_fetch(db, saved_dir, monkeypatch):
    """Replace the fetch/parse batch with a fake that archives canned HTML.

    Returns the dict to fill with per-URL HTML; fetching a URL writes its
    HTML to ``saved/<slug>/page.html`` and upserts a fetched page row. URLs
    without an entry get an empty page. ``calls`` records each batch.
    """
    site: dict[str, str] = {}
    calls: list[list[str]] = []

    def fake_fetch_urls(database, urls, refetch=False):
        calls.append(list(urls))
        fetched = []
        for url in urls:
            domain = registered_domain(url) or url
            slug = slug_for_url(url, domain)
            slug_dir = saved_dir / slug
            slug_dir.mkdir(parents=True, exist_ok=True)
            html = site.get(url, "<html><body>empty</body></html>")
            (slug_dir / "page.html").write_text(html, encoding="utf-8")
            page = Page(
                url=url,
                original_url=url,
                domain=domain,
                slug=slug,
                content_type="html",
                fetched_at=utc_now_iso(),
            )
            database.upsert(page)
            fetched.append(page)
        return fetched

    monkeypatch.setattr(archive_module, "fetch_urls", fake_fetch_urls)
    monkeypatch.setattr(archive_module, "parse_pending", lambda database: 0)
    fake_fetch_urls.site = site
    fake_fetch_urls.calls = calls
    return fake_fetch_urls


def _link_page(*urls: str) -> str:
    anchors = "".join(f'<a href="{url}">x</a>' for url in urls)
    return f"<html><body>{anchors}</body></html>"


TOC = "https://book.example.com/toc"


def test_depth_zero_is_one_batch_no_following(db, fake_fetch):
    fake_fetch.site[TOC] = _link_page("https://book.example.com/ch1")

    result = crawl_urls(db, [TOC], depth=0)

    assert fake_fetch.calls == [[TOC]]
    assert result.urls == [TOC]


def test_depth_one_follows_same_domain_links(db, fake_fetch):
    fake_fetch.site[TOC] = _link_page(
        "https://book.example.com/ch1",
        "https://book.example.com/ch2",
        "https://elsewhere.com/external",  # off the seed's domain: not followed
    )

    result = crawl_urls(db, [TOC], depth=1)

    assert fake_fetch.calls == [
        [TOC],
        ["https://book.example.com/ch1", "https://book.example.com/ch2"],
    ]
    assert set(result.urls) == {
        TOC,
        "https://book.example.com/ch1",
        "https://book.example.com/ch2",
    }
    # The chapters were registered as page rows, so the crawl is resumable.
    assert db.get("https://book.example.com/ch1") is not None


def test_depth_two_follows_links_of_links(db, fake_fetch):
    fake_fetch.site[TOC] = _link_page("https://book.example.com/ch1")
    fake_fetch.site["https://book.example.com/ch1"] = _link_page(
        "https://book.example.com/ch1/section"
    )

    crawl_urls(db, [TOC], depth=2)

    assert fake_fetch.calls == [
        [TOC],
        ["https://book.example.com/ch1"],
        ["https://book.example.com/ch1/section"],
    ]


def test_already_seen_links_are_not_refollowed(db, fake_fetch):
    # toc and ch1 link to each other; the crawl must not loop.
    fake_fetch.site[TOC] = _link_page("https://book.example.com/ch1")
    fake_fetch.site["https://book.example.com/ch1"] = _link_page(TOC)

    crawl_urls(db, [TOC], depth=3)

    assert fake_fetch.calls == [[TOC], ["https://book.example.com/ch1"]]


def test_stops_early_when_no_new_links(db, fake_fetch):
    fake_fetch.site[TOC] = "<html><body>no links here</body></html>"

    crawl_urls(db, [TOC], depth=5)

    assert fake_fetch.calls == [[TOC]]


def test_rules_apply_to_followed_links(db, fake_fetch):
    # A fragment-only variation canonicalizes back to the seed and is deduped.
    fake_fetch.site[TOC] = _link_page(
        f"{TOC}#section-2",
        "https://book.example.com/ch1",
    )

    crawl_urls(db, [TOC], depth=1)

    assert fake_fetch.calls == [[TOC], ["https://book.example.com/ch1"]]


def test_links_of_pdf_pages_are_not_extracted(db, saved_dir, fake_fetch):
    pdf_url = "https://book.example.com/paper.pdf"
    fake_fetch.site[TOC] = _link_page(pdf_url)

    def pdf_aware_fetch(database, urls, refetch=False):
        fake_fetch.calls.append(list(urls))
        fetched = []
        for url in urls:
            content_type = "pdf" if url.endswith(".pdf") else "html"
            domain = registered_domain(url) or url
            slug = slug_for_url(url, domain)
            if content_type == "html":
                slug_dir = saved_dir / slug
                slug_dir.mkdir(parents=True, exist_ok=True)
                html = fake_fetch.site.get(url, "<html></html>")
                (slug_dir / "page.html").write_text(html, encoding="utf-8")
            page = Page(
                url=url,
                original_url=url,
                domain=domain,
                slug=slug,
                content_type=content_type,
                fetched_at=utc_now_iso(),
            )
            database.upsert(page)
            fetched.append(page)
        return fetched

    archive_module.fetch_urls = pdf_aware_fetch  # monkeypatch fixture restores

    crawl_urls(db, [TOC], depth=2)

    # The PDF is archived at depth 1 but contributes no further frontier.
    assert fake_fetch.calls == [[TOC], [pdf_url]]


def test_missing_html_on_disk_is_skipped_not_fatal(db, saved_dir, fake_fetch):
    fake_fetch.site[TOC] = _link_page("https://book.example.com/ch1")

    def fetch_without_writing(database, urls, refetch=False):
        fake_fetch.calls.append(list(urls))
        # Rows say fetched, but no page.html lands on disk.
        for url in urls:
            domain = registered_domain(url) or url
            database.upsert(
                Page(
                    url=url,
                    original_url=url,
                    domain=domain,
                    slug=slug_for_url(url, domain),
                    content_type="html",
                    fetched_at=utc_now_iso(),
                )
            )
        return []

    archive_module.fetch_urls = fetch_without_writing  # monkeypatch fixture restores

    result = crawl_urls(db, [TOC], depth=2)

    assert fake_fetch.calls == [[TOC]]
    assert result.urls == [TOC]


def test_multiple_seeds_allow_each_seed_domain(db, fake_fetch):
    seed_a = "https://a.example.com/start"
    seed_b = "https://b.example.org/start"
    fake_fetch.site[seed_a] = _link_page("https://b.example.org/linked")

    crawl_urls(db, [seed_a, seed_b], depth=1)

    # a's link into b's registered domain is followed: both seeds' domains
    # are in the allowed set.
    assert fake_fetch.calls == [
        [seed_a, seed_b],
        ["https://b.example.org/linked"],
    ]


def test_results_aggregate_across_levels(db, fake_fetch):
    fake_fetch.site[TOC] = _link_page("https://book.example.com/ch1")

    result = crawl_urls(db, [TOC], depth=1)

    assert set(result.urls) == {TOC, "https://book.example.com/ch1"}
    assert {page.url for page in result.fetched} == set(result.urls)
