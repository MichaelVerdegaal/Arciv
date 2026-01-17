"""url_processor.py - URL processing for scraping: skip, rewrite, or pass through."""

import re
from collections.abc import Callable
from urllib.parse import urlparse, urlunparse

# URLs starting with these prefixes are skipped entirely
SKIP_PREFIXES = (
    "https://localhost",
    "https://app.powerbi.com/",
    "https://app.fabric.microsoft.com/",
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


def split_url(url: str) -> tuple[str, str]:
    """Split the domain and the path from a URL.

    Args:
        url: The URL to extract from

    Returns:
        A tuple of (domain, path) where domain has 'www.' prefix removed
    """
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    path = parsed.path
    return domain.lower(), path


# Domain -> rewriter function
DOMAIN_REWRITERS: dict[str, Callable[[str], str]] = {
    "github.com": _rewrite_github,
    "raw.githubusercontent.com": _rewrite_raw_github,
}


def process_url(url: str) -> str | None:
    """Process URL for scraping.

    Args:
        url: The URL to process

    Returns:
        None if URL should be skipped, otherwise the URL to scrape
        (possibly rewritten)
    """
    # Only process https URLs
    if not url.startswith("https://"):
        return None

    # Skip specific prefixes
    if url.startswith(SKIP_PREFIXES):
        return None

    # Skip IP addresses (local network, etc.)
    domain, _ = split_url(url)
    if _IP_DOMAIN_RE.match(domain):
        return None

    # Apply rewriters
    if domain in DOMAIN_REWRITERS:
        return DOMAIN_REWRITERS[domain](url)

    return url
