"""Thin ChromaDB wrapper."""

from pathlib import Path

import chromadb
import numpy as np

from .constants import COLLECTION_NAME, VECTOR_SPACE


class Store:
    """Persistent Chroma store with cosine similarity."""

    def __init__(self, db_dir: Path) -> None:
        """Open or create the persistent Chroma client and collection.

        Args:
            db_dir: Directory where Chroma persists its data.
        """
        self._client = chromadb.PersistentClient(
            path=str(db_dir),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata=VECTOR_SPACE,
        )

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

    def neighbors(
        self,
        source: str,
        index: int,
        n: int,
    ) -> list[tuple[str, dict]]:
        """Return (document, metadata) pairs adjacent to a chunk in its file.

        Args:
            source: Source path of the anchor chunk.
            index: File-wide index of the anchor chunk.
            n: Number of neighboring chunks to fetch on each side.

        Returns:
            Pairs for chunks with index in [index - n, index + n], excluding
            the anchor itself, sorted by index.
        """
        wanted = [i for i in range(index - n, index + n + 1) if i != index and i >= 0]
        if not wanted:
            return []
        result = self._collection.get(
            where={"$and": [{"source": source}, {"index": {"$in": wanted}}]},
            include=["documents", "metadatas"],
        )
        pairs = zip(result["documents"], result["metadatas"], strict=True)
        return sorted(pairs, key=lambda pair: pair[1]["index"])

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
