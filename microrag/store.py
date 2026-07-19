"""Thin ChromaDB wrapper."""

from pathlib import Path

import chromadb
import numpy as np

from .constants import DEFAULT_COLLECTION, VECTOR_SPACE

# Chroma rejects writes above its max batch size (5461 in chromadb 1.5.9,
# via get_max_batch_size()); slice with headroom so callers never need to
# care how many rows they hand over at once.
_MAX_BATCH = 5000


def _client(db_dir: Path) -> chromadb.api.ClientAPI:
    """Open the persistent Chroma client with telemetry disabled."""
    return chromadb.PersistentClient(
        path=str(db_dir),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )


class Store:
    """Persistent Chroma store with cosine similarity, one collection per root."""

    def __init__(self, db_dir: Path, collection: str = DEFAULT_COLLECTION) -> None:
        """Open or create the persistent Chroma client and collection.

        Args:
            db_dir: Directory where Chroma persists its data.
            collection: Name of the collection to open or create.
        """
        self._collection = _client(db_dir).get_or_create_collection(
            name=collection,
            metadata=VECTOR_SPACE,
        )

    @classmethod
    def collection_names(cls, db_dir: Path) -> list[str]:
        """Return the names of all collections in the store, sorted."""
        return sorted(c.name for c in _client(db_dir).list_collections())

    def upsert(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """Upsert chunks into the collection.

        Args:
            ids: Unique chunk IDs.
            embeddings: Array of shape (n, dim).
            documents: Chunk texts.
            metadatas: Chunk metadata dicts.
        """
        # Chroma accepts numpy arrays directly; tolist() only added copies.
        for start in range(0, len(ids), _MAX_BATCH):
            end = start + _MAX_BATCH
            self._collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

    def count(self) -> int:
        """Return the number of chunks in the collection."""
        return self._collection.count()

    def ids_by_source(self) -> dict[str, list[str]]:
        """Return every chunk ID in the collection, grouped by source path.

        One store round trip, so the indexer can diff a whole corpus against
        it instead of querying per file. Roughly 200 bytes per chunk in RAM.
        """
        result = self._collection.get(include=["metadatas"])
        grouped: dict[str, list[str]] = {}
        for chunk_id, meta in zip(
            result["ids"], result["metadatas"] or [], strict=True
        ):
            grouped.setdefault(meta["source"], []).append(chunk_id)
        return grouped

    def delete(self, ids: list[str]) -> None:
        """Delete chunks by ID; a no-op for an empty list."""
        for start in range(0, len(ids), _MAX_BATCH):
            self._collection.delete(ids=ids[start : start + _MAX_BATCH])

    def query(
        self,
        query_embeddings: np.ndarray,
        n_results: int,
    ) -> tuple[list[list[str]], list[list[dict]], list[list[float]]]:
        """Query the collection for the nearest neighbors.

        Args:
            query_embeddings: Array of shape (1, dim).
            n_results: Number of results to return.

        Returns:
            Tuple of (documents, metadatas, distances).
        """
        result = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        return result["documents"], result["metadatas"], result["distances"]
