"""Markdown-aware chunking built on chonkie.

Uses MarkdownChef to separate fenced code, tables, and images from prose, then
splits prose on markdown headings. Each heading section is independently chunked
by a RecursiveChunker (heading-aware rules from the markdown recipe, then
paragraph/line/sentence fallbacks) with overlap refinement.

Every chunk gets a breadcrumb (e.g. "filename > Heading > Subheading") so
context survives the vector store.
"""

import re
from pathlib import Path

from chonkie import MarkdownChef, Pipeline
from chonkie.types import MarkdownImage, RecursiveLevel, RecursiveRules

from .constants import CHUNK_OVERLAP_TOKENS, MAX_TOKENS

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Heading delimiters from the standard markdown recipe, in order of priority.
# Level 0: split on headings first (include_delim='next' keeps the `#` marker
#   so the heading text is part of the next chunk for breadcrumb extraction).
# Level 1: paragraph breaks.
# Level 2: line breaks.
# Level 3: sentence endings.
# Level 4: token-level (no delimiters, pure size).
_RULES = RecursiveRules(levels=[
    RecursiveLevel(
        delimiters=["######", "#####", "####", "###", "##", "#"],
        include_delim="next",
    ),
    RecursiveLevel(delimiters=["\n\n", "\n\r"], include_delim="prev"),
    RecursiveLevel(delimiters=["\n", "\r"], include_delim="prev"),
    RecursiveLevel(delimiters=[". ", "! ", "? "], include_delim="prev"),
    RecursiveLevel(delimiters=None, include_delim="prev"),
])

_CHEF = MarkdownChef()


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
    """Join the document title and heading stack into a breadcrumb string.

    The title (filename stem) leads so chunks carry document-level context
    even before the first heading; it is skipped when the top-level heading
    already matches it, to avoid "Setup > Setup".
    """
    parts = [t for _, t in heading_stack]
    if not parts or parts[0].casefold() != title.casefold():
        parts.insert(0, title)
    return " > ".join(parts)


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


def _build_pipeline() -> Pipeline:
    """Build a pipeline that chunks with heading-aware rules then refines with overlap.

    Constructed per-call since Pipeline holds mutable state.
    """
    return (
        Pipeline()
        .chunk_with("recursive", rules=_RULES, chunk_size=MAX_TOKENS)
        .refine_with(
            "overlap",
            context_size=CHUNK_OVERLAP_TOKENS,
            method="prefix",
            mode="recursive",
            merge=True,
        )
    )


def _pack_section(
    body: str,
    breadcrumb: str,
    source: Path,
    mtime: float,
) -> list[dict]:
    """Chunk a section body to size using the heading-aware pipeline."""
    pipeline = _build_pipeline()
    packed = pipeline.run(texts=body.strip()).chunks

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
