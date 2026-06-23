"""Tests for inline-image localization (download + link rewrite)."""

import urllib.request

import pytest

from arciv.core.parse import images
from arciv.core.parse.images import localize_images


class _FakeResponse:
    """Minimal stand-in for the object urlopen yields as a context manager."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._data


@pytest.fixture
def fake_download(monkeypatch):
    """Patch urlopen to serve fixed bytes and record the URLs it was asked for.

    Returns the list of requested URLs so a test can assert how many real
    downloads happened (idempotency).
    """
    requested: list[str] = []

    def fake_urlopen(request, timeout=0):
        requested.append(request.full_url)
        return _FakeResponse(b"\x89PNG fake image bytes")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requested


class TestLocalizeImages:
    def test_downloads_and_rewrites_absolute_url(self, tmp_path, fake_download):
        images_dir = tmp_path / "images"
        md, count = localize_images(
            "![A cat](https://example.com/cat.png)", None, images_dir
        )

        assert count == 1
        # Link now points at a local file inside the images/ subfolder.
        assert "](images/" in md
        assert "https://example.com" not in md
        # Exactly one file was written, and it carries the original extension.
        saved = list(images_dir.iterdir())
        assert len(saved) == 1
        assert saved[0].suffix == ".png"
        assert saved[0].read_bytes() == b"\x89PNG fake image bytes"

    def test_resolves_relative_url_against_base(self, tmp_path, fake_download):
        images_dir = tmp_path / "images"
        _, count = localize_images(
            "![](/static/diagram.png)", "https://example.com/blog/post", images_dir
        )

        assert count == 1
        # The relative src was resolved to an absolute URL before downloading.
        assert fake_download == ["https://example.com/static/diagram.png"]

    def test_idempotent_reuses_cached_file(self, tmp_path, fake_download):
        images_dir = tmp_path / "images"
        md = "![one](https://example.com/a.png) ![two](https://example.com/a.png)"

        first, count = localize_images(md, None, images_dir)
        # Same URL twice in one pass: downloaded once, both links rewritten.
        assert count == 2
        assert len(fake_download) == 1

        # Re-running (a reparse) downloads nothing: the file is already on disk.
        second, _ = localize_images(md, None, images_dir)
        assert len(fake_download) == 1
        assert first == second

    def test_failed_download_keeps_remote_link(self, tmp_path, monkeypatch):
        def boom(request, timeout=0):
            raise OSError("network down")

        monkeypatch.setattr(urllib.request, "urlopen", boom)

        images_dir = tmp_path / "images"
        original = "![x](https://example.com/missing.png)"
        md, count = localize_images(original, None, images_dir)

        assert count == 0
        assert md == original
        # A page whose images all fail leaves no stray empty images/ folder.
        assert not images_dir.exists()

    def test_data_uri_is_left_untouched(self, tmp_path, fake_download):
        images_dir = tmp_path / "images"
        original = "![](data:image/png;base64,AAAA)"
        md, count = localize_images(original, None, images_dir)

        assert count == 0
        assert md == original
        assert fake_download == []

    def test_unresolvable_relative_url_without_base_is_skipped(
        self, tmp_path, fake_download
    ):
        images_dir = tmp_path / "images"
        original = "![](photo.png)"
        md, count = localize_images(original, None, images_dir)

        assert count == 0
        assert md == original
        assert fake_download == []

    def test_same_url_maps_to_stable_name(self, tmp_path, fake_download):
        # Determinism: the local filename is a function of the URL, so two
        # separate runs against fresh folders produce the same name.
        md1, _ = localize_images("![](https://example.com/x.png)", None, tmp_path / "a")
        md2, _ = localize_images("![](https://example.com/x.png)", None, tmp_path / "b")
        assert md1 == md2


class TestStripImageLinks:
    def test_removes_image_syntax(self):
        from arciv.core.parse.images import strip_image_links

        assert strip_image_links("a ![alt](images/x.png) b") == "a  b"

    def test_leaves_text_without_images_unchanged(self):
        from arciv.core.parse.images import strip_image_links

        text = "plain text, no images here."
        assert strip_image_links(text) == text


class TestModuleConstants:
    def test_images_subdir_name(self):
        assert images.IMAGES_SUBDIR == "images"
