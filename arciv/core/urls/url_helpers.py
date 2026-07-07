"""url_helpers.py - Pure URL utilities: decomposition, classification, slugs.

These are stateless helpers with no opinion about the skip/rewrite pipeline
(that lives in :mod:`arciv.core.urls.url_processing`). They cover splitting a
URL into domain and path, recognising PDF/raw-text URLs, generating the
on-disk slug, and collapsing equivalent URL forms to one canonical string.
"""

import hashlib
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    urlsplit,
    urlunsplit,
)

import tldextract
from w3lib.url import canonicalize_url as _w3lib_canonicalize_url

# Extensions served as plain text (skip trafilatura, store bytes directly)
RAW_TEXT_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".csv", ".tsv"})


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


def slug_for_url(url: str, domain: str | None = None) -> str:
    """Generate a slug (folder name) for a URL.

    The slug is used as the directory name under ``saved/`` where the
    page's HTML and markdown files are stored, so it must be a safe
    directory name on both Linux and Windows.

    Args:
        url: The processed/normalized URL.
        domain: The URL's registered domain, if the caller already resolved it
            (via ``split_url``/``registered_domain``). Passed through to skip a
            redundant ``split_url`` — and its tldextract call — since callers
            building a page entry compute the same domain right alongside the
            slug. When None it is resolved here.

    Returns:
        Slug in format "{domain}-{hash}", e.g. "github.com-a1b2c3d4e5f60718".
    """
    if domain is None:
        domain, _ = split_url(url)
    safe_domain = _UNSAFE_SLUG_CHARS_RE.sub("-", domain) or "unknown"
    # 16 hex chars = 64 bits: collisions within one domain are negligible at
    # any personal-archive scale (8 chars/32 bits reached ~1% at 10k pages).
    # Slugs already stored in the DB keep their old 8-char form; only new
    # pages get the wider hash, and the two never collide structurally.
    url_hash = hashlib.md5(url.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
    return f"{safe_domain}-{url_hash}"


# Query parameters that only carry tracking/analytics state, never identity.
# Matched case-insensitively against the parameter name. Only unambiguous
# tracker names belong here: generic words some sites use for real routing
# (ref, source, campaign) are deliberately absent, because stripping an
# identity-bearing param silently collapses two different pages into one
# archive entry. Strip those per-site via rules.toml if a site needs it.
_TRACKING_PARAM_RE = re.compile(
    r"^(?:utm_|fbclid$|gclid$|gclsrc$|dclid$|msclkid$|mc_eid$|mc_cid$"
    r"|igshid$|ref_src$|ref_url$|spm$|_hsenc$|_hsmi$"
    r"|vero_id$|yclid$|wt_mc$|cmpid$)",
    re.IGNORECASE,
)


def canonicalize(url: str) -> str:
    """Collapse equivalent URL forms to one canonical string.

    Two layers. The opinionated one lives here: strip ``www.``, drop a
    trailing slash and default ports, remove tracking parameters, sort the
    query. The mechanical one (consistent percent-encoding of path and
    query, IDNA hosts) is delegated to w3lib's ``canonicalize_url`` as the
    final step, so encoding variants of the same URL collapse without this
    module owning the escaping rules.

    The path is treated as opaque (other than the trailing-slash trim and
    w3lib's encoding normalisation): site-specific path rewrites are the
    rewriter's job, not this function's, which keeps unsafe per-site path
    transforms out of the always-on layer.

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

    stripped = urlunsplit((parts.scheme, netloc, path, query, ""))
    try:
        return _w3lib_canonicalize_url(stripped)
    except (ValueError, UnicodeError):
        # w3lib refuses some pathological inputs (bad IDNA, invalid escapes);
        # the un-normalised form is still a usable, stable identity.
        return stripped
