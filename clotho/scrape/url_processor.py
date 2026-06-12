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

# Domains ending with these suffixes are skipped (handles subdomains)
SKIP_DOMAIN_SUFFIXES = (
    "sharepoint.com",
    "getvirtualbrain.com",
    "content.powerapps.com",
    "app.fabric.microsoft.com",
    "app.powerbi.com",
    "youtube.com",
    "youtu.be",
    "azure.com",
)

# Exact domain + path prefix combinations that are not archivable content.
# These get marked "skipped (not content)" instead of cluttering failure logs.
SKIP_DOMAINS: set[str] = {
    "claude.ai",
    "lnkd.in",
    "support.dfg.nl",
}
SKIP_DOMAIN_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "google.com": ("/search",),
}

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
        host = host.lower()

    # Skip specific prefixes
    if url.startswith(SKIP_PREFIXES):
        return None, "URL matches skip prefix"

    # Skip specific suffixes (but not .pdf — arxiv PDFs get rewritten)
    path_lower = parsed.path.lower()
    if path_lower.endswith(SKIP_SUFFIXES):
        return None, "URL matches skip suffix"

    # Skip image-proxy/optimizer endpoints (serve images, not content)
    if any(sub in path_lower for sub in SKIP_PATH_SUBSTRINGS):
        return None, "URL is an image proxy endpoint"

    # Skip IP addresses (local network, etc.)
    domain, _ = split_url(url)
    if _IP_DOMAIN_RE.match(domain):
        return None, "URL domain is an IP address"

    # Skip domains by suffix (handles subdomains)
    if domain.endswith(SKIP_DOMAIN_SUFFIXES):
        return None, "URL domain matches skip suffix"

    # Skip non-content domains (chat links, shorteners, internal tools)
    if domain in SKIP_DOMAINS:
        return None, "skipped (not content)"

    # Skip domain + path prefix combos (e.g. google.com/search)
    if domain in SKIP_DOMAIN_PATH_PREFIXES:
        for prefix in SKIP_DOMAIN_PATH_PREFIXES[domain]:
            if parsed.path.startswith(prefix):
                return None, "skipped (not content)"

    # Apply rewriters. Try the full host first (raw.githubusercontent.com),
    # then the registered domain (github.com, huggingface.co) — tldextract
    # collapses subdomains, so host-keyed rewriters never match on domain.
    rewriter = DOMAIN_REWRITERS.get(host) or DOMAIN_REWRITERS.get(domain)
    if rewriter is not None:
        return rewriter(url), "Success (rewritten)"

    return url, "Success"
