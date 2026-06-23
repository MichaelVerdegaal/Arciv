"""Tests for the parse stage (raw HTML/PDF on disk → markdown)."""

import pytest

from arciv.core.db import Page, PageDatabase
from arciv.core.image_manifest import write_manifest
from arciv.core.pipeline.parse import parse_pending


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


def _fetched_page(url: str, slug: str, content_type: str = "html") -> Page:
    return Page(
        url=url,
        original_url=url,
        domain="example.com",
        slug=slug,
        content_type=content_type,
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
        assert page.parsed is True
        assert page.parsed_at is not None

    def test_skips_already_parsed_unless_reparse(self, db, tmp_path):
        saved = tmp_path / "saved"
        page = _fetched_page("https://example.com/a", "example.com-aaaaaaaa")
        page.parsed_at = "2026-06-11T01:00:00+00:00"
        db.upsert(page)
        _save_html(saved, "example.com-aaaaaaaa", _make_html("beta"))

        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
        assert parse_pending(db, saved_dir=saved, reparse=True, min_words=10) == 1

    def test_rejects_too_short_pages(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))
        _save_html(saved, "example.com-aaaaaaaa", _make_html("gamma"))

        parsed = parse_pending(db, saved_dir=saved, min_words=100_000)

        assert parsed == 0
        page = db.get("https://example.com/a")
        # Raw content is still on disk: the page stays fetched, not parsed
        assert page.fetched is True
        assert page.parsed is False
        assert "too short" in page.fail_reason

    def test_rejects_missing_raw_content(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))

        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
        assert "raw file missing" in db.get("https://example.com/a").fail_reason

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

    def test_relinks_inline_images_from_manifest(self, db, tmp_path):
        # A page-relative <img> should be resolved against the page URL and,
        # using the fetch-written manifest, linked to the local capture.
        saved = tmp_path / "saved"
        slug = "example.com-aaaaaaaa"
        db.upsert(_fetched_page("https://example.com/a", slug))
        paragraphs = "".join(
            f"<p>Gallery prose line {i} with distinct words for extraction "
            f"number {i * 3}.</p>"
            for i in range(40)
        )
        html = (
            "<html><head><title>Gallery</title></head><body><article>"
            f"{paragraphs}"
            '<img src="/img/pic.png" alt="A pic"/>'
            f"{paragraphs}"
            "</article></body></html>"
        )
        _save_html(saved, slug, html)
        # Simulate what the fetch stage wrote: the manifest plus the file.
        slug_dir = saved / slug
        (slug_dir / "images").mkdir()
        (slug_dir / "images" / "pic123.png").write_bytes(b"fake image bytes")
        write_manifest(slug_dir, {"https://example.com/img/pic.png": "pic123.png"})

        assert parse_pending(db, saved_dir=saved, min_words=10) == 1

        md = (slug_dir / "page.md").read_text("utf-8")
        assert "](images/pic123.png)" in md
        assert "example.com/img/pic.png" not in md

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

    def test_rejected_page_is_not_retried_without_reparse(self, db, tmp_path):
        saved = tmp_path / "saved"
        db.upsert(_fetched_page("https://example.com/a", "example.com-aaaaaaaa"))
        _save_html(saved, "example.com-aaaaaaaa", _make_html("delta"))

        # First run rejects (gate impossible to clear), second run skips it
        assert parse_pending(db, saved_dir=saved, min_words=100_000) == 0
        assert parse_pending(db, saved_dir=saved, min_words=10) == 0
        # --reparse retries rejected pages and clears the failure
        assert parse_pending(db, saved_dir=saved, reparse=True, min_words=10) == 1
        assert db.get("https://example.com/a").fail_reason is None
