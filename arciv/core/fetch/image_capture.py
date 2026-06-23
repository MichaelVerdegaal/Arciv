"""Capture a page's images in-browser during the fetch.

A real browser downloads a page's images as it loads; the fetcher lets that
happen (it no longer blocks the ``image`` resource type) and this module
siphons the bytes off the responses as they arrive. Capturing inside the same
stealthy patchright session is the whole point: no second, fingerprint-different
round-trip to the origin, and the downloads run concurrently with page load
instead of one-at-a-time afterward.

Bytes land in ``<slug>/images/<sha256>.<ext>`` (content-hashed, so a repeated
image is stored once) and a normalized ``url -> filename`` manifest is written
for the parse stage, which links the images trafilatura keeps without ever
touching the network. The objects passed in (``page``/``response``) are
duck-typed Playwright handles, so this module needs no patchright import.
"""

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from arciv.core.image_manifest import normalize_url

# Skip sub-kilobyte responses: tracking pixels, spacers, 1x1 beacons.
MIN_IMAGE_BYTES = 1024
# Bound per-page disk/memory use on media-heavy or hostile pages. With the
# fetch batch running several pages at once, keep the per-page ceiling modest.
MAX_IMAGES = 200
MAX_TOTAL_BYTES = 32 * 1024 * 1024
# Cap concurrent in-memory image bodies per page.
_READ_CONCURRENCY = 6

# Bounded autoscroll so lazy/off-screen images load before we drain. Hard time
# budget keeps infinite-scroll pages from stalling the fetch.
_AUTOSCROLL_JS = """
async () => {
  const pause = 150, step = 1000, budgetMs = 5000;
  const start = Date.now();
  let last = -1;
  while (Date.now() - start < budgetMs) {
    const h = document.documentElement.scrollHeight;
    for (let y = 0; y < h && (Date.now() - start) < budgetMs; y += step) {
      window.scrollTo(0, y);
      await new Promise(r => setTimeout(r, pause));
    }
    if (h === last) break;
    last = h;
  }
  window.scrollTo(0, 0);
}
"""

_EXT_BY_CTYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/x-icon": ".ico",
    "image/tiff": ".tiff",
}
_KNOWN_EXTS = {
    ".jpg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp", ".ico", ".tiff",
}  # fmt: skip


def _ext_for(url: str, content_type: str) -> str:
    """Pick a file extension from the URL path, falling back to content type."""
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    if suffix in _KNOWN_EXTS:
        return suffix
    return (
        _EXT_BY_CTYPE.get(content_type)
        or mimetypes.guess_extension(content_type or "")
        or ".bin"
    )


async def autoscroll(page: Any) -> None:
    """Scroll the page to trigger lazy-loaded images, bounded by a time budget.

    Best-effort: any failure (navigation, closed page, CSP blocking eval) is
    swallowed, since scrolling is an enhancement, not a requirement.
    """
    try:
        await page.evaluate(_AUTOSCROLL_JS)
    except Exception as e:
        logger.debug(f"Autoscroll skipped: {e}")


class ImageCapturer:
    """Collects image bytes from a single page load. One instance per page.

    Lifecycle: :meth:`attach` before navigation, :meth:`drain` after the page
    has loaded (and crucially *before* it closes, or in-flight body reads fail),
    then read :attr:`manifest`.
    """

    def __init__(self, images_dir: Path) -> None:
        self.images_dir = images_dir
        self.manifest: dict[str, str] = {}  # normalized url -> filename
        self._names: set[str] = set()
        self._total_bytes = 0
        self._tasks: list[asyncio.Task] = []
        self._sem = asyncio.Semaphore(_READ_CONCURRENCY)

    def attach(self, page: Any) -> None:
        """Subscribe to the page's responses; call before navigating."""
        page.on("response", self._on_response)

    def _on_response(self, response: Any) -> None:
        # The event callback must not block, so schedule the body read.
        self._tasks.append(asyncio.create_task(self._read(response)))

    async def _read(self, response: Any) -> None:
        """Save one image response's bytes and record it in the manifest."""
        try:
            request = response.request
            ctype = (
                (response.headers or {})
                .get("content-type", "")
                .split(";")[0]
                .strip()
                .lower()
            )
            is_image = request.resource_type == "image" or ctype.startswith("image/")
            if not is_image:
                return
            # Redirects carry no body; the bytes arrive on the redirected request.
            if 300 <= response.status < 400:
                return
            # Stop reading more bodies once the page hits its budget.
            if len(self._names) >= MAX_IMAGES or self._total_bytes >= MAX_TOTAL_BYTES:
                return
            async with self._sem:
                await response.finished()
                body = await response.body()
        except Exception:
            # Body unavailable (redirect, target closed, purged) — skip quietly.
            return

        if not body or len(body) < MIN_IMAGE_BYTES:
            return

        digest = hashlib.sha256(body).hexdigest()[:16]
        name = f"{digest}{_ext_for(response.url, ctype)}"
        if name not in self._names:
            if (
                len(self._names) >= MAX_IMAGES
                or self._total_bytes + len(body) > MAX_TOTAL_BYTES
            ):
                return
            self._write(name, body)
            self._names.add(name)
            self._total_bytes += len(body)

        # Key on both the final and original URL so a redirected image still
        # matches the (original) src trafilatura emits.
        for url in {normalize_url(response.url), normalize_url(request.url)}:
            self.manifest[url] = name

    def _write(self, name: str, body: bytes) -> None:
        """Write image bytes via a temp file, so an interrupt leaves no stub."""
        self.images_dir.mkdir(parents=True, exist_ok=True)
        dest = self.images_dir / name
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)

    async def drain(self) -> None:
        """Await every scheduled body read. Call before the page closes."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
