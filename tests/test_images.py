"""Tests for markdown image relinking against the fetch-time manifest."""

from arciv.core.parse.images import relink_images, strip_image_links


class TestRelinkImages:
    def test_rewrites_matched_absolute_url(self):
        manifest = {"https://example.com/cat.png": "deadbeef.png"}
        md, count = relink_images(
            "![A cat](https://example.com/cat.png)", None, manifest
        )
        assert count == 1
        assert md == "![A cat](images/deadbeef.png)"

    def test_resolves_relative_src_against_base(self):
        manifest = {"https://example.com/static/diagram.png": "abc123.png"}
        md, count = relink_images(
            "![](/static/diagram.png)", "https://example.com/blog/post", manifest
        )
        assert count == 1
        assert md == "![](images/abc123.png)"

    def test_query_stripped_fallback(self):
        # Page src has no query; the captured image was served with one.
        manifest = {"https://cdn.example.com/p.png?w=800": "f00d.png"}
        md, count = relink_images("![](https://cdn.example.com/p.png)", None, manifest)
        assert count == 1
        assert md == "![](images/f00d.png)"

    def test_unmatched_image_keeps_remote_link(self):
        original = "![](https://example.com/missing.png)"
        md, count = relink_images(original, None, {"https://other/x.png": "a.png"})
        assert count == 0
        assert md == original

    def test_empty_manifest_is_noop(self):
        original = "![](https://example.com/x.png)"
        md, count = relink_images(original, None, {})
        assert count == 0
        assert md == original

    def test_data_and_blob_uris_skipped(self):
        original = "![](data:image/png;base64,AAAA) ![](blob:https://x/abc)"
        md, count = relink_images(original, None, {"whatever": "a.png"})
        assert count == 0
        assert md == original

    def test_host_case_is_normalized(self):
        # Manifest key has a lowercase host; the src uses mixed case.
        manifest = {"https://example.com/x.png": "cab.png"}
        md, count = relink_images("![](https://Example.COM/x.png)", None, manifest)
        assert count == 1
        assert md == "![](images/cab.png)"


class TestStripImageLinks:
    def test_removes_image_syntax(self):
        assert strip_image_links("a ![alt](images/x.png) b") == "a  b"

    def test_leaves_text_without_images_unchanged(self):
        text = "plain text, no images here."
        assert strip_image_links(text) == text
