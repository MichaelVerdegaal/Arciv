"""ONNX embedder for the local leaf-ir model, as a chonkie embeddings handler."""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from chonkie.embeddings import BaseEmbeddings
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


class OnnxEmbedder(BaseEmbeddings):
    """Compute embeddings using a local ONNX encoder model.

    Loads the tokenizer and ONNX session from explicit paths. Uses CPU only.
    Handles both sentence-level and token-level model outputs.

    Subclasses chonkie's BaseEmbeddings, so instances also work anywhere
    chonkie accepts an embedding model (SemanticChunker, EmbeddingsRefinery)
    and inherit __call__, similarity, and the async variants. The chonkie
    interface (embed/embed_batch) embeds text as documents; use embed_query
    for search queries, which need the instruction prefix.
    """

    def __init__(self, model_path: Path, tokenizer_path: Path) -> None:
        """Initialize the embedder.

        Args:
            model_path: Path to the ONNX model file.
            tokenizer_path: Path to the tokenizer.json file.
        """
        super().__init__()
        if not model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer not found: {tokenizer_path}")
        self._model_path = model_path

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {inp.name for inp in self._session.get_inputs()}
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

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        return EMBEDDING_DIM

    def get_tokenizer(self) -> Tokenizer:
        """Return the underlying tokenizer."""
        return self._tokenizer

    def embed(self, text: str) -> np.ndarray:
        """Embed a single document string.

        Args:
            text: Document string to embed.

        Returns:
            Array of shape (EMBEDDING_DIM,) with a unit-norm vector.
        """
        return self._embed([text], is_query=False)[0]

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a list of document strings.

        Overrides the base one-at-a-time loop with real batched inference.

        Args:
            texts: Document strings to embed.

        Returns:
            List of arrays of shape (EMBEDDING_DIM,) with unit-norm vectors.
        """
        return list(self._embed(texts, is_query=False))

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
        """Embed texts in batches sorted by token length to limit padding waste."""
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        order = sorted(
            range(len(texts)),
            key=lambda i: len(self._tokenizer.encode(texts[i]).ids),
        )
        batches = [
            self._encode_batch(
                [texts[i] for i in order[start : start + BATCH_SIZE]],
                is_query=is_query,
            )
            for start in range(0, len(order), BATCH_SIZE)
        ]

        embeddings = np.empty((len(texts), EMBEDDING_DIM), dtype=np.float32)
        embeddings[order] = np.concatenate(batches, axis=0)
        self._validate(embeddings)
        return embeddings

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
        input_feed = {k: v for k, v in input_feed.items() if k in self._input_names}
        vectors = self._session.run([self._output_name], input_feed)[0]

        if self._output_name != _SENTENCE_EMBEDDING:
            vectors = self._mean_pool(vectors, attention_mask)

        return self._normalize(vectors)

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
        """Return L2-normalized copies of the row vectors."""
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

    def __repr__(self) -> str:
        """Representation of the OnnxEmbedder instance."""
        return f"OnnxEmbedder(model_path={self._model_path})"
