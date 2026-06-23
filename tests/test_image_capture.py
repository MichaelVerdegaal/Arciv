"""Tests for in-browser image capture (driven with duck-typed fakes)."""

import asyncio

from arciv.core.fetch.image_capture import (
    MIN_IMAGE_BYTES,
    ImageCapturer,
    _ext_for,
    autoscroll,
)


class _FakeRequest:
    def __init__(self, url: str, resource_type: str = "image"):
        self.url = url
        self.resource_type = resource_type


class _FakeResponse:
    def __init__(
        self,
        url: str,
        body: bytes,
        status: int = 200,
        content_type: str = "image/png",
        resource_type: str = "image",
        request_url: str | None = None,
    ):
        self.url = url
        self._body = body
        self.status = status
        self.headers = {"content-type": content_type} if content_type else {}
        self.request = _FakeRequest(request_url or url, resource_type)

    async def finished(self):
        return None

    async def body(self):
        return self._body


_BIG = b"x" * (MIN_IMAGE_BYTES + 10)


def _capture(images_dir, *responses) -> ImageCapturer:
    """Run _read for each response under one event loop and return the capturer."""

    async def run():
        cap = ImageCapturer(images_dir)
        for resp in responses:
            await cap._read(resp)
        return cap

    return asyncio.run(run())


class TestExtFor:
    def test_from_url_suffix(self):
        assert _ext_for("https://x.com/a.PNG?w=2", "image/jpeg") == ".png"

    def test_jpeg_normalized_to_jpg(self):
        assert _ext_for("https://x.com/a.jpeg", "") == ".jpg"

    def test_falls_back_to_content_type(self):
        assert _ext_for("https://x.com/image", "image/webp") == ".webp"


class TestImageCapturer:
    def test_saves_image_and_records_both_url_keys(self, tmp_path):
        images = tmp_path / "images"
        cap = _capture(
            images,
            _FakeResponse(
                "https://cdn.example.com/final.png",
                _BIG,
                request_url="https://example.com/orig.png",
            ),
        )
        files = list(images.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".png"
        # Both the final and original URL map to the saved file (redirects).
        assert cap.manifest["https://cdn.example.com/final.png"] == files[0].name
        assert cap.manifest["https://example.com/orig.png"] == files[0].name

    def test_skips_tiny_images(self, tmp_path):
        images = tmp_path / "images"
        cap = _capture(images, _FakeResponse("https://x.com/pixel.gif", b"tiny"))
        assert cap.manifest == {}
        assert not images.exists()

    def test_skips_redirects(self, tmp_path):
        images = tmp_path / "images"
        cap = _capture(images, _FakeResponse("https://x.com/r.png", _BIG, status=301))
        assert cap.manifest == {}

    def test_skips_non_images(self, tmp_path):
        images = tmp_path / "images"
        cap = _capture(
            images,
            _FakeResponse(
                "https://x.com/app.js",
                _BIG,
                content_type="application/javascript",
                resource_type="script",
            ),
        )
        assert cap.manifest == {}

    def test_detects_image_by_content_type(self, tmp_path):
        # resource_type isn't "image" but the content-type is.
        images = tmp_path / "images"
        cap = _capture(
            images,
            _FakeResponse(
                "https://x.com/asset",
                _BIG,
                content_type="image/webp",
                resource_type="fetch",
            ),
        )
        assert len(cap.manifest) == 1
        assert list(images.iterdir())[0].suffix == ".webp"

    def test_dedups_identical_bytes(self, tmp_path):
        images = tmp_path / "images"
        cap = _capture(
            images,
            _FakeResponse("https://x.com/a.png", _BIG),
            _FakeResponse("https://x.com/b.png", _BIG),
        )
        # Same bytes -> one file, two manifest entries pointing at it.
        assert len(list(images.iterdir())) == 1
        assert len(cap.manifest) == 2
        assert len(set(cap.manifest.values())) == 1


class TestAutoscroll:
    def test_swallows_evaluate_errors(self):
        class _Page:
            async def evaluate(self, _js):
                raise RuntimeError("execution context destroyed")

        # Should not raise.
        asyncio.run(autoscroll(_Page()))

    def test_calls_evaluate(self):
        called = []

        class _Page:
            async def evaluate(self, js):
                called.append(js)

        asyncio.run(autoscroll(_Page()))
        assert called and "scrollTo" in called[0]
