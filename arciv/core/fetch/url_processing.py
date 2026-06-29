"""url_processing.py - Turn a raw link into a URL to fetch (or a skip).

A URL runs through, in order:

1. Cheap structural checks: https-only, ``#fragment`` stripped, a host present,
   the host lowercased so case variants dedupe.
2. The in-code plumbing guards (:func:`_plumbing_skip`): media/non-content file
   extensions, the Next.js image proxy, IP-address and localhost hosts. These
   are immutable "never fetch this" facts, so they live in code, ahead of any
   rule.
3. The loaded rules (see :mod:`arciv.core.fetch.rules`): the first matching rule
   skips or rewrites the URL.
4. :func:`~arciv.core.fetch.url_helpers.canonicalize`, collapsing equivalent
   forms to one identity.

:func:`evaluate_url` returns the full structured verdict (used by
``arciv rules test``); :func:`process_url` is the terse ``(url, status)`` wrapper
the index and fetch stages consume.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

from .rules import Rule, apply_rules
from .url_helpers import canonicalize, registered_domain, split_url

# Non-content file extensions never worth fetching (the bytes aren't readable
# material). Matched case-insensitively, before the rules.
_MEDIA_EXT_RE = re.compile(
    r"\.(?:png|jpg|jpeg|gif|svg|webp|bmp|tiff|ico|mp4|mp3|avi|mov|wmv|flv|mkv"
    r"|json|xml)(?:\?|$)",
    re.IGNORECASE,
)
# A bare IPv4 host (after stripping any www./port), e.g. 192.168.2.13.
_IPV4_HOST_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _plumbing_skip(url: str, host: str) -> str | None:
    """Universal never-fetch guard: a skip reason, or None to keep going.

    These are immutable plumbing (nobody un-skips a media file or a localhost
    address), so they run in code ahead of the editable rules and return the
    reason shown to the user.
    """
    if _MEDIA_EXT_RE.search(url):
        return "media/non-content file"
    if "/_next/image" in url:
        return "image proxy endpoint"
    bare_host = host.removeprefix("www.").split(":", 1)[0]
    if _IPV4_HOST_RE.match(bare_host):
        return "IP-address host"
    if bare_host == "localhost":
        return "local address"
    return None


@dataclass(frozen=True)
class UrlVerdict:
    """The full outcome of processing a URL.

    Attributes:
        url: Canonical URL to fetch, or None if the URL is skipped.
        verdict: "skipped", "rewritten", or "passthrough".
        reason: Why it was skipped (None unless verdict is "skipped").
        rule: The rule responsible for a skip/rewrite, or None. A plumbing-guard
            skip and a plain passthrough have no rule.
    """

    url: str | None
    verdict: str
    reason: str | None
    rule: Rule | None


def evaluate_url(url: str, rules: Sequence[Rule] = ()) -> UrlVerdict:
    """Process a URL into a fetch target (or a skip), with full detail.

    Runs the structural checks, the in-code plumbing guards, the given ``rules``
    (first match wins), and canonicalization. ``arciv rules test`` uses this to
    name the rule responsible; most callers use :func:`process_url` instead.
    """
    # Only process https URLs.
    if not url.startswith("https://"):
        return UrlVerdict(None, "skipped", "URL does not begin with HTTPS", None)

    # Strip the #fragment: servers never see it, so URLs differing only by anchor
    # are the same page and would otherwise be archived twice.
    url = url.partition("#")[0]

    # Malformed URLs (e.g. unclosed IPv6 brackets) make urlparse raise.
    try:
        parsed = urlparse(url)
    except ValueError:
        return UrlVerdict(None, "skipped", "URL could not be parsed", None)

    host = parsed.netloc
    if not host:
        return UrlVerdict(None, "skipped", "URL has no host", None)

    # Hosts are case-insensitive: lowercase so case variants dedupe to one page.
    if not host.islower():
        lowered = host.lower()
        url = f"https://{lowered}{url[len('https://') + len(host) :]}"
        host = lowered

    guard_reason = _plumbing_skip(url, host)
    if guard_reason is not None:
        return UrlVerdict(None, "skipped", guard_reason, None)

    domain = registered_domain(url) or split_url(url)[0]
    result = apply_rules(url, host, domain, rules)
    if result.url is None:
        return UrlVerdict(None, "skipped", result.reason, result.rule)

    canonical = canonicalize(result.url)
    if result.url != url:
        return UrlVerdict(canonical, "rewritten", None, result.rule)
    return UrlVerdict(canonical, "passthrough", None, None)


def process_url(url: str, rules: Sequence[Rule] = ()) -> tuple[str | None, str]:
    """Process a URL for scraping: skip it, rewrite it, or pass it through.

    Thin wrapper over :func:`evaluate_url` returning ``(url_or_None, status)``,
    the contract the index and fetch stages consume. ``status`` is the skip
    reason when the URL is None, otherwise ``"Success"`` or
    ``"Success (rewritten)"``.

    Args:
        url: The URL to process.
        rules: Rules to apply, in order (see
            :func:`arciv.core.fetch.rules.load_rules`). Defaults to none; the
            plumbing skips always run regardless.

    Returns:
        The canonical URL to scrape (or None if skipped) and a status message.
    """
    verdict = evaluate_url(url, rules)
    if verdict.url is None:
        return None, verdict.reason or "skipped"
    status = "Success (rewritten)" if verdict.verdict == "rewritten" else "Success"
    return verdict.url, status
