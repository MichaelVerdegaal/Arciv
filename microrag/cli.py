# PYTHON_ARGCOMPLETE_OK
"""Command-line entrypoints for MicroRAG."""

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import argcomplete
from loguru import logger

# httpx is huggingface_hub's own HTTP transport, imported only for its error type.
import httpx
from huggingface_hub import get_token, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError

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

EX_OK = 0
EX_USAGE = 64
EX_NOINPUT = 66
EX_UNAVAILABLE = 69

_ROOT_MARKER = "root.txt"


def _read_root() -> str | None:
    """Return the root the index was built from, or None if not recorded."""
    marker = DEFAULT_DB_DIR / _ROOT_MARKER
    if not marker.exists():
        return None
    return marker.read_text(encoding="utf-8").strip() or None


def emit(line: str) -> None:
    """Write one line of payload data to stdout.

    Every stdout write goes through emit/emit_json; diagnostics, progress,
    and hints belong on stderr via logging.
    """
    print(line)


def emit_json(obj: dict) -> None:
    """Write one JSON object as a single line to stdout."""
    print(json.dumps(obj, ensure_ascii=False))


def _download_command(args: argparse.Namespace) -> int:
    """Download the embedding model files from Hugging Face."""
    if get_token() is None:
        logger.warning(
            "No Hugging Face token configured. Set the HF_TOKEN environment "
            "variable to avoid rate limiting and speed up downloads. "
            "Create a token (read scope) at https://huggingface.co/settings/tokens"
        )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    try:
        for filename in (TOKENIZER_FILENAME, ONNX_FILENAME):
            local_path = hf_hub_download(
                repo_id=MODEL_ID,
                filename=filename,
                local_dir=MODEL_DIR,
            )
            logger.info(f"Downloaded {filename} -> {local_path}")

        # Only large ONNX exports ship weights in a separate external data file.
        try:
            hf_hub_download(
                repo_id=MODEL_ID,
                filename=ONNX_DATA_FILENAME,
                local_dir=MODEL_DIR,
            )
            logger.info(f"Downloaded {ONNX_DATA_FILENAME}")
        except EntryNotFoundError:
            logger.info(f"{ONNX_DATA_FILENAME} not present in repo; skipping")
    except (HfHubHTTPError, httpx.HTTPError) as exc:
        logger.error(
            f"Download from Hugging Face failed: {exc}. "
            "Check your network connection and retry: microrag download"
        )
        return EX_UNAVAILABLE

    if args.json:
        emit_json({"model_dir": str(MODEL_DIR.resolve())})
    else:
        logger.info(f"Model files saved to {MODEL_DIR.resolve()}")
    return EX_OK


def _index_command(args: argparse.Namespace) -> int:
    """Index a directory of markdown files."""
    path = Path(args.path)
    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        return EX_NOINPUT

    # Sources are stored root-relative, so mixing roots in one store can
    # silently collide (and confuses --prune). Pin the store to its first root.
    root = str(path.resolve())
    recorded = _read_root()
    if recorded is not None and recorded != root:
        logger.error(
            f"This index was built from {recorded}; indexing {root} would mix roots and can "
            "collide on relative paths. Use a separate MICRORAG_HOME for a "
            f"second collection, or delete {DEFAULT_DB_DIR.resolve()} to rebuild from the new root.",
        )
        return EX_USAGE

    embedder = _load_embedder()
    if embedder is None:
        return EX_NOINPUT

    store = Store(DEFAULT_DB_DIR)
    files, chunks, pruned = index_directory(path, embedder, store, prune=args.prune)
    if files and recorded is None:
        (DEFAULT_DB_DIR / _ROOT_MARKER).write_text(f"{root}\n", encoding="utf-8")

    if args.json:
        emit_json({"files": files, "chunks": chunks, "pruned": pruned})
    else:
        logger.info(f"Indexed {files} file(s), {chunks} chunk(s), pruned {pruned}")
    return EX_OK


def _query_command(args: argparse.Namespace) -> int:
    """Run a query against the indexed store."""
    if args.text == "-":
        if sys.stdin.isatty():
            logger.error(
                'Query text "-" reads from stdin, but stdin is a terminal. '
                "Example: grep -h TODO notes.md | microrag query -"
            )
            return EX_USAGE
        text = sys.stdin.read().strip()
        if not text:
            logger.error("Empty query text on stdin.")
            return EX_USAGE
    else:
        text = args.text

    if args.context < 0:
        logger.error(f"--context must be zero or positive, got {args.context}.")
        return EX_USAGE

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            f"No index found at {DEFAULT_DB_DIR.resolve()}. Run: microrag index <path>"
        )
        return EX_NOINPUT

    embedder = _load_embedder()
    if embedder is None:
        return EX_NOINPUT

    store = Store(DEFAULT_DB_DIR)
    if store.count() == 0:
        logger.error("The index is empty. Run: microrag index <path>")
        return EX_NOINPUT

    query_embedding = embedder.embed_query(text)
    documents, metadatas, distances = store.query(query_embedding, args.limit)

    for doc, meta, dist in zip(documents[0], metadatas[0], distances[0], strict=True):
        neighbors = (
            store.neighbors(meta["source"], meta["index"], args.context)
            if args.context
            else []
        )
        if args.json:
            result = {
                "distance": dist,
                "source": meta["source"],
                "heading": meta["heading"],
                "text": doc,
            }
            if args.context:
                result["context"] = [
                    {
                        "offset": n_meta["index"] - meta["index"],
                        "heading": n_meta["heading"],
                        "text": n_doc,
                    }
                    for n_doc, n_meta in neighbors
                ]
            emit_json(result)
        else:
            emit(f"distance={dist:.4f}")
            emit(f"source={meta['source']}")
            emit(f"heading={meta['heading']}")
            emit(doc)
            for n_doc, n_meta in neighbors:
                emit(f"context={n_meta['index'] - meta['index']:+d}")
                emit(n_doc)
            emit("---")

    return EX_OK


def _status_command(args: argparse.Namespace) -> int:
    """Show where data lives on disk and how much is indexed."""
    model_present = (MODEL_DIR / ONNX_FILENAME).exists() and (
        MODEL_DIR / TOKENIZER_FILENAME
    ).exists()
    chunks = Store(DEFAULT_DB_DIR).count() if DEFAULT_DB_DIR.exists() else 0

    info = {
        "model_dir": str(MODEL_DIR.resolve()),
        "model_present": model_present,
        "db_dir": str(DEFAULT_DB_DIR.resolve()),
        "root": _read_root(),
        "chunks": chunks,
    }
    if args.json:
        emit_json(info)
    else:
        for key, value in info.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            else:
                rendered = "-" if value is None else str(value)
            emit(f"{key}\t{rendered}")

    if not model_present:
        logger.warning("Model not downloaded yet. Run: microrag download")
    return EX_OK


def _load_embedder() -> OnnxEmbedder | None:
    """Load the local ONNX embedder, or log the next step and return None."""
    model_path = MODEL_DIR / ONNX_FILENAME
    tokenizer_path = MODEL_DIR / TOKENIZER_FILENAME
    if not (model_path.exists() and tokenizer_path.exists()):
        logger.error(
            f"Embedding model not found in {MODEL_DIR.resolve()}. Run: microrag download"
        )
        return None
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)


def _configure_logging(verbose: int, quiet: bool) -> None:
    """Send all diagnostics to stderr; --quiet wins over --verbose."""
    logger.remove()  # remove default stderr handler
    if quiet:
        level = "ERROR"
    elif verbose >= 2:
        level = "DEBUG"
    elif verbose == 1:
        level = "DEBUG"
    else:
        level = "INFO"
    logger.add(sys.stderr, level=level, format="{level}: {message}")


def _version() -> str:
    """Return the installed package version."""
    try:
        return version("microrag")
    except PackageNotFoundError:
        return "unknown"


def _add_common_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Add global options to a parser.

    With suppress=True (subparsers), absent flags leave the root parser's
    values untouched, so options work both before and after the subcommand.
    """
    verbose_default = {"default": argparse.SUPPRESS} if suppress else {"default": 0}
    flag_default = {"default": argparse.SUPPRESS} if suppress else {"default": False}
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="Increase log detail; repeat for more (-v debug, -vv trace).",
        **verbose_default,
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show errors (wins over --verbose).",
        **flag_default,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable output on stdout.",
        **flag_default,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(
        prog="microrag",
        description="Local semantic search over markdown files. "
        "Results go to stdout; logs and progress go to stderr.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    _add_common_options(parser, suppress=False)
    subparsers = parser.add_subparsers(dest="command")

    download_parser = subparsers.add_parser(
        "download",
        help="Download the embedding model (one-time; the only networked command)",
        description="Download the embedding model files from Hugging Face into "
        f"{MODEL_DIR}/. This is the only command that touches the network. "
        "Set HF_TOKEN to avoid rate limiting and speed up downloads.",
    )
    download_parser.set_defaults(func=_download_command)

    index_parser = subparsers.add_parser(
        "index",
        help="Index a directory of markdown files",
        description="Chunk and embed every *.md file under PATH into the local "
        "vector store. Re-indexing unchanged files is a no-op.",
    )
    index_parser.add_argument("path", help="Directory to index")
    index_parser.add_argument(
        "--prune",
        action="store_true",
        help="Also delete chunks whose source file no longer exists under PATH "
        "(skipped when PATH contains no markdown files)",
    )
    index_parser.set_defaults(func=_index_command)

    query_parser = subparsers.add_parser(
        "query",
        help="Query the indexed store",
        description="Print the top matching chunks for TEXT, best match first. "
        "With --json, one JSON object per result (JSONL).",
    )
    query_parser.add_argument("text", help='Query text ("-" reads it from stdin)')
    query_parser.add_argument(
        "-k",
        "--limit",
        dest="limit",
        type=int,
        default=5,
        help="Number of results (default: 5)",
    )
    query_parser.add_argument(
        "-c",
        "--context",
        type=int,
        default=0,
        metavar="N",
        help="Also print up to N neighboring chunks from the same file on "
        "each side of every result (default: 0)",
    )
    query_parser.set_defaults(func=_query_command)

    status_parser = subparsers.add_parser(
        "status",
        help="Show model/index locations and chunk count",
        description="Show where the model and index live on disk, whether the "
        "model is downloaded, and how many chunks are indexed.",
    )
    status_parser.set_defaults(func=_status_command)

    for sub in (download_parser, index_parser, query_parser, status_parser):
        _add_common_options(sub, suppress=True)

    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.quiet)

    if args.command is None:
        parser.print_help()
        return EX_OK
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
