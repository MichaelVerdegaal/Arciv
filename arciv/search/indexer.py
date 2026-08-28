"""Walk markdown files, chunk, embed, and upsert into the store.

Chunk IDs are content-addressed (sha256 of path, index, start line, and
text), so a chunk that already exists in the store needs no work at all:
re-indexing embeds only chunks whose IDs are new and deletes the ones that
disappeared. Embedding runs over windows of FLUSH_CHUNKS new chunks pooled
across files, so small files no longer produce under-filled inference
batches and memory stays bounded no matter how large the corpus is.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from chonkie import FileFetcher
from loguru import logger

from .chunker import chunk_markdown
from .embedder import OnnxEmbedder
from .store import Store

_FETCHER = FileFetcher()

# Embed-and-write window, in chunks. Bounds memory to a constant regardless
# of corpus size while staying far above the inference batch size, so
# batches remain full. 512 chunks is roughly 2-3 MB of pending work.
FLUSH_CHUNKS = 512


@dataclass
class _FilePlan:
    """What one file needs: chunks to embed, and stored chunks to drop."""

    relative: Path
    new_ids: list[str]
    new_texts: list[str]
    new_metadatas: list[dict]
    stale_ids: list[str]
    total_chunks: int


def index_directory(
    path: Path,
    embedder: OnnxEmbedder,
    store: Store,
    *,
    prune: bool = True,
) -> tuple[int, int, int]:
    """Index all *.md files under path into the store.

    Args:
        path: Root directory to walk.
        embedder: Initialized embedder.
        store: Initialized store.
        prune: Delete chunks whose source file no longer exists under path
            (default; never happens when the walk finds no files at all).

    Returns:
        Tuple of (files indexed, new chunks embedded and written, chunks pruned).
    """
    # FileFetcher only accepts directories; a plain-file path means no walk.
    # fetch() is typed Path | list[Path]; with a dir it returns the list.
    files = (
        sorted(cast("list[Path]", _FETCHER.fetch(dir=path, ext=[".md"])))
        if path.is_dir()
        else []
    )
    if not files:
        # Never prune on an empty walk: a mistyped path must not wipe the index.
        logger.warning(f"No markdown (*.md) files found under {path}")
        return 0, 0, 0

    # One store round trip for the whole diff instead of one get per file.
    existing_by_source = store.ids_by_source()

    # Embedding and writes run over windows of new chunks pooled across
    # files: inference batches stay full regardless of file sizes, unchanged
    # files cost nothing, and pending work never exceeds the flush window.
    indexed = 0
    written = 0
    pending: list[_FilePlan] = []
    pending_chunks = 0
    for file_path in files:
        try:
            plan = _plan_file(file_path, path, existing_by_source)
        except (OSError, UnicodeDecodeError):
            logger.exception(f"Failed to index {file_path}")
            continue
        indexed += 1
        pending.append(plan)
        pending_chunks += len(plan.new_texts)
        if pending_chunks >= FLUSH_CHUNKS:
            written += _flush(pending, embedder, store)
            pending = []
            pending_chunks = 0
    written += _flush(pending, embedder, store)

    pruned = 0
    if prune:
        present = {str(f.relative_to(path)) for f in files}
        stale_sources = sorted(set(existing_by_source) - present)
        for source in stale_sources:
            pruned += len(existing_by_source[source])
            logger.info(f"Pruned {source}: {len(existing_by_source[source])} chunks")
        store.delete(
            [
                chunk_id
                for source in stale_sources
                for chunk_id in existing_by_source[source]
            ]
        )
    return indexed, written, pruned


def _flush(plans: list[_FilePlan], embedder: OnnxEmbedder, store: Store) -> int:
    """Embed the pending plans' new chunks and write the window in one upsert.

    Chroma pays a fixed transaction cost per call, so one upsert (and one
    delete) per window beats one per file by a wide margin.
    """
    new_texts = [text for plan in plans for text in plan.new_texts]
    embeddings = embedder.embed_documents(new_texts)

    if new_texts:
        store.upsert(
            ids=[chunk_id for plan in plans for chunk_id in plan.new_ids],
            embeddings=embeddings,
            documents=new_texts,
            metadatas=[meta for plan in plans for meta in plan.new_metadatas],
        )
    store.delete([chunk_id for plan in plans for chunk_id in plan.stale_ids])

    for plan in plans:
        _log_plan(plan)
    return len(new_texts)


def _plan_file(
    file_path: Path,
    root_path: Path,
    existing_by_source: dict[str, list[str]],
) -> _FilePlan:
    """Chunk one file and diff its chunk IDs against the prefetched store state."""
    text = file_path.read_text(encoding="utf-8")
    relative = file_path.relative_to(root_path)
    existing_ids = set(existing_by_source.get(str(relative), ()))
    chunks = chunk_markdown(text, relative)
    ids = [
        _chunk_id(relative, i, chunk["metadata"]["line"], chunk["text"])
        for i, chunk in enumerate(chunks)
    ]

    new = [
        (chunk_id, chunk)
        for chunk_id, chunk in zip(ids, chunks, strict=True)
        if chunk_id not in existing_ids
    ]
    return _FilePlan(
        relative=relative,
        new_ids=[chunk_id for chunk_id, _ in new],
        new_texts=[chunk["text"] for _, chunk in new],
        new_metadatas=[chunk["metadata"] for _, chunk in new],
        stale_ids=sorted(existing_ids - set(ids)),
        total_chunks=len(chunks),
    )


def _log_plan(plan: _FilePlan) -> None:
    """Log what one file contributed to the flushed window."""
    if not plan.new_ids and not plan.stale_ids:
        logger.debug(f"{plan.relative}: unchanged ({plan.total_chunks} chunks)")
    elif plan.stale_ids:
        logger.info(
            f"{plan.relative}: {plan.total_chunks} chunks "
            f"({len(plan.new_ids)} new, {len(plan.stale_ids)} stale removed)"
        )
    else:
        logger.info(
            f"{plan.relative}: {plan.total_chunks} chunks ({len(plan.new_ids)} new)"
        )


def _chunk_id(relative: Path, index: int, line: int, text: str) -> str:
    """Return a stable SHA-256 ID for a chunk.

    The start line is part of the key so that text which only moved (an
    insertion higher up the file) is re-embedded rather than kept with a
    stale line in its metadata.
    """
    key = f"{relative}:{index}:{line}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
