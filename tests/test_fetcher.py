"""Tests for the Fetcher's browser-free helpers.

The network/browser entry points need a real stealth browser, but the
decision logic around them is pure: error classification, the
skip/refetch rule, original_url preservation, and the on-disk writes.
Those are tested here without launching anything.
"""

import asyncio

import pytest

from arciv.core.db import Page, PageDatabase
from arciv.core.urls import Action, Rule, slug_for_url
from arciv.core.fetch.fetcher import Fetcher


@pytest.fixture
def db(tmp_path):
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def fetcher(db, tmp_path):
    return Fetcher(db, tmp_path / "saved")


def _page(url: str, **overrides) -> Page:
    defaults = dict(original_url=url, domain="example.com", slug=slug_for_url(url))
    defaults.update(overrides)
    return Page(url=url, **defaults)


class TestFormatFetchError:
    def test_dns_failure(self, fetcher):
        err = Exception("net::ERR_NAME_NOT_RESOLVED at https://nope.example")
        assert fetcher._format_fetch_error(err) == "DNS resolution failed"

    def test_connection_refused(self, fetcher):
        err = Exception("net::ERR_CONNECTION_REFUSED")
        assert fetcher._format_fetch_error(err) == "connection refused"

    def test_timeout(self, fetcher):
        err = Exception("Timeout 30000ms exceeded")
        assert fetcher._format_fetch_error(err) == "timeout"

    def test_unknown_error_keeps_first_line_only(self, fetcher):
        err = Exception("something broke\nframe 1\nframe 2")
        assert fetcher._format_fetch_error(err) == "something broke"


class TestIsTransient:
    def test_timeout_is_transient(self, fetcher):
        assert fetcher._is_transient("timeout") is True

    def test_connection_reset_is_transient(self, fetcher):
        assert fetcher._is_transient("net::ERR_CONNECTION_RESET happened") is True

    def test_permanent_error_is_not_transient(self, fetcher):
        assert fetcher._is_transient("DNS resolution failed") is False


class TestNeedsFetch:
    # The helpers take the already-looked-up row (the batch does one
    # get_many() for all URLs), so tests hand them the Page directly.

    def test_new_url_needs_fetch(self, fetcher):
        assert fetcher._needs_fetch(None, refetch=False) is True

    def test_pending_url_needs_fetch(self, fetcher):
        existing = _page("https://example.com/p", fetched_at=None)
        assert fetcher._needs_fetch(existing, refetch=False) is True

    def test_failed_url_is_skipped(self, fetcher):
        existing = _page(
            "https://example.com/f", fetched_at=None, fail_reason="timeout"
        )
        assert fetcher._needs_fetch(existing, refetch=False) is False

    def test_already_fetched_is_skipped(self, fetcher):
        existing = _page("https://example.com/a", fetched_at="2026-06-11T00:00:00")
        assert fetcher._needs_fetch(existing, refetch=False) is False

    def test_refetch_forces_already_fetched(self, fetcher):
        existing = _page("https://example.com/a", fetched_at="2026-06-11T00:00:00")
        assert fetcher._needs_fetch(existing, refetch=True) is True

    def test_refetch_forces_failed(self, fetcher):
        existing = _page(
            "https://example.com/f", fetched_at=None, fail_reason="timeout"
        )
        assert fetcher._needs_fetch(existing, refetch=True) is True


class TestEntryFor:
    def test_new_url_uses_input_url_as_original(self, fetcher):
        original, domain, slug = fetcher._entry_for(
            None, "https://example.com/a", "https://example.com/a?utm_source=x"
        )
        assert original == "https://example.com/a?utm_source=x"
        assert domain == "example.com"
        assert slug == slug_for_url("https://example.com/a")

    def test_preserves_original_url_recorded_at_index_time(self, fetcher):
        # The index stage already stored the pre-rewrite URL; a later fetch
        # must not overwrite it with the processed URL.
        existing = _page("https://example.com/a", original_url="https://orig.example/a")
        original, _, _ = fetcher._entry_for(
            existing, "https://example.com/a", "https://input.example/a"
        )
        assert original == "https://orig.example/a"


class TestStore:
    def test_store_success_records_fetched_page(self, db, fetcher):
        slug = slug_for_url("https://example.com/a")
        page = fetcher._store_success(
            "https://example.com/a",
            "https://example.com/a",
            "example.com",
            slug,
            "html",
        )
        assert page.fetched is True
        assert page.content_type == "html"
        stored = db.get("https://example.com/a")
        assert stored.fetched_at is not None
        assert stored.parsed_at is None
        assert stored.fail_reason is None

    def test_store_failure_records_unfetched_page(self, db, fetcher):
        slug = slug_for_url("https://example.com/a")
        fetcher._store_failure(
            "https://example.com/a",
            "https://example.com/a",
            "example.com",
            slug,
            "timeout",
        )
        stored = db.get("https://example.com/a")
        assert stored.fetched is False
        assert stored.fail_reason == "timeout"


class TestRuleDivergence:
    """A stored URL the current rules no longer target must not stay
    pending forever; the divergence is recorded as its fail_reason."""

    def test_batch_marks_pending_row_skipped_by_rule(self, db, tmp_path):
        db.upsert(_page("https://example.com/old", fetched_at=None))
        rules = [
            Rule(
                name="kill",
                match_type="domain",
                pattern="example.com",
                actions=(Action("skip", reason="no longer wanted"),),
            )
        ]
        fetcher = Fetcher(db, tmp_path / "saved", rules=rules)
        assert fetcher.fetch_batch(["https://example.com/old"]) == []
        stored = db.get("https://example.com/old")
        assert stored.fail_reason is not None
        assert "skipped by rule change" in stored.fail_reason

    def test_batch_marks_pending_row_rewritten_by_rule(self, db, tmp_path):
        db.upsert(_page("https://example.com/old", fetched_at=None))
        # The rewrite target is already fetched, so no network is touched.
        db.upsert(_page("https://example.com/new", fetched_at="2026-06-11T00:00:00"))
        rules = [
            Rule(
                name="move",
                match_type="domain",
                pattern="example.com",
                actions=(Action("replace", old="/old", new="/new"),),
            )
        ]
        fetcher = Fetcher(db, tmp_path / "saved", rules=rules)
        fetcher.fetch_batch(["https://example.com/old"])
        stored = db.get("https://example.com/old")
        assert stored.fail_reason is not None
        assert "rewritten by rule change" in stored.fail_reason
        # The already-fetched target row is untouched.
        assert db.get("https://example.com/new").fail_reason is None

    def test_fetched_rows_are_never_demoted(self, db, tmp_path):
        # A rule change must not put a failure on content already archived.
        db.upsert(_page("https://example.com/done", fetched_at="2026-06-11T00:00:00"))
        rules = [
            Rule(
                name="kill",
                match_type="domain",
                pattern="example.com",
                actions=(Action("skip"),),
            )
        ]
        fetcher = Fetcher(db, tmp_path / "saved", rules=rules)
        fetcher.fetch_batch(["https://example.com/done"])
        assert db.get("https://example.com/done").fail_reason is None


class TestIsolation:
    def test_isolated_records_unexpected_failure(self, db, fetcher):
        # An exception that escapes a per-URL task must not propagate (it
        # would cancel the whole gather batch); it becomes that page's failure.
        async def boom():
            raise OSError("disk full")

        url = "https://example.com/a"
        entry = (url, url, "example.com", slug_for_url(url))
        result = asyncio.run(fetcher._isolated(entry, boom()))
        assert result is None
        assert db.get(url).fail_reason == "unexpected: disk full"


class TestSaveToDisk:
    def test_save_pdf_writes_bytes(self, fetcher, tmp_path):
        fetcher._save_pdf("example.com-pdf00001", b"%PDF-1.4 bytes")
        written = tmp_path / "saved" / "example.com-pdf00001" / "page.pdf"
        assert written.read_bytes() == b"%PDF-1.4 bytes"

    def test_save_html_writes_text(self, fetcher, tmp_path):
        asyncio.run(fetcher._save_html("example.com-html0001", "<html>hi</html>"))
        written = tmp_path / "saved" / "example.com-html0001" / "page.html"
        assert written.read_text("utf-8") == "<html>hi</html>"
