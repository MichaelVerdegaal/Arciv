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
from arciv_api.jobs import Action, ArchiveQueue, Job, Phase

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


def _fake_refetch(db_path, url: str) -> None:
    """Stand in for a network re-download: bump fetched_at, leave parsed_at."""
    with PageDatabase(db_path) as db:
        page = db.get(url)
        if page is None:
            return
        page.fetched_at = "2026-06-15T00:00:00+00:00"
        page.content_type = "html"
        db.upsert(page)


def _fake_reparse(db_path, url: str) -> None:
    """Stand in for a from-disk re-parse of one page, whatever its parse state."""
    with PageDatabase(db_path) as db:
        page = db.get(url)
        if page is None:
            return
        page.title = f"Reparsed {page.domain}"
        page.word_count = 321
        page.parsed_at = "2026-06-15T00:01:00+00:00"
        page.fail_reason = None
        db.upsert(page)
        md = api_config.SAVED_DIR / page.slug / "page.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("# Reparsed\n\nFresh body.", encoding="utf-8")


def _fake_fetch_fail(db_path, url: str) -> None:
    with PageDatabase(db_path) as db:
        page = db.get(url)
        page.fail_reason = "timeout"
        db.upsert(page)


def _fake_archive_urls(db_path, urls: list[str]) -> None:
    """Stand in for the batch fetch+parse: mark each known URL fetched+parsed."""
    with PageDatabase(db_path) as db:
        for url in urls:
            page = db.get(url)
            if page is None:
                continue
            page.fetched_at = "2026-06-14T00:00:00+00:00"
            page.content_type = "html"
            page.parsed_at = "2026-06-14T00:01:00+00:00"
            page.title = f"Archived {page.domain}"
            page.fail_reason = None
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
        app.state.archive._refetch = _fake_refetch
        app.state.archive._reparse = _fake_reparse
        # Source archival runs a batch fetch+parse in the background; keep it
        # off a real browser too.
        app.state.archive._archive_urls = _fake_archive_urls
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

    def test_missing_database_is_created(self, client, archive):
        # archive points DB_PATH at a file we never create; the request
        # should initialise an empty database rather than erroring.
        from arciv_api import config

        assert not config.DB_PATH.exists()
        assert client.get("/").status_code == 200
        assert config.DB_PATH.exists()

    def test_fetched_page_shows_fetched_state(self, client, archive):
        # The default page is fetched but not parsed, which is now "fetched".
        _seed(archive, [_page("https://a.com/f", title="In flight")])
        res = client.get("/")
        assert ">fetched<" in res.text

    def test_status_filter_fetched(self, client, archive):
        _seed(
            archive,
            [
                _page("https://a.com/f", title="Fetched One"),
                _page(
                    "https://a.com/d", title="Done One", parsed_at="2026-06-11T01:00:00"
                ),
            ],
        )
        res = client.get("/", params={"status": "fetched"})
        assert "Fetched One" in res.text
        assert "Done One" not in res.text


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

    def test_fetched_page_polls_for_parse(self, client, archive):
        # Fetched but not parsed (e.g. CLI fetched, parse still pending): the
        # detail keeps polling until parse lands, and shows the fetched badge.
        page = _page("https://a.com/await")
        _seed(archive, [page])
        res = client.get(f"/page/{page.slug}")
        assert res.status_code == 200
        assert ">fetched<" in res.text
        assert "data-on-interval" in res.text

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

    def test_done_page_shows_refetch_and_reparse_buttons(self, client, archive):
        page = _page(
            "https://a.com/post", parsed_at="2026-06-11T01:00:00", title="Post"
        )
        _seed(archive, [page])
        _write_md(archive, page, "# Heading\n\nbody")
        res = client.get(f"/page/{page.slug}")
        assert f"/page/{page.slug}/refetch" in res.text
        assert f"/page/{page.slug}/reparse" in res.text

    def test_unfetched_page_hides_reparse_button(self, client, archive):
        # Re-parse needs raw content on disk; a never-fetched (failed) page has
        # none, so only Re-fetch is offered.
        page = _page("https://a.com/x", fetched_at=None, fail_reason="timeout")
        _seed(archive, [page])
        res = client.get(f"/page/{page.slug}")
        assert f"/page/{page.slug}/refetch" in res.text
        assert f"/page/{page.slug}/reparse" not in res.text


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


class TestPageRerun:
    def test_refetch_redirects_and_enqueues_job(self, client, archive):
        page = _page(
            "https://a.com/post", parsed_at="2026-06-11T01:00:00", title="Post"
        )
        _seed(archive, [page])
        res = client.post(f"/page/{page.slug}/refetch", json={}, headers=_DS)
        assert res.status_code == 200
        assert f"/page/{page.slug}" in res.text  # redirect back to the detail
        assert app.state.archive.job_for(page.slug) is not None

    def test_reparse_redirects_and_enqueues_job(self, client, archive):
        page = _page(
            "https://a.com/post", parsed_at="2026-06-11T01:00:00", title="Post"
        )
        _seed(archive, [page])
        res = client.post(f"/page/{page.slug}/reparse", json={}, headers=_DS)
        assert res.status_code == 200
        assert f"/page/{page.slug}" in res.text

    def test_rerun_unknown_slug_redirects_without_a_job(self, client, archive):
        _seed(archive, [])
        res = client.post("/page/nope-00000000/reparse", json={}, headers=_DS)
        assert res.status_code == 200
        assert "/page/nope-00000000" in res.text
        assert app.state.archive.job_for("nope-00000000") is None


class TestRerunWorker:
    def test_refetch_redownloads_then_reparses(self, archive):
        db_path = archive / "arciv.db"
        url = "https://example.com/post"
        _seed(archive, [_page(url, parsed_at="2026-06-11T01:00:00", title="Old")])
        calls: list[str] = []

        def rec_refetch(db_path, url):
            calls.append("refetch")
            _fake_refetch(db_path, url)

        def rec_reparse(db_path, url):
            calls.append("reparse")
            _fake_reparse(db_path, url)

        async def run():
            queue = ArchiveQueue(db_path, refetch=rec_refetch, reparse=rec_reparse)
            queue.start()
            slug = slug_for_url(url)
            outcome = await queue.resubmit(slug, url, refetch=True)
            assert outcome == "refetch"
            await queue._queue.join()
            await queue.stop()
            return slug, queue.job_for(slug)

        slug, job = asyncio.run(run())
        assert job.phase is Phase.done
        assert calls == ["refetch", "reparse"]
        with PageDatabase(db_path, read_only=True) as db:
            assert db.get_by_slug(slug).title == "Reparsed example.com"

    def test_reparse_skips_fetch(self, archive):
        db_path = archive / "arciv.db"
        url = "https://example.com/post"
        _seed(archive, [_page(url, parsed_at="2026-06-11T01:00:00")])

        def boom_fetch(db_path, url):
            raise AssertionError("re-parse must not touch the network")

        async def run():
            queue = ArchiveQueue(
                db_path,
                fetch=boom_fetch,
                refetch=boom_fetch,
                reparse=_fake_reparse,
            )
            queue.start()
            slug = slug_for_url(url)
            outcome = await queue.resubmit(slug, url, refetch=False)
            assert outcome == "reparse"
            await queue._queue.join()
            await queue.stop()
            return slug, queue.job_for(slug)

        slug, job = asyncio.run(run())
        assert job.phase is Phase.done
        with PageDatabase(db_path, read_only=True) as db:
            assert db.get_by_slug(slug).title == "Reparsed example.com"

    def test_resubmit_in_flight_is_not_requeued(self, archive):
        db_path = archive / "arciv.db"
        url = "https://example.com/inflight"
        slug = slug_for_url(url)

        async def run():
            queue = ArchiveQueue(db_path)
            queue._jobs[slug] = Job(
                slug=slug, url=url, phase=Phase.parsing, action=Action.reparse
            )
            return await queue.resubmit(slug, url, refetch=False)

        assert asyncio.run(run()) == "existing"


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


class TestRules:
    def test_rules_page_lists_seeded_defaults(self, client, archive):
        _seed(archive, [])  # creates the DB, which seeds the default rules
        res = client.get("/rules")
        assert res.status_code == 200
        assert "youtube.com" in res.text

    def test_add_rule_redirects_and_persists(self, client, archive):
        _seed(archive, [])
        res = client.post(
            "/rules",
            json={
                "match_type": "domain",
                "pattern": "newsite.com",
                "action": "skip",
                "replacement": "not content",
            },
            headers=_DS,
        )
        assert res.status_code == 200
        assert "/rules" in res.text  # redirect back to the list
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert any(r.pattern == "newsite.com" for r in db.list_rules())

    def test_add_rule_rejects_missing_pattern(self, client, archive):
        _seed(archive, [])
        res = client.post(
            "/rules",
            json={"match_type": "domain", "pattern": "", "action": "skip"},
            headers=_DS,
        )
        assert "pattern" in res.text.lower()
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert all(r.pattern for r in db.list_rules())

    def test_add_rewrite_rule_requires_replacement(self, client, archive):
        _seed(archive, [])
        res = client.post(
            "/rules",
            json={"match_type": "domain", "pattern": "medium.com", "action": "rewrite"},
            headers=_DS,
        )
        assert "replacement" in res.text.lower()

    def test_delete_rule_removes_it(self, client, archive):
        _seed(archive, [])
        with PageDatabase(archive / "arciv.db") as db:
            rule_id = db.list_rules()[0].id
        res = client.post(f"/rules/{rule_id}/delete", json={}, headers=_DS)
        assert res.status_code == 200
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert all(r.id != rule_id for r in db.list_rules())

    def test_added_skip_rule_takes_effect_on_archive(self, client, archive):
        _seed(archive, [])
        client.post(
            "/rules",
            json={
                "match_type": "domain",
                "pattern": "blocked.com",
                "action": "skip",
                "replacement": "blocked by rule",
            },
            headers=_DS,
        )
        res = client.post(
            "/archive", json={"url": "https://blocked.com/page"}, headers=_DS
        )
        assert "Skipped" in res.text
        assert "blocked by rule" in res.text


class TestSourcesUI:
    def test_add_source_indexes_and_redirects(self, client, archive):
        notes = archive / "vault"
        notes.mkdir()
        (notes / "a.md").write_text("[x](https://example.com/post)", encoding="utf-8")
        res = client.post(
            "/sources", json={"name": "notes", "path": str(notes)}, headers=_DS
        )
        assert res.status_code == 200
        assert "/sources/notes" in res.text  # redirect to the new source
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert db.get_source("notes") is not None
            # Indexing is synchronous, so the link is attributed right away.
            assert db.get_urls_for_source("notes") == ["https://example.com/post"]

    def test_add_source_rejects_missing_directory(self, client, archive):
        # Validation fails before any DB write, so nothing is registered.
        _seed(archive, [])  # create the DB so the check below can open it
        res = client.post(
            "/sources",
            json={"name": "ghost", "path": str(archive / "nope")},
            headers=_DS,
        )
        assert "Not a directory" in res.text
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert db.get_source("ghost") is None

    def test_add_source_rejects_blank_name(self, client, archive):
        notes = archive / "vault"
        notes.mkdir()
        res = client.post(
            "/sources", json={"name": "  ", "path": str(notes)}, headers=_DS
        )
        assert "name" in res.text.lower()

    def test_add_source_rejects_duplicate_name(self, client, archive):
        notes = archive / "vault"
        notes.mkdir()
        with PageDatabase(archive / "arciv.db") as db:
            db.add_source(Source("notes", str(notes), "2026-06-11T00:00:00+00:00"))
        res = client.post(
            "/sources", json={"name": "notes", "path": str(notes)}, headers=_DS
        )
        assert "already exists" in res.text

    def test_source_detail_lists_files_and_links(self, client, archive):
        with PageDatabase(archive / "arciv.db") as db:
            db.add_source(Source("notes", "/vault/notes", "2026-06-11T00:00:00+00:00"))
            db.upsert(_page("https://a.com/1", title="Linked Page"))
            db.replace_links_for_files(
                ["/vault/notes/x.md"],
                [("https://a.com/1", "/vault/notes/x.md", "notes", "t1")],
            )
        res = client.get("/sources/notes")
        assert res.status_code == 200
        assert "/vault/notes/x.md" in res.text
        assert "Linked Page" in res.text

    def test_source_detail_unknown_is_404(self, client, archive):
        _seed(archive, [])
        res = client.get("/sources/ghost")
        assert res.status_code == 404
        assert "No source named" in res.text

    def test_remove_source_redirects_and_deletes(self, client, archive):
        with PageDatabase(archive / "arciv.db") as db:
            db.add_source(Source("notes", "/vault/notes", "2026-06-11T00:00:00+00:00"))
        res = client.post("/sources/notes/delete", json={}, headers=_DS)
        assert res.status_code == 200
        assert "/sources" in res.text
        with PageDatabase(archive / "arciv.db", read_only=True) as db:
            assert db.get_source("notes") is None

    def test_rearchive_unknown_source_shows_error(self, client, archive):
        _seed(archive, [])
        res = client.post("/sources/ghost/archive", json={}, headers=_DS)
        assert "No source named" in res.text


class TestSourceArchiveWorker:
    def test_archive_source_bg_fetches_and_parses(self, archive):
        db_path = archive / "arciv.db"
        with PageDatabase(db_path) as db:
            db.add_source(Source("notes", "/vault/notes", "2026-06-11T00:00:00+00:00"))
            db.upsert(_page("https://a.com/1", fetched_at=None))  # pending
            db.replace_links_for_files(
                ["/vault/notes/x.md"],
                [("https://a.com/1", "/vault/notes/x.md", "notes", "t1")],
            )

        async def run():
            queue = ArchiveQueue(db_path, archive_urls=_fake_archive_urls)
            queue.archive_source_bg("notes", ["https://a.com/1"])
            assert queue.is_archiving("notes")  # set before the task runs
            await asyncio.gather(*queue._source_tasks)
            await queue.stop()

        asyncio.run(run())
        with PageDatabase(db_path, read_only=True) as db:
            assert db.get("https://a.com/1").parsed_at is not None

    def test_is_archiving_false_when_idle(self, archive):
        queue = ArchiveQueue(archive / "arciv.db")
        assert queue.is_archiving("notes") is False


class TestHealth:
    def test_health_ok_without_a_database(self, client, archive):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
