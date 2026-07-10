"""Command-line entrypoints for MicroRAG."""

import argparse
import logging
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download
from huggingface_hub.errors import EntryNotFoundError

from .constants import (
    DEFAULT_DB_DIR,
    MODEL_DIR,
    MODEL_ID,
    ONNX_DATA_FILENAME,
    ONNX_FILENAME,
    TOKENIZER_FILENAME,
)
from .embedder import OnnxEmbedder
from .indexer import index_directory
from .store import Store

logger = logging.getLogger(__name__)


def _download_command(_args: argparse.Namespace) -> int:
    """Download the embedding model files from Hugging Face."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for filename in (TOKENIZER_FILENAME, ONNX_FILENAME):
        local_path = hf_hub_download(
            repo_id=MODEL_ID,
            filename=filename,
            local_dir=MODEL_DIR,
        )
        logger.info("Downloaded %s -> %s", filename, local_path)

    # Only large ONNX exports ship weights in a separate external data file.
    try:
        hf_hub_download(
            repo_id=MODEL_ID,
            filename=ONNX_DATA_FILENAME,
            local_dir=MODEL_DIR,
        )
        logger.info("Downloaded %s", ONNX_DATA_FILENAME)
    except EntryNotFoundError:
        logger.info("%s not present in repo; skipping", ONNX_DATA_FILENAME)

    print(f"Model files saved to {MODEL_DIR.resolve()}")
    return 0


def _index_command(args: argparse.Namespace) -> int:
    """Index a directory of markdown files."""
    path = Path(args.path)
    if not path.exists():
        logger.error("Path does not exist: %s", path)
        return 1

    embedder = _load_embedder()
    store = Store(DEFAULT_DB_DIR)
    index_directory(path, embedder, store)
    return 0


def _query_command(args: argparse.Namespace) -> int:
    """Run a query against the indexed store."""
    embedder = _load_embedder()
    store = Store(DEFAULT_DB_DIR)
    query_embedding = embedder.embed_query(args.text)
    documents, metadatas, distances = store.query(query_embedding, args.k)

    for doc, meta, dist in zip(documents[0], metadatas[0], distances[0], strict=True):
        print(f"distance={dist:.4f}")
        print(f"source={meta['source']}")
        print(f"heading={meta['heading']}")
        print(doc)
        print("---")

    return 0


def _load_embedder() -> OnnxEmbedder:
    """Load the local ONNX embedder."""
    model_path = MODEL_DIR / ONNX_FILENAME
    tokenizer_path = MODEL_DIR / TOKENIZER_FILENAME
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(prog="microrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download", help="Download the embedding model"
    )
    download_parser.set_defaults(func=_download_command)

    index_parser = subparsers.add_parser(
        "index", help="Index a directory of markdown files"
    )
    index_parser.add_argument("path", help="Directory to index")
    index_parser.set_defaults(func=_index_command)

    query_parser = subparsers.add_parser("query", help="Query the indexed store")
    query_parser.add_argument("text", help="Query text")
    query_parser.add_argument("-k", type=int, default=5, help="Number of results")
    query_parser.set_defaults(func=_query_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
