"""Tests for the OnnxEmbedder."""

import logging

import numpy as np
import pytest
from chonkie.embeddings import BaseEmbeddings

from arciv.search.constants import (
    EMBEDDING_DIM,
    MODEL_DIR,
    ONNX_FILENAME,
    TOKENIZER_FILENAME,
)
from arciv.search.embedder import OnnxEmbedder

MODEL_PATH = MODEL_DIR / ONNX_FILENAME
TOKENIZER_PATH = MODEL_DIR / TOKENIZER_FILENAME


def _model_available() -> bool:
    return MODEL_PATH.exists() and TOKENIZER_PATH.exists()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason=f"Model files not found at {MODEL_DIR}; run 'arciv search download' first.",
)


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a.flatten(), b.flatten()))


@pytest.fixture
def embedder() -> OnnxEmbedder:
    return OnnxEmbedder(model_path=MODEL_PATH, tokenizer_path=TOKENIZER_PATH)


def test_embed_documents_shape_and_norm(embedder: OnnxEmbedder) -> None:
    texts = ["a short sentence", "another one"]
    vectors = embedder.embed_documents(texts)
    assert vectors.shape == (2, EMBEDDING_DIM)
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embed_query_shape_and_norm(embedder: OnnxEmbedder) -> None:
    vector = embedder.embed_query("what is onnx runtime")
    assert vector.shape == (1, EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(vector), 1.0, atol=1e-5)


def test_query_prefix_changes_embedding(embedder: OnnxEmbedder) -> None:
    text = "vector search"
    query_vec = embedder.embed_query(text)
    doc_vec = embedder.embed_documents([text])
    assert not np.allclose(query_vec, doc_vec, atol=1e-6)


def test_semantic_similarity(embedder: OnnxEmbedder) -> None:
    cat = embedder.embed_query("cat")
    kitten = embedder.embed_query("kitten")
    carburetor = embedder.embed_query("carburetor")
    assert _similarity(cat, kitten) > _similarity(cat, carburetor)


def test_empty_documents(embedder: OnnxEmbedder) -> None:
    vectors = embedder.embed_documents([])
    assert vectors.shape == (0, EMBEDDING_DIM)


def test_chonkie_embed_interface(embedder: OnnxEmbedder) -> None:
    assert isinstance(embedder, BaseEmbeddings)
    assert embedder.dimension == EMBEDDING_DIM

    vector = embedder.embed("a short sentence")
    assert vector.shape == (EMBEDDING_DIM,)
    assert np.allclose(np.linalg.norm(vector), 1.0, atol=1e-5)

    vectors = embedder.embed_batch(["a short sentence", "another one"])
    assert len(vectors) == 2
    assert all(v.shape == (EMBEDDING_DIM,) for v in vectors)
    assert np.allclose(vectors[0], vector, atol=1e-5)


def test_chonkie_call_dispatch(embedder: OnnxEmbedder) -> None:
    single = embedder("a short sentence")
    assert single.shape == (EMBEDDING_DIM,)
    batch = embedder(["a short sentence", "another one"])
    assert len(batch) == 2


def test_chonkie_interface_matches_embed_documents(embedder: OnnxEmbedder) -> None:
    texts = ["vector search", "another sentence"]
    rows = embedder.embed_documents(texts)
    assert np.allclose(np.stack(embedder.embed_batch(texts)), rows, atol=1e-5)


def test_truncation_warning_logged(
    embedder: OnnxEmbedder, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    long_text = "word " * 1000
    embedder.embed_documents([long_text])
    assert any("truncated" in record.message for record in caplog.records)
