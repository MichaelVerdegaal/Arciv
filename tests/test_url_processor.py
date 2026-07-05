"""Tests for URL processing: skip, rewrite, and passthrough logic."""

import re

from hypothesis import given
from hypothesis import strategies as st

from arciv.core.urls import (
    Action,
    Rule,
    canonicalize,
    is_pdf_url,
    is_raw_text_url,
    load_rules,
    process_url,
    registered_domain,
    slug_for_url,
    split_url,
)

# The packaged defaults (no user file): medium/github/huggingface rewrites plus
# the policy skips. Behaviour tests that exercise a default rule pass these.
DEFAULTS = load_rules()

_SLUG_RE = re.compile(r"^.+-[0-9a-f]{8}$")

# Characters that are path separators or illegal in Windows directory names
_UNSAFE_FS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]')


def _rule(match_type: str, pattern: str, *actions: Action, name: str = "test") -> Rule:
    """Build a Rule tersely for the engine tests."""
    return Rule(name=name, match_type=match_type, pattern=pattern, actions=actions)


class TestProcessUrl:
    """Behaviour of the top-level process_url dispatcher (with defaults)."""

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

    def test_image_suffix_is_skipped_by_guard(self):
        # Media extensions are an in-code plumbing guard, not a rule, so they
        # fire without any rules passed.
        processed, _ = process_url("https://example.com/photo.png")
        assert processed is None

    def test_image_proxy_endpoint_is_skipped_by_guard(self):
        url = "https://example.com/_next/image?url=%2Fcat.jpg&w=640"
        processed, status = process_url(url)
        assert processed is None
        assert "image proxy" in status

    def test_ip_host_is_skipped_by_guard(self):
        processed, _ = process_url("https://192.168.2.13/dashboard")
        assert processed is None

    def test_localhost_is_skipped_by_guard(self):
        processed, status = process_url("https://localhost:8080/page")
        assert processed is None
        assert "local" in status

    def test_github_blob_rewritten_to_repo_root(self):
        processed, status = process_url(
            "https://github.com/pytorch/captum/blob/main/setup.py", DEFAULTS
        )
        assert processed == "https://github.com/pytorch/captum"
        assert "rewritten" in status

    def test_github_readable_file_kept(self):
        # The github rule's negative lookahead keeps readable files archived.
        url = "https://github.com/owner/repo/blob/main/README.md"
        processed, _ = process_url(url, DEFAULTS)
        assert processed == url

    def test_raw_github_rewritten_to_repo_root(self):
        processed, status = process_url(
            "https://raw.githubusercontent.com/unit8co/darts/master/darts/x.py",
            DEFAULTS,
        )
        assert processed == "https://github.com/unit8co/darts"
        assert "rewritten" in status

    def test_raw_github_collapses_readable_file_too(self):
        # Unlike the github rule, the raw.github rule has no readable exception,
        # so even a raw README collapses to the repo root.
        processed, _ = process_url(
            "https://raw.githubusercontent.com/owner/repo/main/README.md", DEFAULTS
        )
        assert processed == "https://github.com/owner/repo"

    def test_huggingface_blob_pdf_rewritten_to_resolve(self):
        processed, status = process_url(
            "https://huggingface.co/org/model/blob/main/paper.pdf", DEFAULTS
        )
        assert processed == "https://huggingface.co/org/model/resolve/main/paper.pdf"
        assert "rewritten" in status

    def test_huggingface_blob_json_skipped_by_media_guard(self):
        # .json matches the media guard (which runs before the rules), so the
        # huggingface rule never sees it.
        url = "https://huggingface.co/org/model/blob/main/config.json"
        processed, _ = process_url(url, DEFAULTS)
        assert processed is None

    def test_huggingface_non_blob_passes_through(self):
        url = "https://huggingface.co/org/model"
        processed, _ = process_url(url, DEFAULTS)
        assert processed == url

    def test_medium_default_prepends_freedium_keeping_subdomain(self):
        processed, status = process_url(
            "https://aignishant.medium.com/some-post", DEFAULTS
        )
        assert processed == (
            "https://freedium-mirror.cfd/https://aignishant.medium.com/some-post"
        )
        assert "rewritten" in status

    def test_youtube_default_skipped(self):
        processed, _ = process_url("https://www.youtube.com/watch?v=abc", DEFAULTS)
        assert processed is None

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
        processed, status = process_url(f"https://{value}", DEFAULTS)
        assert isinstance(status, str)
        if processed is not None:
            assert processed.startswith("https://")


class TestProcessUrlRules:
    """The match/action engine drives skip and rewrite during process_url."""

    def test_no_rules_passes_content_through(self):
        # Without rules, only the plumbing guards run; ordinary content is kept.
        url = "https://my.sharepoint.com/sites/x"
        processed, _ = process_url(url)
        assert processed == url

    def test_domain_skip_matches_subdomain(self):
        rules = [
            _rule("domain", "sharepoint.com", Action("skip", reason="not content"))
        ]
        processed, _ = process_url("https://my.sharepoint.com/sites/x", rules)
        assert processed is None

    def test_skip_reason_is_propagated(self):
        rules = [
            _rule(
                "starts_with",
                "https://localhost.example",
                Action("skip", reason="local"),
            )
        ]
        processed, status = process_url("https://localhost.example/page", rules)
        assert processed is None
        assert status == "local"

    def test_skip_uses_default_reason_when_blank(self):
        rules = [_rule("domain", "claude.ai", Action("skip"))]
        processed, status = process_url("https://claude.ai/chat/abc", rules)
        assert processed is None
        assert status  # a non-empty generic reason

    def test_host_skip_is_exact_hostname(self):
        rules = [_rule("host", "app.powerbi.com", Action("skip"))]
        skipped, _ = process_url("https://app.powerbi.com/report", rules)
        # A different host on the same registered domain is not matched.
        kept, _ = process_url("https://learn.powerbi.com/docs", rules)
        assert skipped is None
        assert kept == "https://learn.powerbi.com/docs"

    def test_starts_with_skip_is_path_aware(self):
        rules = [_rule("starts_with", "https://google.com/search", Action("skip"))]
        skipped, _ = process_url("https://google.com/search?q=test", rules)
        kept, _ = process_url("https://google.com/maps", rules)
        assert skipped is None
        assert kept == "https://google.com/maps"

    def test_first_matching_rule_wins(self):
        rules = [
            _rule("domain", "example.com", Action("skip", reason="first")),
            _rule("domain", "example.com", Action("skip", reason="second")),
        ]
        processed, status = process_url("https://example.com/p", rules)
        assert processed is None
        assert status == "first"

    def test_prepend_action_wraps_url(self):
        rules = [
            _rule("domain", "medium.com", Action("prepend", text="https://mirror/"))
        ]
        processed, status = process_url("https://medium.com/@a/post-123", rules)
        assert processed == "https://mirror/https://medium.com/@a/post-123"
        assert "rewritten" in status

    def test_replace_action_swaps_substring(self):
        rules = [
            _rule(
                "regex",
                r"huggingface\.co/.+/blob/.+\.pdf",
                Action("replace", old="/blob/", new="/resolve/"),
            )
        ]
        processed, _ = process_url(
            "https://huggingface.co/org/model/blob/main/paper.pdf", rules
        )
        assert processed == "https://huggingface.co/org/model/resolve/main/paper.pdf"

    def test_regex_replace_with_capture_group(self):
        rules = [
            _rule(
                "regex",
                r"^https://arxiv\.org/abs/(.*)$",
                Action(
                    "regex_replace",
                    pattern=r"^https://arxiv\.org/abs/(.*)$",
                    replacement=r"https://arxiv.org/pdf/$1",
                ),
            )
        ]
        processed, status = process_url("https://arxiv.org/abs/2606.14647", rules)
        assert processed == "https://arxiv.org/pdf/2606.14647"
        assert is_pdf_url(processed)
        assert "rewritten" in status

    def test_regex_replace_braced_capture_group(self):
        rules = [
            _rule(
                "regex",
                r"^https://arxiv\.org/abs/(.*)$",
                Action(
                    "regex_replace",
                    pattern=r"^https://arxiv\.org/abs/(.*)$",
                    replacement=r"https://arxiv.org/pdf/${1}",
                ),
            )
        ]
        processed, _ = process_url("https://arxiv.org/abs/2606.14647", rules)
        assert processed == "https://arxiv.org/pdf/2606.14647"

    def test_regex_replace_preserves_path_segments(self):
        rules = [
            _rule(
                "regex",
                r"^https://example\.com/old/",
                Action(
                    "regex_replace",
                    pattern=r"^https://example\.com/old/(.*?)(?:\?|$)",
                    replacement=r"https://example.com/new/$1",
                ),
            )
        ]
        processed, _ = process_url("https://example.com/old/page123", rules)
        assert processed == "https://example.com/new/page123"

    def test_regex_match_is_case_insensitive(self):
        rules = [_rule("regex", r"example\.com", Action("skip"))]
        skipped, _ = process_url("https://EXAMPLE.COM/page", rules)
        assert skipped is None

    def test_invalid_regex_match_does_not_crash(self):
        rules = [_rule("regex", r"(?P<invalid", Action("skip"))]
        kept, _ = process_url("https://example.com/page", rules)
        assert kept == "https://example.com/page"

    def test_invalid_regex_replace_is_noop(self):
        rules = [
            _rule(
                "regex",
                r"example\.com",
                Action("regex_replace", pattern=r"(?P<invalid", replacement="x"),
            )
        ]
        # The match fires but the broken replace leaves the URL unchanged.
        processed, _ = process_url("https://example.com/page", rules)
        assert processed == "https://example.com/page"


class TestLoadRules:
    """Loading the packaged defaults and an optional user file."""

    def test_defaults_loaded_without_user_file(self):
        rules = load_rules()
        assert rules  # not empty
        names = {r.name for r in rules}
        assert "medium to freedium" in names
        assert "youtube" in names

    def test_user_rules_load_ahead_of_defaults(self, tmp_path):
        user_file = tmp_path / "rules.toml"
        user_file.write_text(
            '[[rule]]\nname = "mine"\ntype = "domain"\nmatch = "example.com"\n'
            '  [[rule.action]]\n  type = "skip"\n  reason = "custom"\n',
            encoding="utf-8",
        )
        rules = load_rules(user_file)
        assert rules[0].name == "mine"
        # The defaults still follow the user rule.
        assert any(r.name == "youtube" for r in rules)

    def test_user_rule_wins_on_first_match(self, tmp_path):
        # A user rule that rewrites medium beats the default freedium prepend.
        user_file = tmp_path / "rules.toml"
        user_file.write_text(
            '[[rule]]\nname = "scribe"\ntype = "domain"\nmatch = "medium.com"\n'
            '  [[rule.action]]\n  type = "prepend"\n  text = "https://scribe/"\n',
            encoding="utf-8",
        )
        processed, _ = process_url("https://medium.com/@a/p", load_rules(user_file))
        assert processed == "https://scribe/https://medium.com/@a/p"

    def test_malformed_user_file_is_ignored(self, tmp_path):
        user_file = tmp_path / "rules.toml"
        user_file.write_text("this is not valid toml = = =", encoding="utf-8")
        # Falls back to the defaults rather than raising.
        rules = load_rules(user_file)
        assert any(r.name == "youtube" for r in rules)


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
