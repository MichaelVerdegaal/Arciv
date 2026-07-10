"""Project-wide constants."""

from pathlib import Path

QUERY_PREFIX: str = "Represent this sentence for searching relevant passages: "

MODEL_ID: str = "MongoDB/mdbr-leaf-ir"
MODEL_DIR: Path = Path(".microrag")
TOKENIZER_FILENAME: str = "tokenizer.json"
ONNX_FILENAME: str = "onnx/model.onnx"
ONNX_DATA_FILENAME: str = "onnx/model.onnx_data"

DEFAULT_DB_DIR: Path = Path(".microrag-db")

CHUNK_TARGET_CHARS: int = 1200
CHUNK_OVERLAP_CHARS: int = 200
MAX_TOKENS: int = 512
BATCH_SIZE: int = 8
EMBEDDING_DIM: int = 768

COLLECTION_NAME: str = "microrag"
VECTOR_SPACE: dict[str, str] = {"hnsw:space": "cosine"}
