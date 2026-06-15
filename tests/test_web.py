"""Tests for the server-rendered web app and the archive job flow.

Routes are exercised with the FastAPI TestClient over a temporary archive. The
archive worker's fetch/parse callables are replaced with fakes that mutate the
DB the way the real pipeline would, so nothing launches a browser.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import arciv_api.config as api_config
from arciv.core.db import Page, PageDatabase, Source
from arciv.core.fetch import process_url, slug_for_url
from arciv_api.app import app
from arciv_api.jobs import ArchiveQueue, Job, Phase

# The Datastar client always sends this header; the backend reads signals only
# when it is present, so the tests simulate it.
_DS = {"Datastar-Request": "true"}


def _fake_fetch_raises(db_path, url: str) -> None:
    raise RuntimeError("boom")


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


# --- fakes standing in for the real fetch/parse pipeline ---


def _fake_fetch(db_path, url: str) -> None:
    with PageDatabase(db_path) as db:
        page = db.get(url)
        if page is None:
            return
        page.fetched_at = "2026-06-14T00:00:00+00:00"
        page.content_type = "html"
        db.upsert(page)


def _fake_parse(db_path) -> None:
    with PageDatabase(db_path) as db:
        for page in db.get_unparsed():
            page.title = f"Archived {page.domain}"
            page.word_count = 123
            page.parsed_at = "2026-06-14T00:01:00+00:00"
            page.fail_reason = None
            db.upsert(page)
            md = api_config.SAVED_DIR / page.slug / "page.md"
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text("# Archived\n\nBody text.", encoding="utf-8")


def _fake_fetch_fail(db_path, url: str) -> None:
    with PageDatabase(db_path) as db:
        page = db.get(url)
        page.fail_reason = "timeout"
        db.upsert(page)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """Point the app at a temp archive (DB + saved/) and return its root."""
    monkeypatch.setattr(api_config, "DB_PATH", tmp_path / "arciv.db")
    monkeypatch.setattr(api_config, "SAVED_DIR", tmp_path / "saved")
    return tmp_path


@pytest.fixture
def client(archive):
    # The context manager runs the lifespan, so app.state.archive (the worker)
    # exists. Swap in fake fetch/parse so enqueued jobs never open a browser.
    with TestClient(app) as test_client:
        app.state.archive._fetch = _fake_fetch
        app.state.archive._parse = _fake_parse
        yield test_client


def _seed(archive, pages: list[Page]) -> None:
    with PageDatabase(archive / "arciv.db") as db:
        for page in pages:
            db.upsert(page)


def _write_md(archive, page: Page, text: str) -> None:
    md = archive / "saved" / page.slug / "page.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(text, encoding="utf-8")


class TestBrowse:
    def test_lists_pages_with_titles_and_links(self, client, archive):
        page = _page("https://a.com/1", domain="a.com", title="Hello World")
        _seed(archive, [page])
        res = client.get("/")
        assert res.status_code == 200
        assert "Hello World" in res.text
        assert f"/page/{page.slug}" in res.text

    def test_domain_filter(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/1", domain="a.com", title="Keep me"),
                _page("https://b.com/1", domain="b.com", title="Drop me"),
            ],
        )
        res = client.get("/", params={"domain": "a.com"})
        assert "Keep me" in res.text
        assert "Drop me" not in res.text

    def test_bad_sort_falls_back_to_default(self, client, archive):
        _seed(archive, [_page("https://a.com/1", title="Still here")])
        res = client.get("/", params={"sort": "bogus; DROP TABLE pages"})
        assert res.status_code == 200
        assert "Still here" in res.text

    def test_missing_database_is_503(self, client, archive):
        # archive points DB_PATH at a file we never create
        assert client.get("/").status_code == 503


class TestPageDetail:
    def test_done_page_renders_markdown_body(self, client, archive):
        page = _page(
            "https://a.com/post", parsed_at="2026-06-11T01:00:00", title="Post"
        )
        _seed(archive, [page])
        _write_md(archive, page, "# Heading\n\nHello **bold** world.")
        res = client.get(f"/page/{page.slug}")
        assert res.status_code == 200
        assert "<strong>bold</strong>" in res.text
        assert "<h1" in res.text  # markdown heading rendered to HTML

    def test_markdown_is_sanitized(self, client, archive):
        page = _page("https://a.com/xss", parsed_at="2026-06-11T01:00:00")
        _seed(archive, [page])
        _write_md(archive, page, "Hi\n\n<script>alert('x')</script>\n")
        res = client.get(f"/page/{page.slug}")
        assert "<script>" not in res.text

    def test_pending_page_shows_poll_interval(self, client, archive):
        page = _page("https://a.com/p", fetched_at=None)
        _seed(archive, [page])
        res = client.get(f"/page/{page.slug}")
        assert res.status_code == 200
        assert "data-on-interval" in res.text
        assert f"/page/{page.slug}/progress" in res.text

    def test_failed_page_shows_reason(self, client, archive):
        page = _page("https://a.com/f", fetched_at=None, fail_reason="paywalled")
        _seed(archive, [page])
        res = client.get(f"/page/{page.slug}")
        assert "paywalled" in res.text
        assert "data-on-interval" not in res.text  # no polling once failed

    def test_unknown_slug_is_404(self, client, archive):
        _seed(archive, [])
        res = client.get("/page/nope-00000000")
        assert res.status_code == 404
        assert "Not found" in res.text

    def test_progress_returns_sse_patch(self, client, archive):
        page = _page(
            "https://a.com/post", parsed_at="2026-06-11T01:00:00", title="Done"
        )
        _seed(archive, [page])
        _write_md(archive, page, "# Done\n\nbody")
        res = client.get(f"/page/{page.slug}/progress")
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        assert "event: datastar-patch-elements" in res.text
        assert 'id="page-main"' in res.text


class TestDashboards:
    def test_domains(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/1", domain="a.com"),
                _page("https://a.com/2", domain="a.com"),
                _page("https://b.com/1", domain="b.com"),
            ],
        )
        res = client.get("/domains")
        assert res.status_code == 200
        assert "a.com" in res.text and "b.com" in res.text

    def test_sources(self, client, archive):
        with PageDatabase(archive / "arciv.db") as db:
            db.add_source(Source("notes", "/vault/notes", "2026-06-11T00:00:00"))
        res = client.get("/sources")
        assert res.status_code == 200
        assert "notes" in res.text
        assert "/vault/notes" in res.text

    def test_status(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/p", parsed_at="2026-06-11T01:00:00"),
                _page("https://a.com/x", fetched_at=None, fail_reason="timeout"),
            ],
        )
        res = client.get("/status")
        assert res.status_code == 200
        assert "timeout" in res.text


class TestArchivePost:
    def test_valid_url_redirects_to_page(self, client, archive):
        _seed(archive, [])  # empty DB so it exists
        url = "https://example.com/new-article"
        slug = slug_for_url(process_url(url)[0])
        res = client.post("/archive", json={"url": url}, headers=_DS)
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        assert f"/page/{slug}" in res.text

    def test_skipped_url_shows_reason(self, client, archive):
        _seed(archive, [])
        res = client.post(
            "/archive", json={"url": "https://youtube.com/watch?v=abc"}, headers=_DS
        )
        assert res.status_code == 200
        assert "Skipped" in res.text
        assert "/page/" not in res.text

    def test_empty_url_prompts(self, client, archive):
        _seed(archive, [])
        res = client.post("/archive", json={"url": "  "}, headers=_DS)
        assert "Enter a URL" in res.text


class TestWorker:
    def test_processes_job_to_done(self, archive):
        db_path = archive / "arciv.db"

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch, parse=_fake_parse)
            queue.start()
            slug, outcome = await queue.submit("https://example.com/a")
            assert outcome == "queued"
            await queue._queue.join()
            await queue.stop()
            return slug, queue.job_for(slug)

        slug, job = asyncio.run(run())
        assert job.phase is Phase.done
        with PageDatabase(db_path, read_only=True) as db:
            assert db.get_by_slug(slug).parsed_at is not None

    def test_recorded_fetch_failure_leaves_page_failed(self, archive):
        # A real fetch failure records a fail_reason and returns normally, so
        # the worker completes (phase done) while the durable row is "failed".
        db_path = archive / "arciv.db"

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch_fail, parse=_fake_parse)
            queue.start()
            slug, _ = await queue.submit("https://example.com/bad")
            await queue._queue.join()
            await queue.stop()
            return slug, queue.job_for(slug)

        slug, job = asyncio.run(run())
        assert job.phase is Phase.done
        with PageDatabase(db_path, read_only=True) as db:
            assert db.get_by_slug(slug).state == "failed"

    def test_unexpected_error_marks_job_failed(self, archive):
        # An unexpected exception (not a recorded failure) flips the job phase
        # and is captured, without killing the worker.
        db_path = archive / "arciv.db"

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch_raises, parse=_fake_parse)
            queue.start()
            slug, _ = await queue.submit("https://example.com/boom")
            await queue._queue.join()
            await queue.stop()
            return queue.job_for(slug)

        job = asyncio.run(run())
        assert job.phase is Phase.failed
        assert job.error

    def test_skipped_url_returns_reason(self, archive):
        db_path = archive / "arciv.db"

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch, parse=_fake_parse)
            return await queue.submit("https://youtube.com/watch?v=x")

        slug, reason = asyncio.run(run())
        assert slug is None
        assert reason  # a non-empty skip reason

    def test_already_parsed_returns_done(self, archive):
        db_path = archive / "arciv.db"
        url = "https://example.com/done"
        _seed(archive, [_page(url, parsed_at="2026-06-11T01:00:00")])

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch, parse=_fake_parse)
            return await queue.submit(url)

        slug, outcome = asyncio.run(run())
        assert outcome == "done"
        assert slug == slug_for_url(url)

    def test_in_flight_job_is_not_requeued(self, archive):
        db_path = archive / "arciv.db"
        url = "https://example.com/inflight"
        processed = process_url(url)[0]
        slug = slug_for_url(processed)

        async def run():
            queue = ArchiveQueue(db_path, fetch=_fake_fetch, parse=_fake_parse)
            # Pretend a job is already mid-fetch (worker not started here).
            queue._jobs[slug] = Job(slug=slug, url=processed, phase=Phase.fetching)
            return await queue.submit(url)

        _, outcome = asyncio.run(run())
        assert outcome == "existing"


class TestHealth:
    def test_health_ok_without_a_database(self, client, archive):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
