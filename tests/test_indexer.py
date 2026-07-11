"""Tests for stale-chunk cleanup and pruning in the indexer."""

from pathlib import Path

import numpy as np

from microrag.indexer import index_directory


class _FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 4), dtype=np.float32)


class _MemoryStore:
    """Minimal in-memory stand-in for Store: tracks id -> source."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        for chunk_id, meta in zip(ids, metadatas, strict=True):
            self.data[chunk_id] = meta["source"]

    def ids_for_source(self, source: str) -> list[str]:
        return [i for i, s in self.data.items() if s == source]

    def sources(self) -> set[str]:
        return set(self.data.values())

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.data.pop(chunk_id, None)


def test_reindex_unchanged_file_is_a_noop(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# T\n\nstable content\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)
    before = dict(store.data)
    index_directory(tmp_path, _FakeEmbedder(), store)
    assert store.data == before


def test_editing_a_file_removes_stale_chunks(tmp_path: Path) -> None:
    note = tmp_path / "a.md"
    note.write_text("# T\n\noriginal content\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)
    old_ids = set(store.data)

    note.write_text("# T\n\ncompletely different content\n", encoding="utf-8")
    index_directory(tmp_path, _FakeEmbedder(), store)
    assert not old_ids & set(store.data)
    assert store.data  # new chunks present


def test_emptied_file_removes_all_its_chunks(tmp_path: Path) -> None:
    note = tmp_path / "a.md"
    note.write_text("# T\n\nsome content\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nkeep me\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)

    note.write_text("", encoding="utf-8")
    index_directory(tmp_path, _FakeEmbedder(), store)
    assert store.sources() == {"b.md"}


def test_prune_removes_deleted_files_only_when_opted_in(tmp_path: Path) -> None:
    gone = tmp_path / "gone.md"
    gone.write_text("# G\n\nbye\n", encoding="utf-8")
    (tmp_path / "kept.md").write_text("# K\n\nhello\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)
    gone.unlink()

    _, _, pruned = index_directory(tmp_path, _FakeEmbedder(), store)
    assert pruned == 0
    assert "gone.md" in store.sources()  # default is non-destructive

    _, _, pruned = index_directory(tmp_path, _FakeEmbedder(), store, prune=True)
    assert pruned > 0
    assert store.sources() == {"kept.md"}


def test_prune_is_skipped_when_no_files_found(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# T\n\ncontent\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)

    empty = tmp_path / "empty"
    empty.mkdir()
    files, chunks, pruned = index_directory(empty, _FakeEmbedder(), store, prune=True)
    assert (files, chunks, pruned) == (0, 0, 0)
    assert store.sources() == {"a.md"}
