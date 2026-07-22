"""Tests for markdown chunking."""

from pathlib import Path

from microrag.chunker import chunk_markdown

SOURCE = Path("notes/example.md")


def test_preamble_before_first_heading_is_kept() -> None:
    text = "Intro before any heading.\n\n# Title\n\nBody text."
    chunks = chunk_markdown(text, SOURCE)
    assert any("Intro before any heading." in chunk["text"] for chunk in chunks)


def test_headingless_file_is_chunked() -> None:
    chunks = chunk_markdown("Just one paragraph.", SOURCE)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "example\n\nJust one paragraph."
    assert chunks[0]["metadata"]["heading"] == "example"


def test_breadcrumb_tracks_heading_nesting() -> None:
    text = "# Top\n\nalpha\n\n## Nested\n\nbeta\n\n# Other\n\ngamma"
    chunks = chunk_markdown(text, SOURCE)
    breadcrumbs = [chunk["metadata"]["heading"] for chunk in chunks]
    assert breadcrumbs == ["example > Top", "example > Top > Nested", "example > Other"]
    assert chunks[1]["text"].startswith("example > Top > Nested\n\n")


def test_title_matching_top_heading_is_not_repeated() -> None:
    text = "# Setup\n\nbody under the title heading"
    chunks = chunk_markdown(text, Path("notes/setup.md"))
    assert chunks[0]["metadata"]["heading"] == "Setup"
    assert chunks[0]["text"].startswith("Setup\n\n")


def test_image_alt_text_is_indexed_as_its_own_chunk() -> None:
    text = (
        "# Diagrams\n\nprose around the image\n\n"
        "![architecture diagram of the indexer](img/arch.png)\n\n"
        "![](img/no-alt.png)\n\nmore prose"
    )
    chunks = chunk_markdown(text, SOURCE)
    alt_chunks = [
        c for c in chunks if "architecture diagram of the indexer" in c["text"]
    ]
    assert len(alt_chunks) == 1
    assert alt_chunks[0]["metadata"]["heading"] == "example > Diagrams"
    assert not any("no-alt" in chunk["text"] for chunk in chunks)


def test_chunk_indices_are_file_wide_and_sequential() -> None:
    text = "# A\n\none\n\n# B\n\ntwo\n\n# C\n\nthree"
    chunks = chunk_markdown(text, SOURCE)
    assert [chunk["metadata"]["index"] for chunk in chunks] == list(range(len(chunks)))
    assert len(chunks) == 3


def test_heading_inside_code_fence_is_not_a_heading() -> None:
    text = (
        "# Real\n\nprose before code\n\n"
        "```python\n# just a comment\nx = 1\n```\n\n"
        "after the code"
    )
    chunks = chunk_markdown(text, SOURCE)
    breadcrumbs = {chunk["metadata"]["heading"] for chunk in chunks}
    assert breadcrumbs == {"example > Real"}
    assert any("# just a comment" in chunk["text"] for chunk in chunks)
    assert any("after the code" in chunk["text"] for chunk in chunks)


def test_deep_heading_levels() -> None:
    """Verify that ###### headings are correctly recognised."""
    text = "# L1\n\na\n\n###### L6\n\nb"
    chunks = chunk_markdown(text, SOURCE)
    breadcrumbs = [chunk["metadata"]["heading"] for chunk in chunks]
    assert breadcrumbs == ["example > L1", "example > L1 > L6"]


def test_breadcrumb_skips_intermediate_heading_levels() -> None:
    """Only the top and the section's own heading are kept, bounding length."""
    text = "# Guide\n\na\n\n## Install\n\nb\n\n### Docker\n\nc\n\n#### Compose\n\nd"
    chunks = chunk_markdown(text, SOURCE)
    breadcrumbs = [chunk["metadata"]["heading"] for chunk in chunks]
    assert breadcrumbs == [
        "example > Guide",
        "example > Guide > Install",
        "example > Guide > Docker",
        "example > Guide > Compose",
    ]


def test_breadcrumb_trims_long_headings() -> None:
    long_heading = "An Extremely Verbose Heading " * 5  # 145 chars
    text = f"# {long_heading}\n\nbody"
    chunks = chunk_markdown(text, SOURCE)
    heading = chunks[0]["metadata"]["heading"]
    assert heading.startswith("example > An Extremely Verbose Heading")
    assert len(heading) <= len("example > ") + 60


def test_metadata_fields() -> None:
    chunks = chunk_markdown("# H\n\nbody", SOURCE)
    metadata = chunks[0]["metadata"]
    assert metadata["source"] == str(SOURCE)
    assert metadata["heading"] == "example > H"
    assert metadata["index"] == 0
