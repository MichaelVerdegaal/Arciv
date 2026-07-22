"""Constants for the search engine.

The data home (model files and vector index) is resolved by ``arciv.settings``
so search shares the archive's data directory; see ``SEARCH_HOME`` there.
"""

from pathlib import Path

from arciv.settings import SEARCH_HOME

QUERY_PREFIX: str = "Represent this sentence for searching relevant passages: "

MODEL_ID: str = "MongoDB/mdbr-leaf-ir"

MODEL_DIR: Path = SEARCH_HOME / "model"
TOKENIZER_FILENAME: str = "tokenizer.json"
ONNX_FILENAME: str = "onnx/model.onnx"
ONNX_DATA_FILENAME: str = "onnx/model.onnx_data"

DEFAULT_DB_DIR: Path = SEARCH_HOME / "db"

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
