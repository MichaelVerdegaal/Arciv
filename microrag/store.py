"""Thin ChromaDB wrapper."""

from pathlib import Path

import chromadb
import numpy as np

from .constants import DEFAULT_COLLECTION, VECTOR_SPACE


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
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas,
        )

    def count(self) -> int:
        """Return the number of chunks in the collection."""
        return self._collection.count()

    def ids_for_source(self, source: str) -> list[str]:
        """Return the IDs of all chunks whose metadata source equals source."""
        return self._collection.get(where={"source": source}, include=[])["ids"]

    def sources(self) -> set[str]:
        """Return the distinct source paths present in the collection."""
        result = self._collection.get(include=["metadatas"])
        return {meta["source"] for meta in result["metadatas"]}

    def delete(self, ids: list[str]) -> None:
        """Delete chunks by ID; a no-op for an empty list."""
        if ids:
            self._collection.delete(ids=ids)

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
            query_embeddings=query_embeddings.tolist(),
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        return result["documents"], result["metadatas"], result["distances"]
