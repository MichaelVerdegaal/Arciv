"""Tests for stale-chunk cleanup and pruning in the indexer."""

from pathlib import Path

import numpy as np
import pytest

from microrag.indexer import index_directory


class _FakeEmbedder:
    def __init__(self) -> None:
        self.embedded_texts: list[str] = []
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.embedded_texts.extend(texts)
        self.calls += 1
        return np.zeros((len(texts), 4), dtype=np.float32)


class _MemoryStore:
    """Minimal in-memory stand-in for Store: tracks id -> source."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        for chunk_id, meta in zip(ids, metadatas, strict=True):
            self.data[chunk_id] = meta["source"]

    def ids_by_source(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for chunk_id, source in self.data.items():
            grouped.setdefault(source, []).append(chunk_id)
        return grouped

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


def test_prune_removes_deleted_files_by_default(tmp_path: Path) -> None:
    gone = tmp_path / "gone.md"
    gone.write_text("# G\n\nbye\n", encoding="utf-8")
    (tmp_path / "kept.md").write_text("# K\n\nhello\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)
    gone.unlink()

    _, _, pruned = index_directory(tmp_path, _FakeEmbedder(), store, prune=False)
    assert pruned == 0
    assert "gone.md" in store.sources()  # opt-out keeps deleted files

    _, _, pruned = index_directory(tmp_path, _FakeEmbedder(), store)
    assert pruned > 0
    assert store.sources() == {"kept.md"}


def test_unchanged_files_are_not_reembedded(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# T\n\nstable content\n", encoding="utf-8")
    store = _MemoryStore()
    embedder = _FakeEmbedder()

    _, chunks, _ = index_directory(tmp_path, embedder, store)
    assert chunks == len(embedder.embedded_texts) > 0

    embedder.embedded_texts.clear()
    _, chunks, _ = index_directory(tmp_path, embedder, store)
    assert chunks == 0
    assert embedder.embedded_texts == []  # no inference for unchanged files


def test_only_changed_chunks_are_reembedded(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n\nkeep me as is\n", encoding="utf-8")
    edited = tmp_path / "b.md"
    edited.write_text("# B\n\nfirst body\n\n# B2\n\nsecond body\n", encoding="utf-8")
    store = _MemoryStore()
    embedder = _FakeEmbedder()
    index_directory(tmp_path, embedder, store)

    edited.write_text("# B\n\nfirst body\n\n# B2\n\nedited body\n", encoding="utf-8")
    embedder.embedded_texts.clear()
    _, chunks, _ = index_directory(tmp_path, embedder, store)

    # Only the edited chunk of the edited file is embedded again.
    assert chunks == 1
    assert embedder.embedded_texts == ["b > B2\n\nedited body"]


def test_flush_window_does_not_change_what_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tiny flush window must write exactly what one big pass writes."""
    for i in range(5):
        (tmp_path / f"n{i}.md").write_text(f"# T{i}\n\nbody {i}\n", encoding="utf-8")

    unbounded = _MemoryStore()
    one_pass = index_directory(tmp_path, _FakeEmbedder(), unbounded)

    monkeypatch.setattr("microrag.indexer.FLUSH_CHUNKS", 2)
    windowed_store = _MemoryStore()
    windowed_embedder = _FakeEmbedder()
    windowed = index_directory(tmp_path, windowed_embedder, windowed_store)

    assert windowed == one_pass
    assert windowed_store.data == unbounded.data
    assert windowed_embedder.calls > 1  # the window actually flushed mid-run


def test_prune_is_skipped_when_no_files_found(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# T\n\ncontent\n", encoding="utf-8")
    store = _MemoryStore()
    index_directory(tmp_path, _FakeEmbedder(), store)

    empty = tmp_path / "empty"
    empty.mkdir()
    files, chunks, pruned = index_directory(empty, _FakeEmbedder(), store, prune=True)
    assert (files, chunks, pruned) == (0, 0, 0)
    assert store.sources() == {"a.md"}
