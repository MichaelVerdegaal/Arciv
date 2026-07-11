"""Markdown-aware chunking built on chonkie."""

import re
from pathlib import Path

from chonkie import MarkdownChef, RecursiveChunker
from chonkie.refinery import OverlapRefinery

from .constants import CHUNK_OVERLAP_CHARS, CHUNK_TARGET_CHARS

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

# All chonkie components run offline: MarkdownChef separates fenced code and
# tables from prose (so `# comments` in code are never mistaken for headings),
# RecursiveChunker packs text to size and splits oversized paragraphs, and
# OverlapRefinery reproduces the prefix overlap between adjacent chunks.
_CHEF = MarkdownChef()
_CHUNKER = RecursiveChunker(tokenizer="character", chunk_size=CHUNK_TARGET_CHARS)
_OVERLAP = OverlapRefinery(
    tokenizer="character",
    context_size=CHUNK_OVERLAP_CHARS,
    method="prefix",
    mode="recursive",  # align the overlap to logical boundaries, not mid-word
    merge=True,
)


def chunk_markdown(text: str, source: Path, mtime: float) -> list[dict]:
    """Split markdown text into heading-aware chunks.

    Fenced code blocks and tables are chunked as their own sections under the
    heading in effect at their position; markdown image syntax is dropped.

    Args:
        text: Raw markdown content.
        source: Relative path of the source file.
        mtime: File modification time as a Unix timestamp.

    Returns:
        List of chunk dicts with keys "text" and "metadata".
    """
    doc = _CHEF.parse(text)
    segments = sorted(
        [("prose", c.start_index, c.text) for c in doc.chunks]
        + [("verbatim", c.start_index, c.content) for c in doc.code]
        + [("verbatim", t.start_index, t.content) for t in doc.tables],
        key=lambda segment: segment[1],
    )

    chunks: list[dict] = []
    heading_stack: list[tuple[int, str]] = []
    for kind, _, segment_text in segments:
        if kind == "prose":
            sections = _split_on_headings(segment_text, heading_stack)
        else:
            sections = [(" > ".join(t for _, t in heading_stack), segment_text)]
        for breadcrumb, body in sections:
            chunks.extend(_pack_section(body, breadcrumb, source, mtime))

    for index, chunk in enumerate(chunks):
        chunk["metadata"]["index"] = index
    return chunks


def _split_on_headings(
    segment_text: str,
    heading_stack: list[tuple[int, str]],
) -> list[tuple[str, str]]:
    """Split a prose segment into (breadcrumb, body) sections, updating the stack."""
    matches = list(HEADING_RE.finditer(segment_text))
    sections: list[tuple[str, str]] = []

    lead = segment_text[: matches[0].start()] if matches else segment_text
    if lead.strip():
        sections.append((" > ".join(t for _, t in heading_stack), lead))

    for i, match in enumerate(matches):
        _update_heading_stack(
            heading_stack, len(match.group(1)), match.group(2).strip()
        )
        end = matches[i + 1].start() if i + 1 < len(matches) else len(segment_text)
        body = segment_text[match.end() : end]
        if body.strip():
            sections.append((" > ".join(t for _, t in heading_stack), body))
    return sections


def _update_heading_stack(
    stack: list[tuple[int, str]],
    level: int,
    heading_text: str,
) -> None:
    """Replace headings at the same or deeper level, then append the new one."""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, heading_text))


def _pack_section(
    body: str,
    breadcrumb: str,
    source: Path,
    mtime: float,
) -> list[dict]:
    """Chunk a section body to size, with prefix overlap between adjacent chunks."""
    packed = _CHUNKER(body.strip())
    if len(packed) > 1:
        packed = _OVERLAP(packed)

    section_chunks = []
    for piece in packed:
        piece_text = piece.text.strip()
        if not piece_text:
            continue
        chunk_text = f"{breadcrumb}\n\n{piece_text}" if breadcrumb else piece_text
        section_chunks.append(
            {
                "text": chunk_text,
                "metadata": {
                    "source": str(source),
                    "heading": breadcrumb,
                    "index": -1,
                    "mtime": mtime,
                },
            }
        )
    return section_chunks
