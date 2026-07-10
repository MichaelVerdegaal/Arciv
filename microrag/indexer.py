"""Walk markdown files, chunk, embed, and upsert into the store."""

import hashlib
import logging
from pathlib import Path

from .chunker import chunk_markdown
from .embedder import OnnxEmbedder
from .store import Store

logger = logging.getLogger(__name__)


def index_directory(path: Path, embedder: OnnxEmbedder, store: Store) -> None:
    """Index all *.md files under path into the store.

    Args:
        path: Root directory to walk.
        embedder: Initialized embedder.
        store: Initialized store.
    """
    files = sorted(path.rglob("*.md"))
    if not files:
        logger.warning("No markdown files found under %s", path)
        return

    for file_path in files:
        try:
            _index_file(file_path, path, embedder, store)
        except (OSError, UnicodeDecodeError):
            logger.exception("Failed to index %s", file_path)


def _index_file(
    file_path: Path,
    root_path: Path,
    embedder: OnnxEmbedder,
    store: Store,
) -> None:
    """Index a single markdown file."""
    text = file_path.read_text(encoding="utf-8")
    relative = file_path.relative_to(root_path)
    chunks = chunk_markdown(text, relative, file_path.stat().st_mtime)
    if not chunks:
        print(f"{relative}: 0 chunks")
        return

    texts = [chunk["text"] for chunk in chunks]
    embeddings = embedder.embed_documents(texts)
    ids = [_chunk_id(relative, i, text) for i, text in enumerate(texts)]
    metadatas = [chunk["metadata"] for chunk in chunks]

    store.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    print(f"{relative}: {len(chunks)} chunks")


def _chunk_id(relative: Path, index: int, text: str) -> str:
    """Return a stable SHA-256 ID for a chunk."""
    key = f"{relative}:{index}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
