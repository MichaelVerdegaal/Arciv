"""The ``arciv search`` sub-app: local semantic search over markdown.

The engine lives in ``arciv/search``; this module wires it onto the main CLI
as a Typer sub-app. Its heavy dependencies (chromadb, onnxruntime, the
embedding model) sit behind the optional ``search`` extra, so the top-level
imports here stay light and the real work imports them inside the command
bodies. A plain ``arciv`` install therefore never imports chromadb, and even
with the extra installed ``arciv list`` pays none of that import cost.

Global options (-v/-q/--color/--json) are handled by the parent callback in
cli.py, so the commands read ``json_output()``/``verbosity()`` instead of
declaring their own flags. The output contract matches the rest of Arciv:
payload data on stdout via emit/emit_json, everything diagnostic on stderr
via loguru.
"""

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from loguru import logger

from arciv.search.constants import (
    DEFAULT_COLLECTION,
    DEFAULT_DB_DIR,
    MODEL_DIR,
    MODEL_ID,
    ONNX_DATA_FILENAME,
    ONNX_FILENAME,
    TOKENIZER_FILENAME,
)

from .output import (
    EXIT_NOINPUT,
    EXIT_UNAVAILABLE,
    EXIT_USAGE,
    emit,
    emit_json,
    json_output,
    verbosity,
)

if TYPE_CHECKING:
    from arciv.search.embedder import OnnxEmbedder


_INSTALL_HINT = 'Install the search extra with: uv tool install "arciv[search]"'


def search_extra_installed() -> bool:
    """Whether the optional search extra is importable.

    Uses ``find_spec`` rather than importing chromadb, so deciding that
    ``arciv search`` is only a stub costs nothing on a plain install.
    """
    return importlib.util.find_spec("chromadb") is not None


def register_search(parent: typer.Typer) -> None:
    """Mount ``search`` on the parent CLI: the real sub-app, or a stub.

    When the extra is missing the stub still appears in ``arciv --help`` and
    swallows any arguments (``arciv search query ...``) to print the install
    hint instead of a confusing unknown-command error.
    """
    if search_extra_installed():
        parent.add_typer(search_app, name="search")
        return

    def search_unavailable(
        _args: Annotated[
            list[str] | None,
            typer.Argument(help="(the search extra is not installed)"),
        ] = None,
    ) -> None:
        """Local semantic search over markdown (needs the 'search' extra)."""
        logger.error(f'The "search" command needs the search extra. {_INSTALL_HINT}')
        raise typer.Exit(EXIT_USAGE)

    parent.command(
        name="search",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )(search_unavailable)


search_app = typer.Typer(
    name="search",
    no_args_is_help=True,
    help=(
        "Local semantic search over your markdown. Results go to stdout; "
        "logs and progress go to stderr."
    ),
)


@search_app.command()
def download() -> None:
    """Download the embedding model (one-time; the only networked command)."""
    import httpx
    from huggingface_hub import get_token, hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError

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
            "Check your network connection and retry: arciv search download"
        )
        raise typer.Exit(EXIT_UNAVAILABLE) from None

    if json_output():
        emit_json({"model_dir": str(MODEL_DIR.resolve())})
    else:
        logger.info(f"Model files saved to {MODEL_DIR.resolve()}")


@search_app.command()
def index(
    path: Annotated[Path, typer.Argument(help="Directory to index")],
    collection: Annotated[
        str,
        typer.Option(
            "--collection",
            help=f"Collection to index into (default: {DEFAULT_COLLECTION})",
        ),
    ] = DEFAULT_COLLECTION,
    no_prune: Annotated[
        bool,
        typer.Option(
            "--no-prune",
            help="Keep chunks whose source file no longer exists under PATH",
        ),
    ] = False,
) -> None:
    """Index a directory of markdown files into a collection."""
    from arciv.search.collections import COLLECTION_NAME_RE, read_roots, write_root
    from arciv.search.indexer import index_directory
    from arciv.search.store import Store

    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        raise typer.Exit(EXIT_NOINPUT)

    if not COLLECTION_NAME_RE.fullmatch(collection):
        logger.error(
            f"Invalid collection name {collection!r}: use 3-512 characters "
            "[a-zA-Z0-9._-], starting and ending with a letter or digit."
        )
        raise typer.Exit(EXIT_USAGE)

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
        raise typer.Exit(EXIT_USAGE)

    embedder = _load_embedder()
    if embedder is None:
        raise typer.Exit(EXIT_NOINPUT)

    store = Store(DEFAULT_DB_DIR, collection)
    files, chunks, pruned = index_directory(path, embedder, store, prune=not no_prune)
    if files and recorded is None:
        write_root(DEFAULT_DB_DIR, collection, root)

    if json_output():
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


@search_app.command()
def refresh(
    collection: Annotated[
        str | None,
        typer.Option(
            "--collection", help="Refresh only this collection (default: all)"
        ),
    ] = None,
    no_prune: Annotated[
        bool,
        typer.Option(
            "--no-prune",
            help="Keep chunks whose source file no longer exists under the root",
        ),
    ] = False,
) -> None:
    """Re-index collections from their recorded roots, ingesting changed files.

    Each collection remembers the directory it was built from, so refresh
    re-walks that root and embeds only what changed - no path to retype.
    Only whole collections are refreshed; the incremental chunk diff means
    unchanged files cost nothing.
    """
    from arciv.search.collections import COLLECTION_NAME_RE, read_roots
    from arciv.search.indexer import index_directory
    from arciv.search.store import Store

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            f"No index found at {DEFAULT_DB_DIR.resolve()}. "
            "Run: arciv search index <path>"
        )
        raise typer.Exit(EXIT_NOINPUT)

    names = Store.collection_names(DEFAULT_DB_DIR)
    if collection is not None:
        if not COLLECTION_NAME_RE.fullmatch(collection):
            logger.error(
                f"Invalid collection name {collection!r}: use 3-512 characters "
                "[a-zA-Z0-9._-], starting and ending with a letter or digit."
            )
            raise typer.Exit(EXIT_USAGE)
        if collection not in names:
            known = ", ".join(names) or "none"
            logger.error(f"Unknown collection {collection!r} (known: {known}).")
            raise typer.Exit(EXIT_USAGE)
        names = [collection]

    if not names:
        logger.error("No collections to refresh. Run: arciv search index <path>")
        raise typer.Exit(EXIT_NOINPUT)

    # A collection can only be refreshed from a recorded root that still exists.
    # Skip the ones that can't be (never deleting their data), so one broken
    # root doesn't abort a refresh across the rest.
    roots = read_roots(DEFAULT_DB_DIR)
    targets: list[tuple[str, Path]] = []
    for name in names:
        root = roots.get(name)
        if root is None:
            logger.warning(
                f"Skipping {name!r}: no recorded root. Re-run "
                f"'arciv search index <path> --collection {name}' to record one."
            )
            continue
        root_path = Path(root)
        if not root_path.is_dir():
            logger.warning(f"Skipping {name!r}: recorded root {root} no longer exists.")
            continue
        targets.append((name, root_path))

    if not targets:
        logger.warning("Nothing to refresh.")
        raise typer.Exit()

    embedder = _load_embedder()
    if embedder is None:
        raise typer.Exit(EXIT_NOINPUT)

    for name, root_path in targets:
        store = Store(DEFAULT_DB_DIR, name)
        files, chunks, pruned = index_directory(
            root_path, embedder, store, prune=not no_prune
        )
        if json_output():
            emit_json(
                {
                    "collection": name,
                    "root": str(root_path),
                    "files": files,
                    "chunks": chunks,
                    "pruned": pruned,
                }
            )
        else:
            logger.info(
                f"Refreshed {name!r} from {root_path}: {files} file(s), "
                f"{chunks} new chunk(s), pruned {pruned}"
            )


@search_app.command()
def query(
    text: Annotated[str, typer.Argument(help='Query text ("-" reads it from stdin)')],
    limit: Annotated[
        int, typer.Option("-k", "--limit", help="Number of results (default: 5)")
    ] = 5,
    collection: Annotated[
        str | None,
        typer.Option("--collection", help="Search only this collection (default: all)"),
    ] = None,
    null: Annotated[
        bool,
        typer.Option(
            "-0",
            "--null",
            help="Separate plain-output paths with NUL instead of newline (xargs -0).",
        ),
    ] = False,
) -> None:
    """Query the indexed store, best match first (JSONL with --json).

    Plain output is one absolute path per line (deduplicated, best match
    first) so it pipes straight into ``arciv extract -f -``, ``cat``, or an
    editor. ``-v`` prints ranked results with their text, each located as
    ``path:line``; ``--json`` emits JSONL with every field.
    """
    from arciv.search.collections import read_roots, source_path
    from arciv.search.store import Store

    if text == "-":
        if sys.stdin.isatty():
            logger.error(
                'Query text "-" reads from stdin, but stdin is a terminal. '
                "Example: grep -h TODO notes.md | arciv search query -"
            )
            raise typer.Exit(EXIT_USAGE)
        text = sys.stdin.read().strip()
        if not text:
            logger.error("Empty query text on stdin.")
            raise typer.Exit(EXIT_USAGE)

    if limit < 1:
        logger.error(f"-k/--limit must be at least 1, got {limit}.")
        raise typer.Exit(EXIT_USAGE)

    if not DEFAULT_DB_DIR.exists():
        logger.error(
            f"No index found at {DEFAULT_DB_DIR.resolve()}. "
            "Run: arciv search index <path>"
        )
        raise typer.Exit(EXIT_NOINPUT)

    names = Store.collection_names(DEFAULT_DB_DIR)
    if collection is not None:
        if collection not in names:
            known = ", ".join(names) or "none"
            logger.error(f"Unknown collection {collection!r} (known: {known}).")
            raise typer.Exit(EXIT_USAGE)
        names = [collection]

    embedder = _load_embedder()
    if embedder is None:
        raise typer.Exit(EXIT_NOINPUT)

    stores = {name: Store(DEFAULT_DB_DIR, name) for name in names}
    counts = {name: store.count() for name, store in stores.items()}
    if sum(counts.values()) == 0:
        logger.error("The index is empty. Run: arciv search index <path>")
        raise typer.Exit(EXIT_NOINPUT)

    query_embedding = embedder.embed_query(text)

    # Query every collection and merge by distance; the same model embeds
    # them all, so cosine distances are comparable across collections.
    results: list[tuple[float, str, dict, str]] = []
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
    if json_output():
        for dist, doc, meta, name in results:
            emit_json(
                {
                    "confidence": round(_confidence(dist), 2),
                    "collection": name,
                    "source": meta["source"],
                    "path": str(source_path(meta["source"], roots.get(name))),
                    "line": meta.get("line"),
                    "heading": meta["heading"],
                    "text": doc,
                }
            )
    elif verbosity():
        for rank, (dist, doc, meta, name) in enumerate(results, start=1):
            if rank > 1:
                emit()
            emit(f"[{rank}] confidence={_confidence(dist):.1f}%")
            emit(f"    collection={name}")
            path = source_path(meta["source"], roots.get(name))
            emit(f"    path={_located(path, meta.get('line'))}")
            emit()
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
                emit(str(path), null=null)


@search_app.command()
def status() -> None:
    """Show where data lives on disk and how much is indexed, per collection."""
    from arciv.search.collections import read_roots
    from arciv.search.store import Store

    model_present = (MODEL_DIR / ONNX_FILENAME).exists() and (
        MODEL_DIR / TOKENIZER_FILENAME
    ).exists()

    roots = read_roots(DEFAULT_DB_DIR)
    collections: list[dict[str, Any]] = []
    if DEFAULT_DB_DIR.exists():
        for name in Store.collection_names(DEFAULT_DB_DIR):
            collections.append(
                {
                    "name": name,
                    "root": roots.get(name),
                    "chunks": Store(DEFAULT_DB_DIR, name).count(),
                }
            )

    info: dict[str, Any] = {
        "model_dir": str(MODEL_DIR.resolve()),
        "model_present": model_present,
        "db_dir": str(DEFAULT_DB_DIR.resolve()),
        "collections": collections,
        "collections_count": len(collections),
        "chunks": sum(c["chunks"] for c in collections),
    }
    if json_output():
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
        logger.warning("Model not downloaded yet. Run: arciv search download")


@search_app.command()
def collections() -> None:
    """List indexed collections: name, path, files indexed, chunks indexed."""
    from arciv.search.collections import read_roots
    from arciv.search.store import Store

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

    if json_output():
        for record in records:
            emit_json(record)
    else:
        for record in records:
            path = record["path"] if record["path"] is not None else "-"
            emit(f"{record['name']}\t{path}\t{record['files']}\t{record['chunks']}")
        if not records:
            logger.info("No collections indexed yet. Run: arciv search index <path>")


# --- Helpers -----------------------------------------------------------------


def _confidence(distance: float) -> float:
    """Convert a cosine distance into a 0-100 confidence percentage, clamped at 0."""
    return max(0.0, (1.0 - distance) * 100.0)


def _located(path: Path, line: int | None) -> str:
    """Return a result's path, suffixed with ``:LINE`` when the index has one.

    The chunker records the line each chunk starts on, so the verbose view
    points at the passage instead of the file. Indexes written before that
    metadata existed carry no line; they show the plain path until the next
    ``arciv search refresh``.
    """
    return f"{path}:{line}" if line else str(path)


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


def _load_embedder() -> "OnnxEmbedder | None":
    """Load the local ONNX embedder, or log the next step and return None."""
    from arciv.search.embedder import OnnxEmbedder

    model_path = MODEL_DIR / ONNX_FILENAME
    tokenizer_path = MODEL_DIR / TOKENIZER_FILENAME
    if not (model_path.exists() and tokenizer_path.exists()):
        logger.error(
            f"Embedding model not found in {MODEL_DIR.resolve()}. "
            "Run: arciv search download"
        )
        return None
    return OnnxEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)
