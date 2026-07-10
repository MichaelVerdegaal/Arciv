"""Markdown-aware chunking for notes."""

import re
from pathlib import Path

from .constants import CHUNK_OVERLAP_CHARS, CHUNK_TARGET_CHARS

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def chunk_markdown(text: str, source: Path, mtime: float) -> list[dict]:
    """Split markdown text into heading-aware chunks.

    Args:
        text: Raw markdown content.
        source: Relative path of the source file.
        mtime: File modification time as a Unix timestamp.

    Returns:
        List of chunk dicts with keys "text" and "metadata".
    """
    matches = list(HEADING_RE.finditer(text))
    preamble = text[: matches[0].start()] if matches else text
    chunks = _chunk_section(preamble, source, mtime, "")
    heading_stack: list[tuple[int, str]] = []

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end]

        _update_heading_stack(heading_stack, level, heading_text)
        breadcrumb = " > ".join(text for _, text in heading_stack)
        chunks.extend(_chunk_section(section_text, source, mtime, breadcrumb))

    for index, chunk in enumerate(chunks):
        chunk["metadata"]["index"] = index

    return chunks


def _update_heading_stack(
    stack: list[tuple[int, str]],
    level: int,
    heading_text: str,
) -> None:
    """Replace headings at the same or deeper level, then append the new one."""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, heading_text))


def _chunk_section(
    section_text: str,
    source: Path,
    mtime: float,
    breadcrumb: str,
) -> list[dict]:
    """Pack paragraphs within a section into overlapping chunks."""
    paragraphs = [p.strip() for p in section_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[dict] = []
    current_paras: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        para_len = len(paragraph)
        if current_paras and current_len + 2 + para_len > CHUNK_TARGET_CHARS:
            body = "\n\n".join(current_paras)
            chunks.append(_make_chunk(body, source, mtime, breadcrumb))

            overlap = _overlap_text(body)
            current_paras = [overlap] if overlap else []
            current_len = len(overlap)

        current_paras.append(paragraph)
        current_len += (2 if len(current_paras) > 1 else 0) + para_len

    if current_paras:
        body = "\n\n".join(current_paras)
        chunks.append(_make_chunk(body, source, mtime, breadcrumb))

    return chunks


def _overlap_text(body: str) -> str:
    """Return the last CHUNK_OVERLAP_CHARS of body, aligned to paragraph start."""
    if len(body) <= CHUNK_OVERLAP_CHARS:
        return body
    tail = body[-CHUNK_OVERLAP_CHARS:]
    para_break = tail.find("\n\n")
    if para_break != -1:
        return tail[para_break + 2 :]
    return tail


def _make_chunk(
    body: str,
    source: Path,
    mtime: float,
    breadcrumb: str,
) -> dict:
    """Build a chunk dict; the file-wide "index" is filled in by chunk_markdown."""
    text = f"{breadcrumb}\n\n{body}" if breadcrumb else body
    return {
        "text": text,
        "metadata": {
            "source": str(source),
            "heading": breadcrumb,
            "index": -1,
            "mtime": mtime,
        },
    }
