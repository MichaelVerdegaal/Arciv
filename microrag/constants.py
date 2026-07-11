"""Project-wide constants."""

import os
from pathlib import Path

QUERY_PREFIX: str = "Represent this sentence for searching relevant passages: "

MODEL_ID: str = "MongoDB/mdbr-leaf-ir"

# All data lives under one stable home so commands work from any directory.
# Override with the MICRORAG_HOME environment variable.
MICRORAG_HOME: Path = Path(
    os.environ.get("MICRORAG_HOME", "") or Path.home() / ".microrag"
)
MODEL_DIR: Path = MICRORAG_HOME / "model"
TOKENIZER_FILENAME: str = "tokenizer.json"
ONNX_FILENAME: str = "onnx/model.onnx"
ONNX_DATA_FILENAME: str = "onnx/model.onnx_data"

DEFAULT_DB_DIR: Path = MICRORAG_HOME / "db"

CHUNK_TARGET_CHARS: int = 1200
CHUNK_OVERLAP_CHARS: int = 200
MAX_TOKENS: int = 512
BATCH_SIZE: int = 8
EMBEDDING_DIM: int = 768

COLLECTION_NAME: str = "microrag"
VECTOR_SPACE: dict[str, str] = {"hnsw:space": "cosine"}
