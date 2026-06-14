"""Tests for the read API (FastAPI TestClient over a temporary archive)."""

import pytest
from fastapi.testclient import TestClient

import arciv_api.config as api_config
from arciv.db import Page, PageDatabase
from arciv.scrape import slug_for_url
from arciv_api.app import app


def _page(url: str, **overrides) -> Page:
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug=slug_for_url(url),
        content_type="html",
        word_count=500,
        fetched_at="2026-06-11T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Page(url=url, **defaults)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """Point the API at a temp archive (DB + saved/) and return its root."""
    monkeypatch.setattr(api_config, "DB_PATH", tmp_path / "arciv.db")
    monkeypatch.setattr(api_config, "SAVED_DIR", tmp_path / "saved")
    return tmp_path


@pytest.fixture
def client(archive):
    return TestClient(app)


def _seed(archive, pages: list[Page]) -> None:
    """Create the DB (so it exists) and upsert the given pages."""
    with PageDatabase(archive / "arciv.db") as db:
        for page in pages:
            db.upsert(page)


def _write_md(archive, page: Page, text: str) -> None:
    md_path = archive / "saved" / page.slug / "page.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(text, encoding="utf-8")


def _link(archive, page: Page, file_path: str) -> None:
    with PageDatabase(archive / "arciv.db") as db:
        db.replace_links_for_files([file_path], [(page.url, file_path, None, "t1")])


class TestListPages:
    def test_lists_seeded_pages(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/1", domain="a.com"),
                _page("https://b.com/1", domain="b.com"),
            ],
        )
        res = client.get("/api/pages")
        assert res.status_code == 200
        data = res.json()
        assert {item["url"] for item in data["items"]} == {
            "https://a.com/1",
            "https://b.com/1",
        }
        assert data["has_more"] is False

    def test_includes_pending_and_failed(self, client, archive):
        _seed(
            archive,
            [
                _page("https://x.com/done", parsed_at="2026-06-11T01:00:00"),
                _page("https://x.com/pending", fetched_at=None),
                _page("https://x.com/failed", fetched_at=None, fail_reason="timeout"),
            ],
        )
        res = client.get("/api/pages")
        states = {item["url"]: item["state"] for item in res.json()["items"]}
        assert states == {
            "https://x.com/done": "done",
            "https://x.com/pending": "pending",
            "https://x.com/failed": "failed",
        }

    def test_status_filter(self, client, archive):
        _seed(
            archive,
            [
                _page("https://x.com/done", parsed_at="2026-06-11T01:00:00"),
                _page("https://x.com/pending", fetched_at=None),
            ],
        )
        res = client.get("/api/pages", params={"status": "done"})
        assert [item["url"] for item in res.json()["items"]] == ["https://x.com/done"]

    def test_domain_filter(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/1", domain="a.com"),
                _page("https://b.com/1", domain="b.com"),
            ],
        )
        res = client.get("/api/pages", params={"domain": "a.com"})
        assert [item["url"] for item in res.json()["items"]] == ["https://a.com/1"]

    def test_paging_reports_has_more(self, client, archive):
        _seed(archive, [_page(f"https://x.com/{i}", word_count=i) for i in range(5)])
        first = client.get(
            "/api/pages",
            params={"limit": 2, "sort": "word_count", "order": "asc"},
        ).json()
        assert [item["word_count"] for item in first["items"]] == [0, 1]
        assert first["has_more"] is True
        last = client.get(
            "/api/pages",
            params={"limit": 2, "offset": 4, "sort": "word_count", "order": "asc"},
        ).json()
        assert [item["word_count"] for item in last["items"]] == [4]
        assert last["has_more"] is False

    def test_invalid_sort_is_422(self, client, archive):
        _seed(archive, [_page("https://a.com/1")])
        assert client.get("/api/pages", params={"sort": "bogus"}).status_code == 422

    def test_out_of_range_limit_is_422(self, client, archive):
        _seed(archive, [_page("https://a.com/1")])
        assert client.get("/api/pages", params={"limit": 0}).status_code == 422


class TestPageDetail:
    def test_done_page_has_markdown_and_sources(self, client, archive):
        page = _page(
            "https://a.com/post",
            domain="a.com",
            parsed_at="2026-06-11T01:00:00",
            title="Hello",
            author="Me",
        )
        _seed(archive, [page])
        _write_md(archive, page, "# Hello\n\nBody text.")
        _link(archive, page, "/vault/notes/x.md")
        res = client.get(f"/api/pages/{page.slug}")
        assert res.status_code == 200
        data = res.json()
        assert data["url"] == "https://a.com/post"
        assert data["state"] == "done"
        assert data["title"] == "Hello"
        assert data["author"] == "Me"
        assert data["markdown"].startswith("# Hello")
        assert data["sources"] == ["/vault/notes/x.md"]

    def test_pending_page_has_null_markdown_and_no_sources(self, client, archive):
        page = _page("https://a.com/p", fetched_at=None)
        _seed(archive, [page])
        data = client.get(f"/api/pages/{page.slug}").json()
        assert data["state"] == "pending"
        assert data["markdown"] is None
        assert data["sources"] == []

    def test_failed_page_reports_reason(self, client, archive):
        page = _page("https://a.com/f", fetched_at=None, fail_reason="paywalled")
        _seed(archive, [page])
        data = client.get(f"/api/pages/{page.slug}").json()
        assert data["state"] == "failed"
        assert data["fail_reason"] == "paywalled"
        assert data["markdown"] is None

    def test_unknown_slug_is_404(self, client, archive):
        _seed(archive, [])  # create an empty DB so it exists
        assert client.get("/api/pages/nope-00000000").status_code == 404


class TestDomains:
    def test_lists_domains_with_counts_biggest_first(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/1", domain="a.com"),
                _page("https://a.com/2", domain="a.com"),
                _page("https://b.com/1", domain="b.com"),
            ],
        )
        res = client.get("/api/domains")
        assert res.status_code == 200
        assert res.json()["domains"] == [
            {"domain": "a.com", "count": 2},
            {"domain": "b.com", "count": 1},
        ]


class TestMetaAndErrors:
    def test_missing_database_is_503(self, client, archive):
        # archive points DB_PATH at a file we never create
        assert client.get("/api/pages").status_code == 503

    def test_health_ok_without_a_database(self, client, archive):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
