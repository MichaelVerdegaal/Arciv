"""Tests for URL processing: skip, rewrite, and passthrough logic."""

import re

from hypothesis import given
from hypothesis import strategies as st

from clotho.scrape.url_processor import (
    hash_filename,
    is_pdf_url,
    is_raw_text_url,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)

_SLUG_RE = re.compile(r"^.+-[0-9a-f]{8}$")


class TestProcessUrl:
    """Behaviour of the top-level process_url dispatcher."""

    def test_passthrough_keeps_url(self):
        url = "https://example.com/article"
        processed, status = process_url(url)
        assert processed == url
        assert "Success" in status

    def test_non_https_is_skipped(self):
        processed, status = process_url("http://example.com")
        assert processed is None
        assert "HTTPS" in status

    def test_skip_prefix_localhost(self):
        processed, _ = process_url("https://localhost:8080/page")
        assert processed is None

    def test_image_suffix_is_skipped(self):
        processed, _ = process_url("https://example.com/photo.png")
        assert processed is None

    def test_image_proxy_endpoint_is_skipped(self):
        url = "https://example.com/_next/image?url=%2Fcat.jpg&w=640"
        processed, status = process_url(url)
        assert processed is None
        assert "image proxy" in status

    def test_ip_domain_is_skipped(self):
        processed, _ = process_url("https://192.168.2.13/dashboard")
        assert processed is None

    def test_skip_domain_suffix(self):
        processed, _ = process_url("https://my.sharepoint.com/sites/x")
        assert processed is None

    def test_skip_exact_domain(self):
        processed, _ = process_url("https://claude.ai/chat/abc")
        assert processed is None

    def test_skip_domain_path_prefix(self):
        processed, _ = process_url("https://google.com/search?q=test")
        assert processed is None

    def test_google_non_search_path_passes(self):
        url = "https://google.com/maps"
        processed, _ = process_url(url)
        assert processed == url

    def test_github_blob_rewritten_to_repo_root(self):
        processed, status = process_url(
            "https://github.com/pytorch/captum/blob/main/setup.py"
        )
        assert processed == "https://github.com/pytorch/captum"
        assert "rewritten" in status

    def test_github_readable_file_kept(self):
        url = "https://github.com/owner/repo/blob/main/README.md"
        processed, _ = process_url(url)
        assert processed == url

    def test_raw_github_currently_passes_through(self):
        # KNOWN LIMITATION: the raw.githubusercontent.com rewriter is keyed by
        # full host, but process_url dispatches on the *registered* domain
        # (githubusercontent.com), so the rewriter never fires today. This test
        # pins the current behaviour; flip it if the dispatch key is fixed.
        url = "https://raw.githubusercontent.com/unit8co/darts/master/darts/x.py"
        processed, _ = process_url(url)
        assert processed == url

    @given(st.text(min_size=1).filter(lambda s: not s.startswith("https://")))
    def test_anything_not_https_returns_none(self, value):
        processed, _ = process_url(value)
        assert processed is None


class TestSplitUrl:
    def test_registered_domain_strips_subdomain(self):
        domain, path = split_url("https://aignishant.medium.com/some-post")
        assert domain == "medium.com"
        assert path == "/some-post"

    def test_registered_domain_helper(self):
        assert registered_domain("https://api.github.com/repos") == "github.com"


class TestPdfDetection:
    def test_pdf_extension(self):
        assert is_pdf_url("https://example.com/paper.pdf")

    def test_arxiv_pdf_path(self):
        assert is_pdf_url("https://arxiv.org/pdf/2305.14406")

    def test_non_pdf(self):
        assert not is_pdf_url("https://example.com/article")


class TestRawTextDetection:
    def test_markdown(self):
        assert is_raw_text_url("https://example.com/notes.md")

    def test_csv(self):
        assert is_raw_text_url("https://example.com/data.csv")

    def test_html_is_not_raw_text(self):
        assert not is_raw_text_url("https://example.com/index.html")


class TestSlugAndHash:
    def test_slug_format(self):
        slug = slug_for_url("https://github.com/owner/repo")
        assert slug.startswith("github.com-")
        assert _SLUG_RE.match(slug)

    def test_hash_filename_extension(self):
        name = hash_filename("https://example.com/x", ".md")
        assert name.endswith(".md")

    def test_same_url_same_slug(self):
        url = "https://example.com/a"
        assert slug_for_url(url) == slug_for_url(url)

    def test_different_urls_differ(self):
        assert slug_for_url("https://example.com/a") != slug_for_url(
            "https://example.com/b"
        )

    @given(st.text(min_size=1, max_size=200))
    def test_slug_always_well_formed(self, path):
        slug = slug_for_url(f"https://example.com/{path}")
        assert _SLUG_RE.match(slug)
