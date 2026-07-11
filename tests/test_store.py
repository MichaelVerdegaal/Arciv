"""Tests for the Chroma store wrapper."""

from pathlib import Path

import numpy as np

from microrag.store import Store


def _unit_vectors(n: int) -> np.ndarray:
    vectors = np.zeros((n, 4), dtype=np.float32)
    vectors[:, 0] = 1.0
    return vectors


def _seed(store: Store, source: str, texts: list[str]) -> None:
    store.upsert(
        ids=[f"{source}:{i}" for i in range(len(texts))],
        embeddings=_unit_vectors(len(texts)),
        documents=texts,
        metadatas=[
            {"source": source, "heading": "H", "index": i, "mtime": 0.0}
            for i in range(len(texts))
        ],
    )


def test_neighbors_returns_adjacent_chunks_in_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "db")
    _seed(store, "a.md", ["zero", "one", "two", "three"])

    pairs = store.neighbors("a.md", index=2, n=1)
    assert [doc for doc, _ in pairs] == ["one", "three"]
    assert [meta["index"] for _, meta in pairs] == [1, 3]


def test_neighbors_clip_at_file_boundaries(tmp_path: Path) -> None:
    store = Store(tmp_path / "db")
    _seed(store, "a.md", ["zero", "one"])

    assert [doc for doc, _ in store.neighbors("a.md", index=0, n=2)] == ["one"]
    assert store.neighbors("a.md", index=0, n=0) == []


def test_neighbors_never_cross_into_other_sources(tmp_path: Path) -> None:
    store = Store(tmp_path / "db")
    _seed(store, "a.md", ["a-zero", "a-one"])
    _seed(store, "b.md", ["b-zero", "b-one"])

    pairs = store.neighbors("a.md", index=1, n=1)
    assert [doc for doc, _ in pairs] == ["a-zero"]
