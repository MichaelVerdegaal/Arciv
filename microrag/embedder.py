"""ONNX embedder for the local leaf-ir model."""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .constants import (
    BATCH_SIZE,
    EMBEDDING_DIM,
    MAX_TOKENS,
    QUERY_PREFIX,
)

logger = logging.getLogger(__name__)

_SENTENCE_EMBEDDING: str = "sentence_embedding"
_TOKEN_LEVEL_OUTPUTS: set[str] = {"last_hidden_state", "token_embeddings"}


class OnnxEmbedder:
    """Compute embeddings using a local ONNX encoder model.

    Loads the tokenizer and ONNX session from explicit paths. Uses CPU only.
    Handles both sentence-level and token-level model outputs.
    """

    def __init__(self, model_path: Path, tokenizer_path: Path) -> None:
        """Initialize the embedder.

        Args:
            model_path: Path to the ONNX model file.
            tokenizer_path: Path to the tokenizer.json file.
        """
        if not model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer not found: {tokenizer_path}")

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        output_names = {out.name for out in self._session.get_outputs()}
        self._output_name = self._resolve_output_name(output_names)

    def _resolve_output_name(self, output_names: set[str]) -> str:
        """Pick the graph output to use for embeddings."""
        if _SENTENCE_EMBEDDING in output_names:
            return _SENTENCE_EMBEDDING
        for name in _TOKEN_LEVEL_OUTPUTS:
            if name in output_names:
                return name
        raise ValueError(
            f"Unsupported model outputs: {output_names}. "
            f"Expected {_SENTENCE_EMBEDDING!r} or one of {_TOKEN_LEVEL_OUTPUTS}."
        )

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed a list of documents without a query prefix.

        Args:
            texts: Document strings to embed.

        Returns:
            Array of shape (len(texts), EMBEDDING_DIM) with unit-norm vectors.
        """
        return self._embed(texts, is_query=False)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query with the query prefix.

        Args:
            text: Query string.

        Returns:
            Array of shape (1, EMBEDDING_DIM) with unit-norm vector.
        """
        return self._embed([QUERY_PREFIX + text], is_query=True)

    def _embed(self, texts: list[str], *, is_query: bool) -> np.ndarray:
        """Embed texts in batches sorted by token length."""
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        indexed = list(enumerate(texts))
        token_counts = [
            (i, len(self._tokenizer.encode(text).ids)) for i, text in indexed
        ]
        sorted_by_length = sorted(token_counts, key=lambda pair: pair[1])

        embeddings: list[np.ndarray] = [np.zeros((0, EMBEDDING_DIM), dtype=np.float32)]
        for batch_start in range(0, len(sorted_by_length), BATCH_SIZE):
            batch_items = sorted_by_length[batch_start : batch_start + BATCH_SIZE]
            batch_texts = [texts[i] for i, _ in batch_items]
            batch_embeddings = self._encode_batch(batch_texts, is_query=is_query)
            embeddings.append(batch_embeddings)

        concatenated = np.concatenate(embeddings, axis=0)
        unsorted = np.empty_like(concatenated)
        for new_index, (original_index, _) in enumerate(sorted_by_length):
            unsorted[original_index] = concatenated[new_index]

        self._validate(unsorted)
        return unsorted

    def _encode_batch(self, texts: list[str], *, is_query: bool) -> np.ndarray:
        """Encode a single batch and return normalized embeddings."""
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encoded], dtype=np.int64)

        for i, e in enumerate(encoded):
            if e.overflowing:
                source = "query" if is_query else "document"
                logger.warning(
                    "Input truncated at %d tokens for %s: %r",
                    MAX_TOKENS,
                    source,
                    texts[i][:80],
                )

        input_feed = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        }
        outputs = self._session.run(None, input_feed)
        output_map = {
            out.name: outputs[i] for i, out in enumerate(self._session.get_outputs())
        }
        vectors = output_map[self._output_name]

        if self._output_name == _SENTENCE_EMBEDDING:
            embeddings = vectors
        else:
            embeddings = self._mean_pool(vectors, attention_mask)

        return self._normalize(embeddings)

    def _mean_pool(
        self,
        token_embeddings: np.ndarray,
        attention_mask: np.ndarray,
    ) -> np.ndarray:
        """Mean-pool token embeddings over the real (non-padded) tokens."""
        mask = attention_mask.astype(np.float32)
        mask_expanded = np.expand_dims(mask, axis=-1)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(np.sum(mask, axis=1, keepdims=True), a_min=1e-9, a_max=None)
        return summed / counts

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        """L2-normalize vectors in place."""
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, a_min=1e-12, a_max=None)

    def _validate(self, vectors: np.ndarray) -> None:
        """Assert expected shape and unit norm."""
        if vectors.shape[1] != EMBEDDING_DIM:
            raise ValueError(
                f"Expected embedding dimension {EMBEDDING_DIM}, got {vectors.shape[1]}"
            )
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-5):
            bad = np.where(~np.isclose(norms, 1.0, atol=1e-5))[0]
            raise ValueError(
                f"Embeddings are not unit norm at indices {bad.tolist()}: norms={norms[bad].tolist()}"
            )
