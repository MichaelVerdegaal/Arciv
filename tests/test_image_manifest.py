"""Tests for the shared image-manifest format (normalize + read/write)."""

import json

from arciv.core.image_manifest import (
    MANIFEST_NAME,
    load_manifest,
    normalize_url,
    write_manifest,
)


class TestNormalizeUrl:
    def test_lowercases_host_keeps_path_and_query(self):
        assert normalize_url("https://Example.COM/A/b.png?w=2") == (
            "https://example.com/A/b.png?w=2"
        )

    def test_drops_fragment(self):
        assert normalize_url("https://x.com/a.png#frag") == "https://x.com/a.png"


class TestManifestRoundTrip:
    def test_write_then_load(self, tmp_path):
        manifest = {"https://x.com/a.png": "aaaa.png"}
        write_manifest(tmp_path, manifest)
        assert (tmp_path / MANIFEST_NAME).exists()
        assert load_manifest(tmp_path) == manifest

    def test_empty_manifest_writes_nothing(self, tmp_path):
        write_manifest(tmp_path, {})
        assert not (tmp_path / MANIFEST_NAME).exists()

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_manifest(tmp_path) == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        (tmp_path / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        assert load_manifest(tmp_path) == {}

    def test_load_non_dict_returns_empty(self, tmp_path):
        (tmp_path / MANIFEST_NAME).write_text(json.dumps([1, 2]), encoding="utf-8")
        assert load_manifest(tmp_path) == {}
