"""Tests for the post-run report: it summarizes only this run's failures."""

import pytest
from loguru import logger

from arciv.core.db import Page, PageDatabase
from arciv.core.pipeline import report
from arciv.core.urls import slug_for_url


@pytest.fixture
def db(tmp_path):
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def logs():
    """Capture loguru messages emitted during the test."""
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="DEBUG")
    yield messages
    logger.remove(sink_id)


def _page(url: str, **overrides) -> Page:
    defaults = dict(
        original_url=url,
        domain="example.com",
        slug=slug_for_url(url),
        fetched_at="2026-06-11T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Page(url=url, **defaults)


def test_clean_run_says_nothing_about_failures(db, logs):
    db.upsert(_page("https://example.com/ok", parsed_at="2026-06-11T00:00:00"))
    report(db, archived=1, urls=["https://example.com/ok"])
    assert not any("failed this run" in m for m in logs)


def test_lists_only_this_runs_failures(db, logs):
    # A pre-existing failure from an earlier run must not be re-reported.
    db.upsert(_page("https://old.com/x", domain="old.com", fail_reason="timeout"))
    db.upsert(
        _page(
            "https://new.com/y",
            domain="new.com",
            fail_reason="too short (2 words from 1 KB html)",
        )
    )

    report(db, archived=0, urls=["https://new.com/y"])

    joined = "\n".join(logs)
    assert "1 failed this run" in joined
    assert "new.com" in joined
    assert "old.com" not in joined
