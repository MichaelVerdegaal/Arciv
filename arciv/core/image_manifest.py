"""Shared format for the per-page image manifest.

The fetch stage captures a page's images in-browser and writes a
``url -> filename`` manifest; the parse stage reads it to point markdown image
links at the captured files. Both stages must canonicalize URLs identically
for the lookup to hit, so the format (the filename, the normalization, and the
read/write helpers) lives here, in a module neither stage's package ``__init__``
pulls anything heavy into — fetch must not import trafilatura, parse must not
import patchright.
"""

import json
from pathlib import Path
from urllib.parse import urldefrag, urlsplit, urlunsplit

from loguru import logger

# Subfolder, under the page's slug dir, holding the captured image files. The
# rewritten markdown links are relative to the slug dir, so they resolve on disk.
IMAGES_SUBDIR = "images"

# Manifest file, written next to page.html in the slug dir.
MANIFEST_NAME = "image_manifest.json"


def normalize_url(url: str) -> str:
    """Canonicalize a URL for manifest lookup: drop fragment, lowercase host.

    Deliberately conservative — path and query are kept verbatim, since two
    image URLs that differ there are usually different images. The point is
    only to make the fetch-side key and the parse-side lookup agree.
    """
    try:
        defragged, _ = urldefrag(url)
        parts = urlsplit(defragged)
        return urlunsplit(parts._replace(netloc=parts.netloc.lower()))
    except ValueError:
        return url


def load_manifest(slug_dir: Path) -> dict[str, str]:
    """Read a page's image manifest, or an empty dict if it has none.

    Pages fetched before image capture existed (or with no images) simply have
    no manifest, so the parse stage links nothing and leaves remote URLs as-is.
    A corrupt manifest is treated as empty rather than failing the parse.
    """
    path = slug_dir / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Ignoring unreadable image manifest {path}: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(slug_dir: Path, manifest: dict[str, str]) -> None:
    """Write a page's image manifest (atomically); no-op for an empty manifest."""
    if not manifest:
        return
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / MANIFEST_NAME
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
