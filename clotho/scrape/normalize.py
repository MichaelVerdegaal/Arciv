"""URL normalization for site-specific preprocessing.

This module provides URL normalization to transform URLs pointing to specific
resources (files, directories) back to canonical forms suitable for content
extraction. For example, GitHub file URLs are normalized to repository roots
so we can extract READMEs instead of code files.
"""

import re
from collections.abc import Callable
from urllib.parse import urlparse, urlunparse

# GitHub path patterns for file/directory views
_GITHUB_BLOB_TREE_RE = re.compile(r"^/([^/]+/[^/]+)/(?:blob|tree)/")

# File extensions that should not be normalized (readable content files)
_READABLE_EXTENSIONS = frozenset({".md", ".txt", ".rst"})

# Registry mapping domain patterns to normalizer functions
_NORMALIZERS: dict[str, Callable[[str], str]] = {}


def _register_normalizer(
    domain: str,
) -> Callable[[Callable[[str], str]], Callable[[str], str]]:
    """Decorator to register a normalizer function for a domain.

    Args:
        domain: The domain to match (e.g., "github.com").

    Returns:
        Decorator that registers the function and returns it unchanged.
    """

    def decorator(func: Callable[[str], str]) -> Callable[[str], str]:
        _NORMALIZERS[domain] = func
        return func

    return decorator


@_register_normalizer("github.com")
def _normalize_github_url(url: str) -> str:
    """Normalize GitHub URLs to repository root.

    Transforms URLs pointing to specific files or directories (blob/tree paths)
    back to the repository root URL. This enables README extraction instead of
    code file content.

    URLs pointing to readable files (.md, .txt, .rst) are preserved unchanged
    since their content can be extracted directly.

    Args:
        url: A GitHub URL string.

    Returns:
        The normalized URL pointing to the repository root, or the original
        URL if it's already a repository root, points to a readable file,
        or doesn't match expected patterns.

    Examples:
        >>> _normalize_github_url("https://github.com/pytorch/captum/blob/main/file.py#L86")
        'https://github.com/pytorch/captum'
        >>> _normalize_github_url("https://github.com/pytorch/captum/tree/main/dir")
        'https://github.com/pytorch/captum'
        >>> _normalize_github_url("https://github.com/pytorch/captum")
        'https://github.com/pytorch/captum'
        >>> _normalize_github_url("https://github.com/unit8co/darts/blob/master/docs/examples.rst")
        'https://github.com/unit8co/darts/blob/master/docs/examples.rst'
    """
    parsed = urlparse(url)

    # Check if this is a blob/tree URL that needs normalization
    match = _GITHUB_BLOB_TREE_RE.match(parsed.path)

    # Preserve URLs pointing to readable files (.md, .txt, .rst)
    if match:
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in _READABLE_EXTENSIONS):
            return url

    path = f"/{match.group(1)}" if match else parsed.path.rstrip("/")

    # Rebuild URL without fragment and with normalized path
    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            "",  # params
            "",  # query (could preserve if needed)
            "",  # fragment (strip line numbers like #L86)
        )
    )

    return normalized


def normalize_url(url: str) -> str:
    """Normalize a URL using site-specific handlers.

    Dispatches to registered normalizers based on the URL's domain. URLs for
    domains without registered normalizers are returned unchanged.

    Args:
        url: The URL string to normalize.

    Returns:
        The normalized URL string. Returns the original URL unchanged if no
        normalizer is registered for the domain.

    Examples:
        >>> normalize_url("https://github.com/pytorch/captum/blob/main/file.py")
        'https://github.com/pytorch/captum'
        >>> normalize_url("https://boundaryml.com/blog/post")
        'https://boundaryml.com/blog/post'
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Check for exact domain match
    if domain in _NORMALIZERS:
        return _NORMALIZERS[domain](url)

    # Check for subdomain matches (e.g., "www.github.com" matches "github.com")
    for registered_domain, normalizer in _NORMALIZERS.items():
        if domain.endswith(f".{registered_domain}"):
            return normalizer(url)

    return url
