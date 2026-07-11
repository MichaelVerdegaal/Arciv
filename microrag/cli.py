# PYTHON_ARGCOMPLETE_OK
"""Command-line entrypoints for MicroRAG."""

import argparse
import json
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import argcomplete

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

logger = logging.getLogger(__name__)

EX_OK: int = 0
EX_USAGE: int = 64  # sysexits.h: command line usage error
EX_NOINPUT: int = 66  # sysexits.h: an input file did not exist
EX_UNAVAILABLE: int = 69  # sysexits.h: a required service is unavailable


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
    except (HfHubHTTPError, httpx.HTTPError) as exc:
        logger.error(
            "Download from Hugging Face failed: %s. "
            "Check your network connection and retry: microrag download",
            exc,
        )
        return EX_UNAVAILABLE

    if args.json:
        emit_json({"model_dir": str(MODEL_DIR.resolve())})
    else:
        logger.info("Model files saved to %s", MODEL_DIR.resolve())
    return EX_OK


def _index_command(args: argparse.Namespace) -> int:
    """Index a directory of markdown files."""
    path = Path(args.path)
    if not path.exists():
        logger.error("Path does not exist: %s", path)
        return EX_NOINPUT

    embedder = _load_embedder()
    if embedder is None:
        return EX_NOINPUT

    store = Store(DEFAULT_DB_DIR)
    files, chunks, pruned = index_directory(path, embedder, store, prune=args.prune)

    if args.json:
        emit_json({"files": files, "chunks": chunks, "pruned": pruned})
    else:
        logger.info("Indexed %d file(s), %d chunk(s), pruned %d", files, chunks, pruned)
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

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            "No index found at %s. Run: microrag index <path>",
            DEFAULT_DB_DIR.resolve(),
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
        if args.json:
            emit_json(
                {
                    "distance": dist,
                    "source": meta["source"],
                    "heading": meta["heading"],
                    "text": doc,
                }
            )
        else:
            emit(f"distance={dist:.4f}")
            emit(f"source={meta['source']}")
            emit(f"heading={meta['heading']}")
            emit(doc)
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
        "chunks": chunks,
    }
    if args.json:
        emit_json(info)
    else:
        for key, value in info.items():
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
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
            "Embedding model not found in %s. Run: microrag download",
            MODEL_DIR.resolve(),
        )
        return None
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)


def _configure_logging(verbose: int, quiet: bool) -> None:
    """Send all diagnostics to stderr; --quiet wins over --verbose."""
    if quiet:
        root_level = app_level = logging.ERROR
    elif verbose >= 2:
        root_level = app_level = logging.DEBUG
    elif verbose == 1:
        root_level, app_level = logging.INFO, logging.DEBUG
    else:
        # Keep third-party INFO chatter (e.g. per-request HTTP logs) out of
        # the default output while still showing microrag's own progress.
        root_level, app_level = logging.WARNING, logging.INFO
    logging.basicConfig(
        level=root_level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger("microrag").setLevel(app_level)


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
