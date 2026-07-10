"""Walk markdown files, chunk, embed, and upsert into the store."""

import hashlib
import logging
from pathlib import Path

from .chunker import chunk_markdown
from .embedder import OnnxEmbedder
from .store import Store

logger = logging.getLogger(__name__)


def index_directory(
    path: Path, embedder: OnnxEmbedder, store: Store
) -> tuple[int, int]:
    """Index all *.md files under path into the store.

    Args:
        path: Root directory to walk.
        embedder: Initialized embedder.
        store: Initialized store.

    Returns:
        Tuple of (files indexed, chunks written).
    """
    files = sorted(path.rglob("*.md"))
    if not files:
        logger.warning("No markdown (*.md) files found under %s", path)
        return 0, 0

    indexed = 0
    total_chunks = 0
    for file_path in files:
        try:
            total_chunks += _index_file(file_path, path, embedder, store)
            indexed += 1
        except (OSError, UnicodeDecodeError):
            logger.exception("Failed to index %s", file_path)
    return indexed, total_chunks


def _index_file(
    file_path: Path,
    root_path: Path,
    embedder: OnnxEmbedder,
    store: Store,
) -> int:
    """Index a single markdown file and return the number of chunks written."""
    text = file_path.read_text(encoding="utf-8")
    relative = file_path.relative_to(root_path)
    chunks = chunk_markdown(text, relative, file_path.stat().st_mtime)
    if not chunks:
        logger.info("%s: 0 chunks", relative)
        return 0

    texts = [chunk["text"] for chunk in chunks]
    embeddings = embedder.embed_documents(texts)
    ids = [_chunk_id(relative, i, text) for i, text in enumerate(texts)]
    metadatas = [chunk["metadata"] for chunk in chunks]

    store.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    logger.info("%s: %d chunks", relative, len(chunks))
    return len(chunks)


def _chunk_id(relative: Path, index: int, text: str) -> str:
    """Return a stable SHA-256 ID for a chunk."""
    key = f"{relative}:{index}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
