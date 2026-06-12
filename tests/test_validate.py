"""Tests for HTML content validation (block pages, size guards)."""

from clotho.convert.validate import (
    MAX_HTML_BYTES,
    MIN_HTML_BYTES,
    check_html,
)

# A body long enough to clear the MIN_HTML_BYTES floor.
_PADDING = "<p>" + ("content " * 200) + "</p>"


def _page(title: str = "Real Article", body: str = _PADDING) -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


class TestSizeGuards:
    def test_too_small_is_rejected(self):
        reason = check_html("<html></html>")
        assert reason is not None
        assert "suspiciously small" in reason

    def test_too_large_is_rejected(self):
        huge = "<html><body>" + ("x" * (MAX_HTML_BYTES + 1)) + "</body></html>"
        reason = check_html(huge)
        assert reason is not None
        assert "too large" in reason

    def test_normal_page_passes(self):
        assert check_html(_page()) is None

    def test_min_boundary_is_inclusive(self):
        # Exactly MIN_HTML_BYTES should not be rejected as "too small".
        html = "a" * MIN_HTML_BYTES
        reason = check_html(html)
        assert reason is None or "suspiciously small" not in reason


class TestBlockPageDetection:
    def test_just_a_moment_title(self):
        reason = check_html(_page(title="Just a moment..."))
        assert reason is not None
        assert "block page" in reason

    def test_access_denied_title(self):
        reason = check_html(_page(title="Access Denied"))
        assert reason is not None
        assert "block page" in reason

    def test_cloudflare_body_marker(self):
        html = _page(body="<div>challenge-platform</div>" + _PADDING)
        reason = check_html(html)
        assert reason is not None
        assert "marker" in reason

    def test_clean_page_has_no_block_reason(self):
        assert check_html(_page(title="A Normal Blog Post")) is None
