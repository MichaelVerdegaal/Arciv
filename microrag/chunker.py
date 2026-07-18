"""Markdown-aware chunking built on chonkie.

Uses MarkdownChef to separate fenced code, tables, and images from prose, then
splits prose on markdown headings. Each heading section is independently packed
to size by a chonkie Pipeline (RecursiveChunker with the default paragraph/
sentence rules, then verbatim prefix overlap between adjacent chunks).

Every chunk gets a bounded breadcrumb (filename, top heading, and the
section's own heading) so context survives the vector store.
"""

import re
from pathlib import Path

from chonkie import MarkdownChef, Pipeline
from chonkie.types import MarkdownImage

from .constants import CHUNK_OVERLAP_CHARS, CHUNK_TARGET_CHARS

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Cap on each breadcrumb segment, so verbose headings cannot eat into the
# embedder's token budget (the breadcrumb is prepended to every chunk).
_BREADCRUMB_SEGMENT_CHARS = 60

_CHEF = MarkdownChef()

# Sections reach the pipeline with their headings already stripped, so the
# chunker's default paragraph/sentence rules are the right ones. Both
# components count characters (chonkie's "character" tokenizer); the overlap
# runs in token mode, which copies the last CHUNK_OVERLAP_CHARS characters
# verbatim — recursive mode reconstructs the prefix from split pieces and can
# drop the whitespace between them. Module-level because Pipeline caches its
# component instances; run() itself holds no per-call state.
_PIPELINE = (
    Pipeline()
    .chunk_with("recursive", tokenizer="character", chunk_size=CHUNK_TARGET_CHARS)
    .refine_with(
        "overlap",
        tokenizer="character",
        context_size=CHUNK_OVERLAP_CHARS,
        method="prefix",
        mode="token",
        merge=True,
    )
)


def chunk_markdown(text: str, source: Path, mtime: float) -> list[dict]:
    """Split markdown text into heading-aware chunks.

    Fenced code blocks, tables, and image alt texts are chunked as their own
    sections under the heading in effect at their position; image content
    itself is dropped. Every breadcrumb starts with the filename stem, so
    chunks carry document-level context even before the first heading.

    Args:
        text: Raw markdown content.
        source: Relative path of the source file.
        mtime: File modification time as a Unix timestamp.

    Returns:
        List of chunk dicts with keys "text" and "metadata".
    """
    doc = _CHEF.parse(text)
    title = source.stem
    segments = sorted(
        [("prose", c.start_index, c.text) for c in doc.chunks]
        + [("verbatim", c.start_index, c.content) for c in doc.code]
        + [("verbatim", t.start_index, t.content) for t in doc.tables]
        + [("verbatim", i.start_index, i.alias) for i in doc.images if _has_alt(i)],
        key=lambda segment: segment[1],
    )

    chunks: list[dict] = []
    heading_stack: list[tuple[int, str]] = []
    for kind, _, segment_text in segments:
        if kind == "prose":
            sections = _split_on_headings(segment_text, heading_stack, title)
        else:
            sections = [(_breadcrumb(title, heading_stack), segment_text)]
        for breadcrumb, body in sections:
            chunks.extend(_pack_section(body, breadcrumb, source, mtime))

    for index, chunk in enumerate(chunks):
        chunk["metadata"]["index"] = index
    return chunks


def _breadcrumb(title: str, heading_stack: list[tuple[int, str]]) -> str:
    """Return a bounded breadcrumb: title, top heading, section heading.

    Only the shallowest and deepest headings in effect are kept — the
    intermediate levels add length faster than they add retrieval context —
    and every segment is trimmed to _BREADCRUMB_SEGMENT_CHARS, so deep
    nesting or verbose headings cannot overflow the chunk's token budget.
    The title (filename stem) leads so chunks carry document-level context
    even before the first heading; it is skipped when the top heading
    already matches it, to avoid "Setup > Setup".
    """
    parts = [title]
    if heading_stack:
        top = heading_stack[0][1]
        if top.casefold() == title.casefold():
            parts = []
        parts.append(top)
        if len(heading_stack) > 1:
            parts.append(heading_stack[-1][1])
    return " > ".join(part[:_BREADCRUMB_SEGMENT_CHARS] for part in parts)


def _has_alt(image: MarkdownImage) -> bool:
    """Return True when the image carries real alt text worth indexing.

    MarkdownChef falls back to the filename (or "base64_image") when the alt
    text is empty; those aliases are noise, not content.
    """
    alias = image.alias.strip()
    return bool(alias) and alias != "base64_image" and alias != Path(image.content).name


def _split_on_headings(
    segment_text: str,
    heading_stack: list[tuple[int, str]],
    title: str,
) -> list[tuple[str, str]]:
    """Split a prose segment into (breadcrumb, body) sections, updating the stack."""
    matches = list(HEADING_RE.finditer(segment_text))
    sections: list[tuple[str, str]] = []

    lead = segment_text[: matches[0].start()] if matches else segment_text
    if lead.strip():
        sections.append((_breadcrumb(title, heading_stack), lead))

    for i, match in enumerate(matches):
        _update_heading_stack(
            heading_stack, len(match.group(1)), match.group(2).strip()
        )
        end = matches[i + 1].start() if i + 1 < len(matches) else len(segment_text)
        body = segment_text[match.end() : end]
        if body.strip():
            sections.append((_breadcrumb(title, heading_stack), body))
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
    doc = _PIPELINE.run(texts=body.strip())

    section_chunks = []
    for piece in doc.chunks:
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
