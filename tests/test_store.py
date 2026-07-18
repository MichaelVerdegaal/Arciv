"""Tests for the Chroma store wrapper."""

from pathlib import Path

import numpy as np

from microrag.store import Store


def _unit_vectors(n: int) -> np.ndarray:
    vectors = np.zeros((n, 4), dtype=np.float32)
    vectors[:, 0] = 1.0
    return vectors


def test_ids_by_source_groups_all_chunks(tmp_path: Path) -> None:
    store = Store(tmp_path / "db", "test-store")
    assert store.ids_by_source() == {}  # empty store, no error

    store.upsert(
        ids=["a0", "a1", "b0"],
        embeddings=_unit_vectors(3),
        documents=["x", "y", "z"],
        metadatas=[
            {"source": "a.md", "heading": "H", "index": 0, "mtime": 0.0},
            {"source": "a.md", "heading": "H", "index": 1, "mtime": 0.0},
            {"source": "b.md", "heading": "H", "index": 0, "mtime": 0.0},
        ],
    )
    grouped = store.ids_by_source()
    assert {source: sorted(ids) for source, ids in grouped.items()} == {
        "a.md": ["a0", "a1"],
        "b.md": ["b0"],
    }
