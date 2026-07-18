"""Walk markdown files, chunk, embed, and upsert into the store.

Chunk IDs are content-addressed (sha256 of path, index, and text), so a chunk
that already exists in the store needs no work at all: re-indexing embeds only
chunks whose IDs are new and deletes the ones that disappeared. Embedding runs
once over all new chunks from every file, so small files no longer produce
under-filled inference batches.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from chonkie import FileFetcher
from loguru import logger

from .chunker import chunk_markdown
from .embedder import OnnxEmbedder
from .store import Store

_FETCHER = FileFetcher()


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
    files = sorted(_FETCHER.fetch(dir=path, ext=[".md"])) if path.is_dir() else []
    if not files:
        # Never prune on an empty walk: a mistyped path must not wipe the index.
        logger.warning(f"No markdown (*.md) files found under {path}")
        return 0, 0, 0

    plans = []
    for file_path in files:
        try:
            plans.append(_plan_file(file_path, path, store))
        except (OSError, UnicodeDecodeError):
            logger.exception(f"Failed to index {file_path}")

    # One embedding pass over every new chunk from every file: batches stay
    # full regardless of file sizes, and unchanged files cost no inference.
    new_texts = [text for plan in plans for text in plan.new_texts]
    embeddings = embedder.embed_documents(new_texts)

    offset = 0
    for plan in plans:
        _apply_plan(plan, embeddings[offset : offset + len(plan.new_texts)], store)
        offset += len(plan.new_texts)

    pruned = 0
    if prune:
        present = {str(f.relative_to(path)) for f in files}
        for source in sorted(store.sources() - present):
            stale_ids = store.ids_for_source(source)
            store.delete(stale_ids)
            pruned += len(stale_ids)
            logger.info(f"Pruned {source}: {len(stale_ids)} chunks")
    return len(plans), len(new_texts), pruned


def _plan_file(file_path: Path, root_path: Path, store: Store) -> _FilePlan:
    """Chunk one file and diff its chunk IDs against the store."""
    text = file_path.read_text(encoding="utf-8")
    relative = file_path.relative_to(root_path)
    existing_ids = set(store.ids_for_source(str(relative)))
    chunks = chunk_markdown(text, relative, file_path.stat().st_mtime)
    ids = [_chunk_id(relative, i, chunk["text"]) for i, chunk in enumerate(chunks)]

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


def _apply_plan(plan: _FilePlan, embeddings: np.ndarray, store: Store) -> None:
    """Write one file's new chunks and drop its stale ones."""
    if plan.new_ids:
        store.upsert(
            ids=plan.new_ids,
            embeddings=embeddings,
            documents=plan.new_texts,
            metadatas=plan.new_metadatas,
        )
    store.delete(plan.stale_ids)

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


def _chunk_id(relative: Path, index: int, text: str) -> str:
    """Return a stable SHA-256 ID for a chunk."""
    key = f"{relative}:{index}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
