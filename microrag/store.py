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
