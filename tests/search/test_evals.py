"""Tests for the retrieval evaluation suite.

The metric math and the harness run everywhere; the actual quality-floor
test needs the downloaded model, like the embedder tests.
"""

from pathlib import Path

import numpy as np
import pytest

from arciv.search.constants import MODEL_DIR, ONNX_FILENAME, TOKENIZER_FILENAME
from arciv.search.embedder import OnnxEmbedder
from arciv.search.store import Store
from evals.run import (
    CORPUS_DIR,
    QueryResult,
    aggregate,
    evaluate,
    load_queries,
)

MODEL_PATH = MODEL_DIR / ONNX_FILENAME
TOKENIZER_PATH = MODEL_DIR / TOKENIZER_FILENAME


class _HashEmbedder:
    """Deterministic bag-of-words stub: no semantics, just working plumbing."""

    _DIM = 32

    def _vectors(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self._DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                vectors[row, hash(token) % self._DIM] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, a_min=1e-12, a_max=None)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._vectors(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vectors([text])


def test_gold_queries_reference_existing_corpus_files() -> None:
    queries = load_queries()
    assert len(queries) >= 20
    assert len({entry["query"] for entry in queries}) == len(queries)
    corpus_files = {p.name for p in CORPUS_DIR.glob("*.md")}
    for entry in queries:
        expected = entry["source"]
        expected = [expected] if isinstance(expected, str) else expected
        for source in expected:
            assert source in corpus_files, f"{source} missing from corpus"
    # Every corpus file should be exercised by at least one query.
    covered = set()
    for entry in queries:
        expected = entry["source"]
        covered.update([expected] if isinstance(expected, str) else expected)
    assert covered == corpus_files


def test_aggregate_metrics_math() -> None:
    def result(rank: int | None) -> QueryResult:
        return QueryResult(query="q", expected=["a.md"], ranked_sources=[], rank=rank)

    metrics = aggregate([result(1), result(2), result(6), result(None)])
    assert metrics["queries"] == 4
    assert metrics["hit@1"] == 0.25
    assert metrics["hit@3"] == 0.5
    assert metrics["hit@5"] == 0.5
    assert metrics["mrr"] == round((1 + 1 / 2 + 1 / 6 + 0) / 4, 3)

    assert aggregate([]) == {
        "queries": 0,
        "hit@1": 0.0,
        "hit@3": 0.0,
        "hit@5": 0.0,
        "mrr": 0.0,
    }


def test_empty_corpus_is_a_clear_error(tmp_path: Path) -> None:
    empty_corpus = tmp_path / "corpus"
    empty_corpus.mkdir()
    store = Store(tmp_path / "db", "eval")
    with pytest.raises(ValueError, match="produced no chunks"):
        evaluate(empty_corpus, load_queries(), _HashEmbedder(), store)


def test_harness_runs_end_to_end_with_stub_embedder(tmp_path: Path) -> None:
    queries = load_queries()
    store = Store(tmp_path / "db", "eval")
    results = evaluate(CORPUS_DIR, queries, _HashEmbedder(), store)

    assert len(results) == len(queries)
    for result in results:
        assert result.ranked_sources, "every query should retrieve something"
        assert result.rank is None or result.rank >= 1
    aggregate(results)  # must not raise on real result shapes


@pytest.mark.skipif(
    not (MODEL_PATH.exists() and TOKENIZER_PATH.exists()),
    reason=f"Model files not found at {MODEL_DIR}; run 'arciv search download' first.",
)
def test_retrieval_quality_floor(tmp_path: Path) -> None:
    """Conservative floors: raise them once a real baseline is established."""
    embedder = OnnxEmbedder(model_path=MODEL_PATH, tokenizer_path=TOKENIZER_PATH)
    store = Store(tmp_path / "db", "eval")
    metrics = aggregate(evaluate(CORPUS_DIR, load_queries(), embedder, store))

    assert metrics["hit@5"] >= 0.75, metrics
    assert metrics["hit@1"] >= 0.5, metrics
    assert metrics["mrr"] >= 0.6, metrics
