"""Link extracted markdown images to the copies captured during fetch.

The fetch stage captures a page's images in-browser and records a normalized
``url -> filename`` manifest (see ``arciv.core.image_manifest``). This module
rewrites the ``![alt](src)`` links trafilatura emits to point at those local
files (``![alt](images/<name>)``), so the parse stage stays offline — no image
is downloaded here. An image the page never loaded (or that failed to capture)
has no manifest entry and keeps its remote link, ready for a future fallback
fetch.
"""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from arciv.core.image_manifest import IMAGES_SUBDIR, normalize_url

# Markdown image: ![alt](src). The src stops at the first ")" or whitespace;
# trafilatura emits bare URLs (no <>-wrapping, no spaces), so this suffices.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def _absolute_url(base_url: str | None, src: str) -> str | None:
    """Resolve a markdown image src to an absolute http(s) URL, or None.

    Relative srcs are joined against ``base_url`` (the page URL), since
    trafilatura leaves them unresolved. ``data:``/``blob:`` and non-http(s)
    schemes return None: they were never fetched as separate resources.
    """
    if src.startswith(("data:", "blob:")):
        return None
    abs_url = urljoin(base_url, src) if base_url else src
    if urlsplit(abs_url).scheme not in ("http", "https"):
        return None
    return abs_url


def _strip_query(url: str) -> str:
    """Drop the query and fragment, for CDN-variant fallback matching."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query="", fragment=""))


def relink_images(
    markdown: str, base_url: str | None, manifest: dict[str, str]
) -> tuple[str, int]:
    """Rewrite image links to the local files captured during fetch.

    Each ``![alt](src)`` is resolved against ``base_url`` and looked up in the
    fetch-time ``manifest`` (normalized url -> filename). A hit is rewritten to
    ``![alt](images/<name>)``; a miss keeps its original link. A query-stripped
    fallback catches images served from a slightly different CDN-variant URL
    than the one in the page source.

    Args:
        markdown: Extracted markdown, possibly containing remote image links.
        base_url: The page URL, used to resolve relative image srcs.
        manifest: The fetch-stage image manifest (empty for pages with none).

    Returns:
        Tuple of (rewritten markdown, number of links pointed at local files).
    """
    if not manifest:
        return markdown, 0

    by_path = {}
    for url, name in manifest.items():
        by_path.setdefault(_strip_query(url), name)

    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        alt, src = match.group(1), match.group(2)
        abs_url = _absolute_url(base_url, src)
        if abs_url is None:
            return match.group(0)

        key = normalize_url(abs_url)
        name = manifest.get(key) or by_path.get(_strip_query(key))
        if not name:
            return match.group(0)

        count += 1
        return f"![{alt}]({IMAGES_SUBDIR}/{name})"

    return _IMAGE_RE.sub(replace, markdown), count


def strip_image_links(markdown: str) -> str:
    """Remove markdown image syntax so word counts reflect prose.

    Image links carry no prose, but their alt text and URL/path tokens would
    otherwise be counted as words. Stripping them keeps ``word_count`` meaning
    the same thing it did before images were stored inline, so the length gate
    stays calibrated.
    """
    return _IMAGE_RE.sub("", markdown)
