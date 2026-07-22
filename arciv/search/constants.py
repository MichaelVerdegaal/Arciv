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

# The embedder counts real model tokens; the chunker counts characters
# (chonkie's default "character" tokenizer). Roughly 4 characters per token,
# so 1200-char chunks plus breadcrumb and overlap sit well inside the
# 512-token model limit.
MAX_TOKENS: int = 512
CHUNK_TARGET_CHARS: int = 1200
CHUNK_OVERLAP_CHARS: int = 200
BATCH_SIZE: int = 8
EMBEDDING_DIM: int = 768

# Each indexed root gets its own Chroma collection; this one is used when
# no --collection is given, so single-source setups never see the concept.
DEFAULT_COLLECTION: str = "microrag"
VECTOR_SPACE: dict[str, str] = {"hnsw:space": "cosine"}

# Exit codes, following sysexits.h.
EX_OK: int = 0
EX_USAGE: int = 64  # command line usage error
EX_DATAERR: int = 65  # input data was incorrect (e.g. a corrupted marker file)
EX_NOINPUT: int = 66  # an input file did not exist
EX_UNAVAILABLE: int = 69  # a required service is unavailable
