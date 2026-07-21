"""Command-line entrypoints for MicroRAG.

Built on Typer. The output contract is strict: only payload data goes to
stdout (through emit/emit_json), while logs, progress, warnings, and hints
go to stderr via loguru. Global flags (-v/-q/--json) work both before and
after the subcommand; each command reconciles the callback's values with
its own so `microrag status --json` and `microrag --json status` behave the
same.
"""

import json
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# httpx is huggingface_hub's own HTTP transport, imported only for its error type.
import httpx
import typer
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

app = typer.Typer(
    name="microrag",
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    # Plain Click help/errors, not Rich's bordered panels: deterministic across
    # terminals (Rich wraps and colorizes based on width/TTY detection) and
    # keeps help greppable, matching the CLI's plain, pipeable output contract.
    rich_markup_mode=None,
    help=(
        "Local semantic search over markdown files. Results go to stdout; "
        "logs and progress go to stderr."
    ),
)


# --- Output: the single choke point for everything that reaches stdout -------


def emit(line: str) -> None:
    """Write one newline-terminated line of payload data to stdout.

    Every stdout write goes through emit/emit_json/emit_record; diagnostics,
    progress, and hints belong on stderr via logging.
    """
    print(line)


def emit_json(obj: dict) -> None:
    """Write one JSON object as a single line to stdout."""
    print(json.dumps(obj, ensure_ascii=False))


def emit_record(line: str, *, null: bool) -> None:
    """Write one record, NUL-terminated with null=True else newline-terminated.

    NUL separators (`find -print0` style) survive paths that contain spaces
    or newlines, so `microrag query -0 ... | xargs -0` stays correct.
    """
    if null:
        sys.stdout.write(line + "\0")
    else:
        emit(line)


# --- Global options, shared across the callback and every command ------------


@dataclass
class GlobalOpts:
    """Reconciled global flags for the running command."""

    verbose: int = 0
    quiet: bool = False
    json: bool = False


def _opt_verbose() -> int:
    return typer.Option(
        0,
        "-v",
        "--verbose",
        count=True,
        help="Show debug logs (query: also print each result's full text).",
    )


def _opt_quiet() -> bool:
    return typer.Option(
        False, "-q", "--quiet", help="Only show errors (wins over --verbose)."
    )


def _opt_json() -> bool:
    return typer.Option(False, "--json", help="Emit machine-readable output on stdout.")


def _resolve(
    ctx: typer.Context, verbose: int, quiet: bool, json_output: bool
) -> GlobalOpts:
    """Merge a command's global flags with the callback's, then set logging.

    Global flags are declared on both the callback (so they parse *before*
    the subcommand) and each command (so they parse *after*). Verbose counts
    take the max and the boolean flags OR together, so a flag set in either
    position wins regardless of order.
    """
    base = ctx.obj if isinstance(ctx.obj, GlobalOpts) else GlobalOpts()
    opts = GlobalOpts(
        verbose=max(base.verbose, verbose),
        quiet=base.quiet or quiet,
        json=base.json or json_output,
    )
    _configure_logging(opts.verbose, opts.quiet)
    return opts


def _version_callback(value: bool) -> None:
    """Print the version and exit; eager so it works without a subcommand."""
    if value:
        emit(f"microrag {_version()}")
        raise typer.Exit(EX_OK)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """Local semantic search over markdown files."""
    ctx.obj = GlobalOpts(verbose=verbose, quiet=quiet, json=json_output)
    _configure_logging(verbose, quiet)
    if ctx.invoked_subcommand is None:
        # No subcommand is the obvious read-only action: show help, exit 0.
        emit(ctx.get_help())
        raise typer.Exit(EX_OK)


# --- Commands ----------------------------------------------------------------


@app.command()
def download(
    ctx: typer.Context,
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """Download the embedding model (one-time; the only networked command)."""
    opts = _resolve(ctx, verbose, quiet, json_output)

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
        raise typer.Exit(EX_UNAVAILABLE) from None

    if opts.json:
        emit_json({"model_dir": str(MODEL_DIR.resolve())})
    else:
        logger.info(f"Model files saved to {MODEL_DIR.resolve()}")


@app.command()
def index(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Directory to index"),
    collection: str = typer.Option(
        DEFAULT_COLLECTION,
        "--collection",
        help=f"Collection to index into (default: {DEFAULT_COLLECTION})",
    ),
    no_prune: bool = typer.Option(
        False,
        "--no-prune",
        help="Keep chunks whose source file no longer exists under PATH",
    ),
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """Index a directory of markdown files into a collection."""
    opts = _resolve(ctx, verbose, quiet, json_output)

    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        raise typer.Exit(EX_NOINPUT)

    if not COLLECTION_NAME_RE.fullmatch(collection):
        logger.error(
            f"Invalid collection name {collection!r}: use 3-512 characters "
            "[a-zA-Z0-9._-], starting and ending with a letter or digit."
        )
        raise typer.Exit(EX_USAGE)

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
        raise typer.Exit(EX_USAGE)

    embedder = _load_embedder()
    if embedder is None:
        raise typer.Exit(EX_NOINPUT)

    store = Store(DEFAULT_DB_DIR, collection)
    files, chunks, pruned = index_directory(path, embedder, store, prune=not no_prune)
    if files and recorded is None:
        write_root(DEFAULT_DB_DIR, collection, root)

    if opts.json:
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


@app.command()
def query(
    ctx: typer.Context,
    text: str = typer.Argument(..., help='Query text ("-" reads it from stdin)'),
    limit: int = typer.Option(
        5, "-k", "--limit", help="Number of results (default: 5)"
    ),
    collection: str | None = typer.Option(
        None, "--collection", help="Search only this collection (default: all)"
    ),
    null: bool = typer.Option(
        False,
        "-0",
        "--null",
        help="Separate plain-output paths with NUL instead of newline (xargs -0).",
    ),
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """Query the indexed store, best match first (JSONL with --json)."""
    opts = _resolve(ctx, verbose, quiet, json_output)

    if text == "-":
        if sys.stdin.isatty():
            logger.error(
                'Query text "-" reads from stdin, but stdin is a terminal. '
                "Example: grep -h TODO notes.md | microrag query -"
            )
            raise typer.Exit(EX_USAGE)
        text = sys.stdin.read().strip()
        if not text:
            logger.error("Empty query text on stdin.")
            raise typer.Exit(EX_USAGE)

    if limit < 1:
        logger.error(f"-k/--limit must be at least 1, got {limit}.")
        raise typer.Exit(EX_USAGE)

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            f"No index found at {DEFAULT_DB_DIR.resolve()}. Run: microrag index <path>"
        )
        raise typer.Exit(EX_NOINPUT)

    names = Store.collection_names(DEFAULT_DB_DIR)
    if collection is not None:
        if collection not in names:
            known = ", ".join(names) or "none"
            logger.error(f"Unknown collection {collection!r} (known: {known}).")
            raise typer.Exit(EX_USAGE)
        names = [collection]

    embedder = _load_embedder()
    if embedder is None:
        raise typer.Exit(EX_NOINPUT)

    stores = {name: Store(DEFAULT_DB_DIR, name) for name in names}
    counts = {name: store.count() for name, store in stores.items()}
    if sum(counts.values()) == 0:
        logger.error("The index is empty. Run: microrag index <path>")
        raise typer.Exit(EX_NOINPUT)

    query_embedding = embedder.embed_query(text)

    # Query every collection and merge by distance; the same model embeds
    # them all, so cosine distances are comparable across collections.
    results = []
    for name, store in stores.items():
        if counts[name] == 0:
            continue
        documents, metadatas, distances = store.query(query_embedding, limit)
        results.extend(
            (dist, doc, meta, name)
            for doc, meta, dist in zip(
                documents[0], metadatas[0], distances[0], strict=True
            )
        )
    results.sort(key=lambda result: result[0])
    results = results[:limit]

    roots = read_roots(DEFAULT_DB_DIR)
    if opts.json:
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
    elif opts.verbose:
        for rank, (dist, doc, meta, name) in enumerate(results, start=1):
            if rank > 1:
                emit("")
            emit(f"[{rank}] confidence={_confidence(dist):.1f}%")
            emit(f"    collection={name}")
            emit(f"    source={meta['source']}")
            emit(f"    heading={meta['heading']}")
            emit("")
            # Chunks are stored with their heading breadcrumb prepended to the
            # text; drop it from the body so the heading shows once, above.
            for line in _strip_breadcrumb(doc, meta["heading"]).splitlines():
                emit(f"  | {line}")
    else:
        # One full path per record, best match first: pipeable into xargs/cat.
        seen: set[Path] = set()
        for _dist, _doc, meta, name in results:
            path = source_path(meta["source"], roots.get(name))
            if path not in seen:
                seen.add(path)
                emit_record(str(path), null=null)


@app.command()
def status(
    ctx: typer.Context,
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """Show where data lives on disk and how much is indexed, per collection."""
    opts = _resolve(ctx, verbose, quiet, json_output)

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
        "collections_count": len(collections),
        "chunks": sum(c["chunks"] for c in collections),
    }
    if opts.json:
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


@app.command()
def collections(
    ctx: typer.Context,
    verbose: int = _opt_verbose(),
    quiet: bool = _opt_quiet(),
    json_output: bool = _opt_json(),
) -> None:
    """List indexed collections: name, path, files indexed, chunks indexed."""
    opts = _resolve(ctx, verbose, quiet, json_output)

    roots = read_roots(DEFAULT_DB_DIR)
    records = []
    if DEFAULT_DB_DIR.exists():
        for name in Store.collection_names(DEFAULT_DB_DIR):
            store = Store(DEFAULT_DB_DIR, name)
            records.append(
                {
                    "name": name,
                    "path": roots.get(name),
                    "files": store.file_count(),
                    "chunks": store.count(),
                }
            )

    if opts.json:
        for record in records:
            emit_json(record)
    else:
        for record in records:
            path = record["path"] if record["path"] is not None else "-"
            emit(f"{record['name']}\t{path}\t{record['files']}\t{record['chunks']}")
        if not records:
            logger.info("No collections indexed yet. Run: microrag index <path>")


# --- Helpers -----------------------------------------------------------------


def _confidence(distance: float) -> float:
    """Convert a cosine distance into a 0-100 confidence percentage, clamped at 0."""
    return max(0.0, (1.0 - distance) * 100.0)


def _strip_breadcrumb(doc: str, heading: str) -> str:
    r"""Remove the leading breadcrumb the chunker prepends to each chunk's text.

    The chunker stores every chunk as ``"{breadcrumb}\n\n{body}"`` and mirrors
    the breadcrumb into the ``heading`` metadata, so the verbose view would
    otherwise print it twice. Returns the body unchanged when no breadcrumb is
    present (empty heading, or text that does not start with it).
    """
    prefix = f"{heading}\n\n"
    if heading and doc.startswith(prefix):
        return doc[len(prefix) :]
    return doc


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


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code.

    Wraps the Typer app so both entry points (`microrag` and `python -m
    microrag`) and the tests share one path. Running with
    standalone_mode=False lets us return sysexits codes instead of letting
    Click sys.exit itself, and lets typer.Exit(code) surface as that code.
    """
    # Windows text-mode stdout translates every "\n" into "\r\n", which breaks
    # LF-expecting pipe consumers (Git Bash, xargs, arciv). Turn the
    # translation off once at the stream so all payload stays LF-only; a no-op
    # where "\n" is native. The guard skips replaced stdouts (test captures)
    # that lack reconfigure.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")

    try:
        # prog_name pins the name in help/usage output regardless of argv[0]
        # (mirrors argparse's prog="microrag"); standalone_mode=False makes
        # typer.Exit(code) surface as a return value instead of sys.exit.
        result = app(args=argv, prog_name="microrag", standalone_mode=False)
    except SystemExit as exc:
        # Raised by non-CLI modules (e.g. a corrupted roots marker exits with
        # EX_DATAERR); surface the code as our own exit code.
        return exc.code if isinstance(exc.code, int) else EX_OK
    except Exception as exc:
        # Framework parse/usage errors are click's ClickException — but Typer
        # vendors its own click, so match structurally (has show()/exit_code)
        # rather than by import. Real bugs lack these and re-raise.
        show = getattr(exc, "show", None)
        code = getattr(exc, "exit_code", None)
        if callable(show) and isinstance(code, int):
            show()  # one clean usage line to stderr
            return code
        raise
    return result if isinstance(result, int) else EX_OK


if __name__ == "__main__":
    sys.exit(main())
