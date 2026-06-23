"""Download inline images from extracted markdown into the page's folder.

trafilatura (with ``include_images``) emits ``![alt](src)`` for the images it
recognizes. This module downloads each remote image into the page's
``images/`` subfolder and rewrites the link to the local copy
(``![alt](images/<name>)``), so the archived ``page.md`` is self-contained and
renders offline next to its images.

Relative ``src`` values are resolved against the page URL, which trafilatura
leaves untouched (it only rewrites protocol-relative ``//`` URLs). Downloads
are idempotent: a file already on disk is reused, so re-parsing a page does no
network work after the first pass. An image that can't be resolved or
downloaded keeps its original link, so nothing is silently dropped.
"""

import hashlib
import re
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from loguru import logger

# Markdown image: ![alt](src). The src stops at the first ")" or whitespace;
# trafilatura emits bare URLs (no <>-wrapping, no spaces), so this suffices.
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")

# Subfolder (under the page's slug dir) that holds the downloaded images. The
# rewritten links are relative to it, so page.md resolves them on disk.
IMAGES_SUBDIR = "images"

# Per-image download timeout, matching the PDF download path in the fetcher.
_TIMEOUT_S = 30

# Some hosts 403 the default urllib agent; present as a normal client.
_USER_AGENT = "Mozilla/5.0 (compatible; Arciv/1.0; +archival)"


def _local_name(abs_url: str) -> str:
    """Build a stable, clean local filename for an image URL.

    The name is a hash of the absolute URL plus the original (lowercased)
    extension, so the same image always maps to the same file: re-parsing is
    idempotent and duplicate references share a single download. The hex name
    is deliberately free of uppercase/underscores so the downstream markdown
    cleaner never mangles the rewritten link.
    """
    digest = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:16]
    suffix = Path(urlsplit(abs_url).path).suffix.lower()
    # trafilatura only emits known image extensions, but guard against junk.
    if not suffix or len(suffix) > 6:
        suffix = ".img"
    return f"{digest}{suffix}"


def _absolute_url(base_url: str | None, src: str) -> str | None:
    """Resolve a markdown image src to an absolute http(s) URL, or None.

    Relative srcs are joined against ``base_url`` (the page URL), since
    trafilatura does not resolve them. ``data:`` URIs and non-http(s) schemes
    return None: there is nothing to download.
    """
    if src.startswith("data:"):
        return None
    abs_url = urljoin(base_url, src) if base_url else src
    if urlsplit(abs_url).scheme not in ("http", "https"):
        return None
    return abs_url


def _download(abs_url: str, dest: Path) -> bool:
    """Download an image to ``dest``. Returns True on success.

    The bytes are written to a ``.part`` temp file and renamed into place, so
    an interrupted download never leaves a truncated file that a later reparse
    would mistake for a cached image. The target folder is created only once
    real bytes are in hand, so failed pages don't leave empty ``images/`` dirs.
    """
    request = urllib.request.Request(abs_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            data = response.read()
    except Exception as e:
        logger.warning(f"Image download failed {abs_url}: {e}")
        return False

    if not data:
        # An empty body is a broken image; don't cache a 0-byte file that a
        # later reparse would treat as a valid download and never retry.
        logger.warning(f"Image download empty {abs_url}")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return True


def localize_images(
    markdown: str, base_url: str | None, images_dir: Path
) -> tuple[str, int]:
    """Download the images referenced in ``markdown`` and localize their links.

    Each ``![alt](src)`` is resolved against ``base_url``, downloaded into
    ``images_dir``, and rewritten to ``![alt](images/<name>)``. Images already
    on disk are reused without a network request. A src that can't be resolved
    or downloaded keeps its original link.

    Run this before the markdown cleaner: it replaces arbitrary remote URLs
    (which the cleaner can mangle) with clean local paths, leaving only failed
    or non-downloadable links remote.

    Args:
        markdown: Extracted markdown, possibly containing remote image links.
        base_url: The page URL, used to resolve relative image srcs.
        images_dir: Target folder for downloaded images (``<slug>/images``).

    Returns:
        Tuple of (rewritten markdown, number of localized image links).
    """
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        alt, src = match.group(1), match.group(2)
        abs_url = _absolute_url(base_url, src)
        if abs_url is None:
            return match.group(0)

        name = _local_name(abs_url)
        dest = images_dir / name
        if not dest.exists() and not _download(abs_url, dest):
            return match.group(0)

        count += 1
        return f"![{alt}]({IMAGES_SUBDIR}/{name})"

    return _IMAGE_RE.sub(replace, markdown), count


def strip_image_links(markdown: str) -> str:
    """Remove markdown image syntax so word counts reflect prose.

    Image links carry no prose, but their alt text and URL/path tokens would
    otherwise be counted as words (a hash-named local path adds ~3 tokens per
    image). Stripping them keeps ``word_count`` meaning the same thing it did
    before images were stored inline, so the length gate stays calibrated.
    """
    return _IMAGE_RE.sub("", markdown)
