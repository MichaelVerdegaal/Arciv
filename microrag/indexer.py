"""Walk markdown files, chunk, embed, and upsert into the store."""

import hashlib
from pathlib import Path

from chonkie import FileFetcher
from loguru import logger

from .chunker import chunk_markdown
from .embedder import OnnxEmbedder
from .store import Store

_FETCHER = FileFetcher()


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
        Tuple of (files indexed, chunks written, chunks pruned).
    """
    # FileFetcher only accepts directories; a plain-file path means no walk.
    files = sorted(_FETCHER.fetch(dir=path, ext=[".md"])) if path.is_dir() else []
    if not files:
        # Never prune on an empty walk: a mistyped path must not wipe the index.
        logger.warning(f"No markdown (*.md) files found under {path}")
        return 0, 0, 0

    indexed = 0
    total_chunks = 0
    for file_path in files:
        try:
            total_chunks += _index_file(file_path, path, embedder, store)
            indexed += 1
        except (OSError, UnicodeDecodeError):
            logger.exception(f"Failed to index {file_path}")

    pruned = 0
    if prune:
        present = {str(f.relative_to(path)) for f in files}
        for source in sorted(store.sources() - present):
            stale_ids = store.ids_for_source(source)
            store.delete(stale_ids)
            pruned += len(stale_ids)
            logger.info(f"Pruned {source}: {len(stale_ids)} chunks")
    return indexed, total_chunks, pruned


def _index_file(
    file_path: Path,
    root_path: Path,
    embedder: OnnxEmbedder,
    store: Store,
) -> int:
    """Index a single markdown file and return the number of chunks written."""
    text = file_path.read_text(encoding="utf-8")
    relative = file_path.relative_to(root_path)
    existing_ids = set(store.ids_for_source(str(relative)))
    chunks = chunk_markdown(text, relative, file_path.stat().st_mtime)

    texts = [chunk["text"] for chunk in chunks]
    ids = [_chunk_id(relative, i, text) for i, text in enumerate(texts)]
    if chunks:
        embeddings = embedder.embed_documents(texts)
        metadatas = [chunk["metadata"] for chunk in chunks]
        store.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )

    stale_ids = existing_ids - set(ids)
    store.delete(sorted(stale_ids))
    if stale_ids:
        logger.info(
            f"{relative}: {len(chunks)} chunks ({len(stale_ids)} stale removed)"
        )
    else:
        logger.info(f"{relative}: {len(chunks)} chunks")
    return len(chunks)


def _chunk_id(relative: Path, index: int, text: str) -> str:
    """Return a stable SHA-256 ID for a chunk."""
    key = f"{relative}:{index}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
