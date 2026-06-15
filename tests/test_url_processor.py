"""Tests for URL processing: skip, rewrite, and passthrough logic."""

import re

from hypothesis import given
from hypothesis import strategies as st

from arciv.core.db.models import Rule
from arciv.core.fetch.url_processor import (
    canonicalize,
    is_pdf_url,
    is_raw_text_url,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)

_SLUG_RE = re.compile(r"^.+-[0-9a-f]{8}$")

# Characters that are path separators or illegal in Windows directory names
_UNSAFE_FS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]')


class TestProcessUrl:
    """Behaviour of the top-level process_url dispatcher."""

    def test_passthrough_keeps_url(self):
        url = "https://example.com/article"
        processed, status = process_url(url)
        assert processed == url
        assert "Success" in status

    def test_fragment_is_stripped(self):
        processed, _ = process_url("https://example.com/docs/page.html#section-2")
        assert processed == "https://example.com/docs/page.html"

    def test_fragment_only_variants_dedupe_to_same_url(self):
        plain, _ = process_url("https://example.com/page")
        anchored, _ = process_url("https://example.com/page#additional-regressors")
        assert plain == anchored

    def test_non_https_is_skipped(self):
        processed, status = process_url("http://example.com")
        assert processed is None
        assert "HTTPS" in status

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

    def test_raw_github_rewritten_to_repo_root(self):
        processed, status = process_url(
            "https://raw.githubusercontent.com/unit8co/darts/master/darts/x.py"
        )
        assert processed == "https://github.com/unit8co/darts"
        assert "rewritten" in status

    def test_raw_github_readable_file_kept(self):
        url = "https://raw.githubusercontent.com/owner/repo/main/README.md"
        processed, _ = process_url(url)
        assert processed == url

    def test_huggingface_blob_pdf_rewritten_to_resolve(self):
        processed, status = process_url(
            "https://huggingface.co/org/model/blob/main/paper.pdf"
        )
        assert processed == "https://huggingface.co/org/model/resolve/main/paper.pdf"
        assert "rewritten" in status

    def test_huggingface_non_pdf_blob_passes_through(self):
        url = "https://huggingface.co/org/model/blob/main/config.json"
        # .json is a skip suffix, so it never reaches the rewriter.
        processed, _ = process_url(url)
        assert processed is None

    def test_huggingface_non_blob_passes_through(self):
        url = "https://huggingface.co/org/model"
        processed, _ = process_url(url)
        assert processed == url

    def test_host_case_variants_dedupe_to_same_url(self):
        lower, _ = process_url("https://example.com/Path")
        upper, _ = process_url("https://EXAMPLE.com/Path")
        assert lower == upper
        # The path is case-sensitive and must survive untouched
        assert "/Path" in lower

    def test_empty_host_is_skipped(self):
        processed, status = process_url("https://")
        assert processed is None
        assert "host" in status

    def test_malformed_url_is_skipped_not_raised(self):
        # urlparse raises ValueError on unclosed IPv6 brackets; one broken
        # link in a note must not crash the whole index run
        processed, _ = process_url("https://[")
        assert processed is None

    @given(st.text(min_size=1).filter(lambda s: not s.startswith("https://")))
    def test_anything_not_https_returns_none(self, value):
        processed, _ = process_url(value)
        assert processed is None

    @given(st.text())
    def test_never_raises_and_output_is_https_or_none(self, value):
        """process_url is total: any input (including https:// followed by
        garbage) yields (None, reason) or a https URL, never an exception."""
        processed, status = process_url(f"https://{value}")
        assert isinstance(status, str)
        if processed is not None:
            assert processed.startswith("https://")


class TestProcessUrlRules:
    """User rules drive skip/rewrite during process_url (the handler chain)."""

    def test_no_rules_passes_content_through(self):
        # Without rules, only the built-in code handlers run; ordinary content
        # is kept (this is the behaviour migrated skips no longer provide).
        url = "https://my.sharepoint.com/sites/x"
        processed, _ = process_url(url)
        assert processed == url

    def test_starts_with_skip(self):
        rules = [Rule("starts_with", "https://localhost", "skip", "local address")]
        processed, status = process_url("https://localhost:8080/page", rules)
        assert processed is None
        assert status == "local address"

    def test_domain_skip_matches_subdomain(self):
        rules = [Rule("domain", "sharepoint.com", "skip", "not content")]
        processed, _ = process_url("https://my.sharepoint.com/sites/x", rules)
        assert processed is None

    def test_domain_skip_exact(self):
        rules = [Rule("domain", "claude.ai", "skip", None)]
        processed, _ = process_url("https://claude.ai/chat/abc", rules)
        assert processed is None

    def test_starts_with_skip_is_path_aware(self):
        rules = [Rule("starts_with", "https://google.com/search", "skip", None)]
        skipped, _ = process_url("https://google.com/search?q=test", rules)
        kept, _ = process_url("https://google.com/maps", rules)
        assert skipped is None
        assert kept == "https://google.com/maps"

    def test_host_skip_is_exact_hostname(self):
        rules = [Rule("host", "app.powerbi.com", "skip", None)]
        skipped, _ = process_url("https://app.powerbi.com/report", rules)
        # A different host on the same registered domain is not matched.
        kept, _ = process_url("https://learn.powerbi.com/docs", rules)
        assert skipped is None
        assert kept == "https://learn.powerbi.com/docs"

    def test_exact_skip(self):
        rules = [Rule("exact", "https://example.com/one", "skip", None)]
        skipped, _ = process_url("https://example.com/one", rules)
        kept, _ = process_url("https://example.com/one/two", rules)
        assert skipped is None
        assert kept == "https://example.com/one/two"

    def test_rewrite_swaps_host_and_keeps_path(self):
        rules = [Rule("domain", "medium.com", "rewrite", "scribe.rip")]
        processed, status = process_url("https://medium.com/@a/post-123", rules)
        assert processed == "https://scribe.rip/@a/post-123"
        assert "rewritten" in status

    def test_first_matching_rule_wins(self):
        rules = [
            Rule("domain", "example.com", "skip", "first"),
            Rule("domain", "example.com", "skip", "second"),
        ]
        processed, status = process_url("https://example.com/p", rules)
        assert processed is None
        assert status == "first"

    def test_regex_skip(self):
        rules = [Rule("regex", r"^https://example\.com/admin.*", "skip", None)]
        skipped, _ = process_url("https://example.com/admin/panel", rules)
        kept, _ = process_url("https://example.com/public", rules)
        assert skipped is None
        assert kept == "https://example.com/public"

    def test_regex_rewrite_with_capture_group(self):
        rules = [
            Rule("regex", r"^https://arxiv\.org/abs/(.*)$", "rewrite", r"https://arxiv.org/pdf/\1")
        ]
        processed, status = process_url("https://arxiv.org/abs/2606.14647", rules)
        assert processed == "https://arxiv.org/pdf/2606.14647"
        assert "rewritten" in status

    def test_regex_rewrite_preserves_path_segments(self):
        rules = [
            Rule("regex", r"^https://example\.com/old/(.*?)(?:\?|$)", "rewrite", r"https://example.com/new/\1")
        ]
        processed, _ = process_url("https://example.com/old/page123", rules)
        assert processed == "https://example.com/new/page123"

    def test_regex_case_insensitive(self):
        rules = [Rule("regex", r"example\.com", "skip", None)]
        skipped, _ = process_url("https://EXAMPLE.COM/page", rules)
        assert skipped is None

    def test_regex_invalid_pattern_is_skipped(self):
        rules = [Rule("regex", r"(?P<invalid", "skip", None)]
        # Invalid regex should not crash; rule is skipped
        kept, status = process_url("https://example.com/page", rules)
        assert kept == "https://example.com/page"


class TestCanonicalize:
    """The canonicalize normaliser collapses equivalent URL forms."""

    def test_strips_www(self):
        assert canonicalize("https://www.example.com/post") == (
            "https://example.com/post"
        )

    def test_www_and_apex_collapse(self):
        assert canonicalize("https://www.example.com/post") == canonicalize(
            "https://example.com/post"
        )

    def test_trailing_slash_removed(self):
        assert canonicalize("https://example.com/post/") == ("https://example.com/post")

    def test_root_slash_kept(self):
        assert canonicalize("https://example.com/") == "https://example.com/"

    def test_tracking_params_dropped(self):
        assert (
            canonicalize(
                "https://example.com/post?utm_source=newsletter&utm_medium=email"
            )
            == "https://example.com/post"
        )

    def test_meaningful_query_kept_and_sorted(self):
        assert canonicalize("https://example.com/search?b=2&a=1") == (
            "https://example.com/search?a=1&b=2"
        )

    def test_mixed_tracking_and_real_params(self):
        assert (
            canonicalize("https://example.com/p?id=42&utm_campaign=x&fbclid=abc")
            == "https://example.com/p?id=42"
        )

    def test_default_port_dropped(self):
        assert canonicalize("https://example.com:443/post") == (
            "https://example.com/post"
        )

    def test_non_default_port_kept(self):
        assert canonicalize("https://example.com:8443/post") == (
            "https://example.com:8443/post"
        )

    def test_path_is_opaque(self):
        # Case and the encoded parens of the Wikipedia bug must survive
        url = "https://en.wikipedia.org/wiki/Leakage_(machine_learning)"
        assert canonicalize(url) == url

    def test_all_four_dupe_forms_collapse(self):
        forms = [
            "https://example.com/post",
            "https://example.com/post/",
            "https://www.example.com/post",
            "https://example.com/post?utm_source=newsletter",
        ]
        canon = {canonicalize(f) for f in forms}
        assert len(canon) == 1

    def test_unparseable_returned_unchanged(self):
        assert canonicalize("https://[") == "https://["


class TestProcessUrlCanonicalization:
    """process_url applies canonicalize to its result."""

    def test_dupe_forms_get_same_slug(self):
        forms = [
            "https://example.com/post",
            "https://example.com/post/",
            "https://www.example.com/post",
            "https://example.com/post?utm_source=newsletter",
        ]
        slugs = {slug_for_url(process_url(f)[0]) for f in forms}
        assert len(slugs) == 1


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


class TestSlug:
    def test_slug_format(self):
        slug = slug_for_url("https://github.com/owner/repo")
        assert slug.startswith("github.com-")
        assert _SLUG_RE.match(slug)

    def test_same_url_same_slug(self):
        url = "https://example.com/a"
        assert slug_for_url(url) == slug_for_url(url)

    def test_different_urls_differ(self):
        assert slug_for_url("https://example.com/a") != slug_for_url(
            "https://example.com/b"
        )

    def test_host_port_does_not_leak_into_slug(self):
        # ":" is illegal in Windows directory names; hosts without a public
        # suffix fall back to the raw netloc, which can carry a port
        slug = slug_for_url("https://intranet:8080/page")
        assert ":" not in slug

    @given(
        host=st.text(
            alphabet=st.characters(blacklist_characters="/#?@", min_codepoint=33),
            min_size=1,
            max_size=40,
        ),
        path=st.text(max_size=200),
    )
    def test_slug_is_always_a_safe_directory_name(self, host, path):
        """Slugs become directory names under saved/, so for ANY url they
        must be non-empty, end in the 8-hex hash, and contain no characters
        that are unsafe on Linux or Windows filesystems."""
        slug = slug_for_url(f"https://{host}/{path}")
        assert _SLUG_RE.match(slug)
        assert not _UNSAFE_FS_CHARS_RE.search(slug)
