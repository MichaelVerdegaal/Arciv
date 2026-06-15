"""url_processor.py - URL processing for scraping: skip, rewrite, or pass through.

A URL runs through an ordered handler chain (see ``process_url``): fixed code
skips for plumbing (file extensions, image proxies, IP hosts), then the
user-editable :class:`~arciv.core.db.models.Rule` list, then the site-specific
rewriters, and finally :func:`canonicalize`. Each handler returns a
:class:`Skip`, a :class:`Rewrite`, or ``None`` ("no opinion, keep going"); the
first ``Skip`` ends processing and a ``Rewrite`` swaps the URL and continues.
"""

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    urlsplit,
    urlunparse,
    urlunsplit,
)

import tldextract

from arciv.core.db.models import Rule

# URL's ending with these suffixes are skipped entirely (like images)
SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    ".tiff",
    ".ico",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".mkv",
    ".json",
    ".xml",
)

# Path substrings that identify image-proxy/optimizer endpoints. These serve
# a (resized) image, not archivable content, and otherwise trigger a browser
# download (e.g. Next.js "/_next/image?url=...jpg").
SKIP_PATH_SUBSTRINGS = ("/_next/image",)

# Matches IP addresses as domain (e.g., "192.168.2.13", "10.0.0.1:8080")
_IP_DOMAIN_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$")

# File extensions that are human-readable (don't rewrite to repo root)
READABLE_EXTENSIONS = frozenset({".md", ".txt", ".rst"})

# Extensions served as plain text (skip trafilatura, store bytes directly)
RAW_TEXT_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".csv", ".tsv"})

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


def split_url(url: str) -> tuple[str, str]:
    """Split the registered domain and the path from a URL.

    Uses tldextract for accurate domain decomposition, returning only
    the registered domain (e.g. ``medium.com`` from ``aignishant.medium.com``).

    Args:
        url: The URL to extract from.

    Returns:
        A tuple of (domain, path) where domain is the registered domain
        without subdomains. ("", "") for URLs urlparse cannot handle
        (e.g. unclosed IPv6 brackets).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "", ""
    domain = tldextract.extract(url).top_domain_under_public_suffix

    # Fallback for edge cases where tldextract returns nothing useful
    if not domain:
        domain = parsed.netloc.removeprefix("www.").lower()

    return domain, parsed.path


def registered_domain(url: str) -> str:
    """Extract the registered domain from a URL.

    Returns the top-level domain under the public suffix
    (e.g. ``github.com`` from ``https://api.github.com/repos``).

    Args:
        url: The URL to extract from.

    Returns:
        The registered domain, or an empty string if not resolvable.
    """
    return tldextract.extract(url).top_domain_under_public_suffix


# Domain -> rewriter function
DOMAIN_REWRITERS: dict[str, Callable[[str], str]] = {
    "github.com": _rewrite_github,
    "raw.githubusercontent.com": _rewrite_raw_github,
    "huggingface.co": _rewrite_huggingface,
}


def is_raw_text_url(url: str) -> bool:
    """Check if a URL points to a raw text file that should skip HTML conversion.

    Args:
        url: The URL to check.

    Returns:
        True if the URL ends with a known plain-text extension.
    """
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    return any(path_lower.endswith(ext) for ext in RAW_TEXT_EXTENSIONS)


def is_pdf_url(url: str) -> bool:
    """Check if a URL points to a PDF file.

    Matches explicit ``.pdf`` extensions and known PDF-serving path patterns
    (e.g. arxiv ``/pdf/`` routes that serve PDFs without a file extension).

    Args:
        url: The URL to check.

    Returns:
        True if the URL likely serves a PDF.
    """
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return True
    # Paths like /pdf/2305.14406 serve PDFs directly (arxiv, etc.)
    segments = [s for s in path.split("/") if s]
    return len(segments) >= 2 and segments[0] == "pdf"


# Characters allowed in a slug: anything else would be unsafe (or illegal on
# Windows) in a directory name, e.g. ":" from a host with a port
_UNSAFE_SLUG_CHARS_RE = re.compile(r"[^A-Za-z0-9.\-]")


def slug_for_url(url: str) -> str:
    """Generate a slug (folder name) for a URL.

    The slug is used as the directory name under ``saved/`` where the
    page's HTML and markdown files are stored, so it must be a safe
    directory name on both Linux and Windows.

    Args:
        url: The processed/normalized URL.

    Returns:
        Slug in format "{domain}-{hash}", e.g. "github.com-a1b2c3d4".
    """
    domain, _ = split_url(url)
    safe_domain = _UNSAFE_SLUG_CHARS_RE.sub("-", domain) or "unknown"
    url_hash = hashlib.md5(url.encode("utf-8", errors="surrogatepass")).hexdigest()[:8]
    return f"{safe_domain}-{url_hash}"


# Query parameters that only carry tracking/analytics state, never identity.
# Matched case-insensitively against the parameter name.
_TRACKING_PARAM_RE = re.compile(
    r"^(?:utm_|fbclid$|gclid$|gclsrc$|dclid$|msclkid$|mc_eid$|mc_cid$"
    r"|igshid$|ref$|ref_src$|ref_url$|source$|spm$|_hsenc$|_hsmi$"
    r"|vero_id$|yclid$|wt_mc$|cmpid$|campaign$)",
    re.IGNORECASE,
)


def canonicalize(url: str) -> str:
    """Collapse equivalent URL forms to one canonical string.

    Applies the always-safe normalisations (lowercase host, drop default
    ports) plus the widely-safe heuristics (strip ``www.``, drop a trailing
    slash, remove tracking parameters, sort the query) so that forms which
    serve the same page resolve to a single identity, primary key, and slug.

    The path is treated as opaque (other than the trailing-slash trim):
    site-specific path rewrites are the rewriter's job, not this function's,
    which keeps unsafe per-site path transforms out of the always-on layer.

    Args:
        url: A processed https URL (post skip/rewrite).

    Returns:
        The canonical URL used as the page identity and slug input. Returns
        the input unchanged if it cannot be parsed.
    """
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").removeprefix("www.")
        port = parts.port
    except ValueError:
        # Malformed netloc (e.g. a non-numeric port): leave the URL as-is
        # rather than risk producing a different identity from a guess.
        return url

    netloc = host if port in (None, 80, 443) else f"{host}:{port}"

    path = parts.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAM_RE.match(k)
    ]
    query = urlencode(sorted(kept))

    return urlunsplit((parts.scheme, netloc, path, query, ""))


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


def _skip_suffix_handler(url: str) -> Skip | None:
    """Skip URLs ending in a non-content extension (.png, .json, …).

    Plumbing, not policy: nobody wants to manage the image/media list by hand,
    so it stays code rather than becoming an editable rule. ``.pdf`` is
    deliberately absent — PDFs are archived (and arxiv PDFs get rewritten)."""
    if urlparse(url).path.lower().endswith(SKIP_SUFFIXES):
        return Skip("URL matches skip suffix")
    return None


def _image_proxy_handler(url: str) -> Skip | None:
    """Skip image-proxy/optimizer endpoints (serve a resized image, not
    content), e.g. Next.js ``/_next/image?url=...``."""
    path_lower = urlparse(url).path.lower()
    if any(sub in path_lower for sub in SKIP_PATH_SUBSTRINGS):
        return Skip("URL is an image proxy endpoint")
    return None


def _ip_host_handler(url: str) -> Skip | None:
    """Skip URLs whose host is a bare IP address (local network, etc.)."""
    domain, _ = split_url(url)
    if _IP_DOMAIN_RE.match(domain):
        return Skip("URL domain is an IP address")
    return None


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


def _rule_matches(rule: Rule, url: str, netloc: str, domain: str) -> bool:
    """Whether a user rule's pattern matches this URL, per its match_type."""
    if rule.match_type == "domain":
        return domain == rule.pattern
    if rule.match_type == "host":
        return netloc == rule.pattern
    if rule.match_type == "starts_with":
        return url.startswith(rule.pattern)
    if rule.match_type == "exact":
        return url == rule.pattern
    if rule.match_type == "regex":
        try:
            return bool(re.search(rule.pattern, url, re.IGNORECASE))
        except re.error:
            return False
    return False


def _rules_handler(rules: Sequence[Rule]) -> UrlHandler:
    """Build a handler that applies the first matching user rule.

    The rules are walked in order (``PageDatabase.list_rules`` returns them by
    position); the first whose pattern matches wins, mirroring Bitwarden's
    match-and-action model. A skip stops the chain; a rewrite swaps the host
    (for non-regex matches) or applies a full URL rewrite with capture groups
    (for regex matches), then lets processing continue."""

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
                    # Regex rewrite: use capture groups ($1, $2, etc)
                    try:
                        new_url = re.sub(
                            rule.pattern,
                            rule.replacement,
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
                    # Non-regex rewrite: swap only the hostname
                    return Rewrite(parsed._replace(netloc=rule.replacement).geturl())
        return None

    return handler


# Fixed code handlers that run on every URL, before the user rules. These are
# plumbing (file extensions, image proxies, IP hosts), not editable policy.
_CODE_SKIP_HANDLERS: tuple[UrlHandler, ...] = (
    _skip_suffix_handler,
    _image_proxy_handler,
    _ip_host_handler,
)


def process_url(url: str, rules: Sequence[Rule] = ()) -> tuple[str | None, str]:
    """Process a URL for scraping: skip it, rewrite it, or pass it through.

    Runs the URL through the handler chain (see the module docstring): cheap
    guards and host normalisation first, then the fixed code skips, then the
    user ``rules``, then the site rewriters, and finally :func:`canonicalize`.

    Args:
        url: The URL to process.
        rules: User-editable rules to apply, in order (see
            ``PageDatabase.list_rules``). Defaults to none, so callers that
            only want the built-in code handlers can omit it.

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
        *_CODE_SKIP_HANDLERS,
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
