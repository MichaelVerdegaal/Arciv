"""url_processor.py - URL processing for scraping: skip, rewrite, or pass through."""

import hashlib
import re
from collections.abc import Callable
from urllib.parse import urlparse, urlunparse

import tldextract

# URLs starting with these prefixes are skipped entirely
SKIP_PREFIXES = ("https://localhost",)

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
    ".pdf",  # TODO: this contains readable text, but needs special conversion
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".mkv",
)

# Domains ending with these suffixes are skipped (handles subdomains)
SKIP_DOMAIN_SUFFIXES = (
    "sharepoint.com",
    "getvirtualbrain.com",
    "content.powerapps.com",
    "app.fabric.microsoft.com",
    "app.powerbi.com",
    "youtube.com",
    "youtu.be",
    "azure.com"
)

# Matches IP addresses as domain (e.g., "192.168.2.13", "10.0.0.1:8080")
_IP_DOMAIN_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$")

# File extensions that are human-readable (don't rewrite to repo root)
READABLE_EXTENSIONS = frozenset({".md", ".txt", ".rst"})

# GitHub path patterns
_GITHUB_BLOB_TREE_RE = re.compile(r"^/([^/]+/[^/]+)/(?:blob|tree)/")
_RAW_GITHUB_PATH_RE = re.compile(r"^/([^/]+/[^/]+)/")


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


def _rewrite_medium(url: str) -> str:
    """Rewrite Medium URLs to use Freedium mirror.

    E.g. https://medium.com/data-science/topic-modeling-with-bert-779f7db187e6
         -> https://freedium-mirror.cfd/https://medium.com/data-science/topic-modeling-with-bert-779f7db187e6
    """
    return f"https://freedium-mirror.cfd/{url}"


def split_url(url: str) -> tuple[str, str]:
    """Split the registered domain and the path from a URL.

    Uses tldextract for accurate domain decomposition, returning only
    the registered domain (e.g. ``medium.com`` from ``aignishant.medium.com``).

    Args:
        url: The URL to extract from.

    Returns:
        A tuple of (domain, path) where domain is the registered domain
        without subdomains.
    """
    parsed = urlparse(url)
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
    "medium.com": _rewrite_medium,
}


def hash_filename(url: str, extension: str = ".md") -> str:
    """Generate a hashed filename from a URL.

    Args:
        url: The URL to hash.
        extension: File extension including the dot.

    Returns:
        Filename in format "{domain}-{hash}{extension}".
    """
    domain, _ = split_url(url)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{domain}-{url_hash}{extension}"


def process_url(url: str) -> tuple[str | None, str]:
    """Process URL for scraping.

    Args:
        url: The URL to process

    Returns:
        URL to scrape or None if skipped, and a status message.
    """
    # Only process https URLs
    if not url.startswith("https://"):
        return None, "URL does not begin with HTTPS"

    # Skip specific prefixes
    if url.startswith(SKIP_PREFIXES):
        return None, "URL matches skip prefix"

    # Skip specific suffixes
    if url.lower().endswith(SKIP_SUFFIXES):
        return None, "URL matches skip suffix"

    # Skip IP addresses (local network, etc.)
    domain, _ = split_url(url)
    if _IP_DOMAIN_RE.match(domain):
        return None, "URL domain is an IP address"

    # Skip domains by suffix (handles subdomains)
    if domain.endswith(SKIP_DOMAIN_SUFFIXES):
        return None, "URL domain matches skip suffix"

    # Apply rewriters
    if domain in DOMAIN_REWRITERS:
        return DOMAIN_REWRITERS[domain](url), "Success (rewritten)"

    return url, "Success"
