# PYTHON_ARGCOMPLETE_OK
"""Command-line entrypoints for MicroRAG."""

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import argcomplete

# httpx is huggingface_hub's own HTTP transport, imported only for its error type.
import httpx
from huggingface_hub import get_token, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError
from loguru import logger

from .collections import COLLECTION_NAME_RE, read_roots, source_path, write_root
from .constants import (
    DEFAULT_COLLECTION,
    DEFAULT_DB_DIR,
    EX_NOINPUT,
    EX_OK,
    EX_UNAVAILABLE,
    EX_USAGE,
    MODEL_DIR,
    MODEL_ID,
    ONNX_DATA_FILENAME,
    ONNX_FILENAME,
    TOKENIZER_FILENAME,
)
from .embedder import OnnxEmbedder
from .indexer import index_directory
from .store import Store


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
    """Index a directory of markdown files into a collection."""
    path = Path(args.path)
    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        return EX_NOINPUT

    collection = args.collection
    if not COLLECTION_NAME_RE.fullmatch(collection):
        logger.error(
            f"Invalid collection name {collection!r}: use 3-512 characters "
            "[a-zA-Z0-9._-], starting and ending with a letter or digit."
        )
        return EX_USAGE

    # Sources are stored root-relative, so mixing roots in one collection can
    # silently collide (and confuses pruning). Pin each collection to the
    # first root it was built from.
    root = str(path.resolve())
    recorded = read_roots(DEFAULT_DB_DIR).get(collection)
    if recorded is not None and recorded != root:
        logger.error(
            f"Collection {collection!r} was built from {recorded}; indexing {root} "
            "into it would mix roots and can collide on relative paths. Index the "
            "new root into its own collection (--collection NAME), or delete "
            f"{DEFAULT_DB_DIR.resolve()} to start over."
        )
        return EX_USAGE

    embedder = _load_embedder()
    if embedder is None:
        return EX_NOINPUT

    store = Store(DEFAULT_DB_DIR, collection)
    files, chunks, pruned = index_directory(
        path, embedder, store, prune=not args.no_prune
    )
    if files and recorded is None:
        write_root(DEFAULT_DB_DIR, collection, root)

    if args.json:
        emit_json(
            {
                "collection": collection,
                "files": files,
                "chunks": chunks,
                "pruned": pruned,
            }
        )
    else:
        logger.info(
            f"Indexed {files} file(s), {chunks} new chunk(s), pruned {pruned} "
            f"into collection {collection!r}"
        )
    return EX_OK


def _confidence(distance: float) -> float:
    """Convert a cosine distance into a 0-100 confidence percentage, clamped at 0."""
    return max(0.0, (1.0 - distance) * 100.0)


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

    if args.limit < 1:
        logger.error(f"-k/--limit must be at least 1, got {args.limit}.")
        return EX_USAGE

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            f"No index found at {DEFAULT_DB_DIR.resolve()}. Run: microrag index <path>"
        )
        return EX_NOINPUT

    names = Store.collection_names(DEFAULT_DB_DIR)
    if args.collection is not None:
        if args.collection not in names:
            known = ", ".join(names) or "none"
            logger.error(f"Unknown collection {args.collection!r} (known: {known}).")
            return EX_USAGE
        names = [args.collection]

    embedder = _load_embedder()
    if embedder is None:
        return EX_NOINPUT

    stores = {name: Store(DEFAULT_DB_DIR, name) for name in names}
    counts = {name: store.count() for name, store in stores.items()}
    if sum(counts.values()) == 0:
        logger.error("The index is empty. Run: microrag index <path>")
        return EX_NOINPUT

    query_embedding = embedder.embed_query(text)

    # Query every collection and merge by distance; the same model embeds
    # them all, so cosine distances are comparable across collections.
    results = []
    for name, store in stores.items():
        if counts[name] == 0:
            continue
        documents, metadatas, distances = store.query(query_embedding, args.limit)
        results.extend(
            (dist, doc, meta, name)
            for doc, meta, dist in zip(
                documents[0], metadatas[0], distances[0], strict=True
            )
        )
    results.sort(key=lambda result: result[0])
    results = results[: args.limit]

    roots = read_roots(DEFAULT_DB_DIR)
    if args.json:
        for dist, doc, meta, name in results:
            emit_json(
                {
                    "confidence": round(_confidence(dist), 2),
                    "collection": name,
                    "source": meta["source"],
                    "path": str(source_path(meta["source"], roots.get(name))),
                    "heading": meta["heading"],
                    "text": doc,
                }
            )
    elif args.verbose:
        for rank, (dist, doc, meta, name) in enumerate(results, start=1):
            if rank > 1:
                emit("")
            emit(f"[{rank}] confidence={_confidence(dist):.1f}%")
            emit(f"    collection={name}")
            emit(f"    source={meta['source']}")
            emit(f"    heading={meta['heading']}")
            emit("")
            for line in doc.splitlines():
                emit(f"  | {line}")
    else:
        # One full path per line, best match first: pipeable into xargs/cat.
        seen: set[Path] = set()
        for _dist, _doc, meta, name in results:
            path = source_path(meta["source"], roots.get(name))
            if path not in seen:
                seen.add(path)
                emit(str(path))

    return EX_OK


def _status_command(args: argparse.Namespace) -> int:
    """Show where data lives on disk and how much is indexed, per collection."""
    model_present = (MODEL_DIR / ONNX_FILENAME).exists() and (
        MODEL_DIR / TOKENIZER_FILENAME
    ).exists()

    roots = read_roots(DEFAULT_DB_DIR)
    collections = []
    if DEFAULT_DB_DIR.exists():
        for name in Store.collection_names(DEFAULT_DB_DIR):
            collections.append(
                {
                    "name": name,
                    "root": roots.get(name),
                    "chunks": Store(DEFAULT_DB_DIR, name).count(),
                }
            )

    info = {
        "model_dir": str(MODEL_DIR.resolve()),
        "model_present": model_present,
        "db_dir": str(DEFAULT_DB_DIR.resolve()),
        "collections": collections,
        "chunks": sum(c["chunks"] for c in collections),
    }
    if args.json:
        emit_json(info)
    else:
        for key, value in info.items():
            if key == "collections":
                for c in value:
                    root = c["root"] if c["root"] is not None else "-"
                    emit(f"collection\t{c['name']}\t{root}\t{c['chunks']}")
                continue
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
            f"Embedding model not found in {MODEL_DIR.resolve()}. Run: microrag download"
        )
        return None
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)


def _configure_logging(verbose: int, quiet: bool) -> None:
    """Send all diagnostics to stderr; --quiet wins over --verbose."""
    logger.remove()  # remove default stderr handler
    if quiet:
        level = "ERROR"
    elif verbose >= 1:
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
        help="Show debug logs (query: also print each result's full text).",
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
        "vector store. Re-indexing unchanged files is a no-op; chunks for "
        "deleted files are pruned unless --no-prune is given. Each collection "
        "is pinned to one root directory — use --collection to index a second "
        "source.",
    )
    index_parser.add_argument("path", help="Directory to index")
    index_parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help=f"Collection to index into (default: {DEFAULT_COLLECTION})",
    )
    index_parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Keep chunks whose source file no longer exists under PATH",
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
        "--collection",
        default=None,
        help="Search only this collection (default: all collections)",
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
