"""Tests for the parse stage (raw HTML/PDF on disk → markdown)."""

import pytest

from clotho.db import Page, PageDatabase
from clotho.pipeline.parse import parse_pending


def _make_html(tag: str) -> str:
    """Build article HTML with varied, unique prose.

    trafilatura deduplicates repeated text and caches content across calls,
    so each test needs distinct, non-repetitive paragraphs.
    """
    paragraphs = "".join(
        f"<p>Paragraph {i} of the {tag} article covers archival topic number "
        f"{i * 7} with enough distinct prose to pass extraction filters.</p>"
        for i in range(40)
    )
    return (
        f"<html><head><title>Test Article {tag}</title></head>"
        f"<body><article>{paragraphs}</article></body></html>"
    )


@pytest.fixture
def db(tmp_path):
    """A fresh database backed by a temp file, closed after the test."""
    with PageDatabase(tmp_path / "test.db") as database:
        yield database


def _fetched_page(url: str, slug: str) -> Page:
    return Page(
        url=url,
        original_url=url,
        domain="example.com",
        slug=slug,
        fetched=True,
        fetched_at="2026-06-11T00:00:00+00:00",
    )


def _save_html(saved_dir, slug: str, html: str):
    slug_dir = saved_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "page.html").write_text(html, encoding="utf-8")


class TestParsePending:
    def test_writes_markdown_and_metadata(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))
        _save_html(saved, "example.com-aaaaaaaa", _make_html("alpha"))

        parsed = parse_pending(db, saved_dir=saved, min_words=10)

        assert parsed == 1
        assert (saved / "example.com-aaaaaaaa" / "page.md").exists()
        page = db.get("https://example.com/a")
        assert page.word_count > 0
        assert page.fetched is True

    def test_skips_already_parsed_unless_reparse(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))
        _save_html(saved, "example.com-aaaaaaaa", _make_html("beta"))
        (saved / "example.com-aaaaaaaa" / "page.md").write_text("old", "utf-8")

        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
        assert parse_pending(db, saved_dir=saved, reparse=True, min_words=10) == 1

    def test_rejects_too_short_pages(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))
        _save_html(saved, "example.com-aaaaaaaa", _make_html("gamma"))

        parsed = parse_pending(db, saved_dir=saved, min_words=100_000)

        assert parsed == 0
        page = db.get("https://example.com/a")
        assert page.fetched is False
        assert "too short" in page.fail_reason

    def test_rejects_missing_raw_content(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))

        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
        assert db.get("https://example.com/a").fail_reason == "no raw content on disk"

    def test_raw_text_url_stored_directly(self, db, tmp_path):
        saved = tmp_path / "saved"
        url = "https://raw.example.com/readme.md"
        db.upsert(_fetched_page(url, "example.com-bbbbbbbb"))
        content = "plain text " * 50
        _save_html(saved, "example.com-bbbbbbbb", content)

        parsed = parse_pending(db, saved_dir=saved, min_words=10)

        assert parsed == 1
        md = (saved / "example.com-bbbbbbbb" / "page.md").read_text("utf-8")
        assert md == content

    def test_unfetched_pages_are_ignored(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(
            Page(
                url="https://example.com/pending",
                original_url="https://example.com/pending",
                slug="example.com-cccccccc",
            )
        )
        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
