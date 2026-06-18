"""url_processing.py - URL processing for scraping: skip, rewrite, or pass through.

A URL runs through an ordered handler chain (see ``process_url``): the
user-editable :class:`~arciv.core.db.models.Rule` list (which now carries the
plumbing skips for media files, image proxies, and IP hosts, seeded as default
rules when the database is created), then the site-specific rewriters, and
finally :func:`~arciv.core.fetch.url_helpers.canonicalize`. Each handler returns
a :class:`Skip`, a :class:`Rewrite`, or ``None`` ("no opinion, keep going"); the
first ``Skip`` ends processing and a ``Rewrite`` swaps the URL and continues.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from arciv.core.db.models import Rule

from .url_helpers import canonicalize, registered_domain, split_url

# File extensions that are human-readable (don't rewrite to repo root)
READABLE_EXTENSIONS = frozenset({".md", ".txt", ".rst"})

# GitHub path patterns
_GITHUB_BLOB_TREE_RE = re.compile(r"^/([^/]+/[^/]+)/(?:blob|tree)/")
_RAW_GITHUB_PATH_RE = re.compile(r"^/([^/]+/[^/]+)/")

# HuggingFace /blob/ PDF viewer paths (serve HTML, not the file)
_HF_BLOB_PDF_RE = re.compile(r"^(/[^/]+/[^/]+)/blob/(.+\.pdf)$", re.IGNORECASE)


def _rewrite_github(url: str) -> str:
    """Normalize GitHub file URLs to repository root.

    E.g. https://github.com/pytorch/captum/blob/main/file.py
         -> https://github.com/pytorch/captum

    Keeps readable files (.md, .txt, .rst) as-is.
    """
    parsed = urlparse(url)
    match = _GITHUB_BLOB_TREE_RE.match(parsed.path)

    if not match:
        return url

    # Keep readable files unchanged
    if any(parsed.path.lower().endswith(ext) for ext in READABLE_EXTENSIONS):
        return url

    # Rewrite to repo root, strip fragments (line numbers)
    return urlunparse((parsed.scheme, parsed.netloc, f"/{match.group(1)}", "", "", ""))


def _rewrite_raw_github(url: str) -> str:
    """Normalize raw.githubusercontent.com URLs to GitHub repository root.

    E.g. https://raw.githubusercontent.com/unit8co/darts/refs/heads/master/darts/timeseries.py
         -> https://github.com/unit8co/darts

    Keeps readable files (.md, .txt, .rst) as-is.
    """
    parsed = urlparse(url)

    # Keep readable files unchanged
    if any(parsed.path.lower().endswith(ext) for ext in READABLE_EXTENSIONS):
        return url

    match = _RAW_GITHUB_PATH_RE.match(parsed.path)
    if not match:
        return url

    return f"https://github.com/{match.group(1)}"


def _rewrite_huggingface(url: str) -> str:
    """Rewrite HuggingFace /blob/ PDF links to the raw /resolve/ download URL.

    The /blob/ path returns an HTML viewer page rather than the file itself,
    which fails PDF parsing. E.g.
    https://huggingface.co/org/model/blob/main/paper.pdf
         -> https://huggingface.co/org/model/resolve/main/paper.pdf

    Non-PDF URLs are passed through unchanged.
    """
    parsed = urlparse(url)
    match = _HF_BLOB_PDF_RE.match(parsed.path)
    if not match:
        return url

    new_path = f"{match.group(1)}/resolve/{match.group(2)}"
    return urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))


# Domain -> rewriter function
DOMAIN_REWRITERS: dict[str, Callable[[str], str]] = {
    "github.com": _rewrite_github,
    "raw.githubusercontent.com": _rewrite_raw_github,
    "huggingface.co": _rewrite_huggingface,
}


@dataclass(frozen=True)
class Skip:
    """A handler's verdict to stop the chain: the URL is not archived."""

    reason: str


@dataclass(frozen=True)
class Rewrite:
    """A handler's verdict to replace the URL and keep processing the chain."""

    url: str


# A handler decides about one URL. None means "no opinion, keep going".
UrlHandler = Callable[[str], Skip | Rewrite | None]


def _rewriter_handler(url: str) -> Rewrite | None:
    """Apply a site-specific rewriter, if one is registered for this URL.

    Tries the full host first (raw.githubusercontent.com), then the registered
    domain (github.com, huggingface.co); tldextract collapses subdomains, so a
    host-keyed rewriter never matches on the registered domain. Returns a
    Rewrite only when the URL actually changes, so a no-op rewriter (e.g.
    GitHub keeping a README) does not flip the status to "rewritten"."""
    host = urlparse(url).netloc
    domain = registered_domain(url) or split_url(url)[0]
    rewriter = DOMAIN_REWRITERS.get(host) or DOMAIN_REWRITERS.get(domain)
    if rewriter is None:
        return None
    new_url = rewriter(url)
    return Rewrite(new_url) if new_url != url else None


_DOLLAR_REF = re.compile(r"\$(?:(\$)|\{(\d+)\}|(\d+))")


def _expand_dollar_refs(replacement: str) -> str:
    r"""Translate a ``$1``-style replacement into ``re.sub``'s ``\1`` form.

    Rules are documented to reference capture groups with ``$1``, ``$2`` (and
    ``${1}``), but ``re.sub`` only understands ``\1``. Any backslashes in the
    user's text are escaped first so they stay literal, and ``$$`` yields a
    literal ``$``."""
    escaped = replacement.replace("\\", "\\\\")

    def repl(m: re.Match) -> str:
        if m.group(1):  # $$ -> literal $
            return "$"
        return "\\" + (m.group(2) or m.group(3))  # $1 / ${1} -> \1

    return _DOLLAR_REF.sub(repl, escaped)


def _rule_matches(rule: Rule, url: str, netloc: str, domain: str) -> bool:
    """Whether a user rule's pattern matches this URL, per its match_type."""
    if rule.match_type == "domain":
        return domain == rule.pattern
    if rule.match_type == "host":
        return netloc == rule.pattern
    if rule.match_type == "starts_with":
        return url.startswith(rule.pattern)
    if rule.match_type == "ends_with":
        return url.endswith(rule.pattern)
    if rule.match_type == "exact":
        return url == rule.pattern
    if rule.match_type == "regex":
        try:
            return bool(re.search(rule.pattern, url, re.IGNORECASE))
        except re.error:
            return False
    return False


def _nonregex_rewrite(rule: Rule, url: str, parsed) -> str:
    """Compute the rewritten URL for a non-regex rewrite rule.

    Rewrite replaces whatever the match selected, so the replacement stands in
    for a different span per match type: the netloc for ``domain``/``host``,
    the matched prefix for ``starts_with``, the matched suffix for
    ``ends_with``, or the whole URL for ``exact``. (regex rewrites are handled
    separately, with capture-group expansion.) The ``ends_with`` slice is safe
    because validation guarantees a non-empty pattern."""
    if rule.match_type in ("domain", "host"):
        return parsed._replace(netloc=rule.replacement).geturl()
    if rule.match_type == "starts_with":
        return rule.replacement + url[len(rule.pattern) :]
    if rule.match_type == "ends_with":
        return url[: -len(rule.pattern)] + rule.replacement
    # exact: replace the whole URL
    return rule.replacement


def _rules_handler(rules: Sequence[Rule]) -> UrlHandler:
    """Build a handler that applies the first matching user rule.

    The rules are walked in order (``PageDatabase.list_rules`` returns them by
    position); the first whose pattern matches wins. A skip stops the chain; a
    rewrite replaces the matched span (see :func:`_nonregex_rewrite`) or, for a
    regex match, applies a full URL rewrite with capture groups, then lets
    processing continue."""

    def handler(url: str) -> Skip | Rewrite | None:
        parsed = urlparse(url)
        netloc = parsed.netloc
        domain = registered_domain(url) or split_url(url)[0]
        for rule in rules:
            if not _rule_matches(rule, url, netloc, domain):
                continue
            if rule.action == "skip":
                return Skip(rule.replacement or "skipped (not content)")
            if rule.action == "rewrite" and rule.replacement:
                if rule.match_type == "regex":
                    # Regex rewrite: capture groups are written as $1, $2 in
                    # the rule; translate them to re.sub's \1, \2 form.
                    try:
                        new_url = re.sub(
                            rule.pattern,
                            _expand_dollar_refs(rule.replacement),
                            url,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                        # Only rewrite if the pattern actually matched and produced a change
                        return Rewrite(new_url) if new_url != url else None
                    except re.error:
                        # Invalid regex: skip this rule
                        continue
                else:
                    return Rewrite(_nonregex_rewrite(rule, url, parsed))
        return None

    return handler


def process_url(url: str, rules: Sequence[Rule] = ()) -> tuple[str | None, str]:
    """Process a URL for scraping: skip it, rewrite it, or pass it through.

    Runs the URL through the handler chain (see the module docstring): cheap
    guards and host normalisation first, then the user ``rules``, then the site
    rewriters, and finally :func:`~arciv.core.fetch.url_helpers.canonicalize`.

    Args:
        url: The URL to process.
        rules: User-editable rules to apply, in order (see
            ``PageDatabase.list_rules``). Defaults to none; the plumbing skips
            (media files, image proxies, IP hosts) now live in the seeded
            default rules, so callers wanting them must pass the rule list.

    Returns:
        The canonical URL to scrape (or None if skipped) and a status message.
    """
    # Only process https URLs
    if not url.startswith("https://"):
        return None, "URL does not begin with HTTPS"

    # Strip the #fragment: servers never see it, so URLs differing only by
    # anchor are the same page and would otherwise be archived twice.
    url = url.partition("#")[0]

    # Malformed URLs (e.g. unclosed IPv6 brackets) make urlparse raise
    try:
        parsed = urlparse(url)
    except ValueError:
        return None, "URL could not be parsed"

    host = parsed.netloc
    if not host:
        return None, "URL has no host"

    # Hosts are case-insensitive: lowercase so case variants dedupe to one page
    if not host.islower():
        url = f"https://{host.lower()}{url[len('https://') + len(host) :]}"

    # Ordered handler chain. The first Skip ends processing; a Rewrite swaps the
    # URL and the chain continues, so a rewritten URL is still canonicalised.
    handlers: tuple[UrlHandler, ...] = (
        _rules_handler(rules),
        _rewriter_handler,
    )
    rewritten = False
    for handler in handlers:
        result = handler(url)
        if isinstance(result, Skip):
            return None, result.reason
        if isinstance(result, Rewrite):
            url = result.url
            rewritten = True

    status = "Success (rewritten)" if rewritten else "Success"
    return canonicalize(url), status
