# Architecture

Local semantic search over markdown notes, fully offline after a one-time model download, CPU only.

## Pipeline

`index` walks a directory of `*.md` files, chunks them (chonkie-based, heading-aware), embeds each
chunk with a local ONNX model, and upserts the chunks into a persistent ChromaDB collection. `query`
embeds the query text (with a model-specific prefix) and returns the nearest chunks.

Everything lives under `MICRORAG_HOME` (default `~/.microrag`): the downloaded model in `model/`, the
Chroma DB in `db/`. See [README.md](README.md#conventions) for the user-facing behavior and
[PLAN.md](PLAN.md#locked-technical-decisions) for the decisions behind these choices.

## Modules

```
microrag/
    constants.py    # QUERY_PREFIX, model id, paths, chunk sizes, collection name, exit codes
    embedder.py     # OnnxEmbedder: loads the ONNX model, produces embeddings (CPU only)
    chunker.py      # heading-aware markdown chunking via chonkie
    store.py        # thin ChromaDB wrapper (upsert, query, ids_by_source)
    collections.py  # collection name validation + per-collection root pinning
    indexer.py      # walk files -> chunk -> embed -> upsert
    cli.py          # argparse entrypoints: download, index, query, status
tests/
evals/              # retrieval-quality suite (dev tool, not shipped)
```

### Module boundaries

These are strict. If an import crosses one of them, it's wrong.

- `embedder` knows nothing about Chroma.
- `store` knows nothing about ONNX or tokenizers.
- `chunker` is pure functions over strings.
- `collections` owns the roots marker and the name rules.
- `cli` is the only place these are wired together.

`cli.py` sits above the ~300-line signal (~445 lines after the multi-collection feature); the owner
reviewed and approved the size on 2026-07-19. Recheck only if it grows further.

## Chunk IDs and incremental indexing

Each chunk's ID is `sha256(f"{relative_path}:{chunk_index}:{chunk_text}")`. The indexer diffs these
IDs against the store, so:

- Already-indexed chunks are never re-embedded; unchanged files cost no inference.
- Edited files replace only their changed chunks.
- Chunks whose source file no longer exists under the indexed root are pruned (opt out with
  `--no-prune`).

Embedding runs over windows of new chunks pooled across files, so small files don't produce
under-filled inference batches and memory stays bounded regardless of corpus size.

## Collections

Each indexed root gets its own Chroma collection (default `microrag`). A collection is pinned to the
first root it was built from, recorded in `roots.json` inside the DB directory; indexing a different
root into it is refused. `query` merges results across all collections by cosine distance, and
`query --collection NAME` narrows the search.

## Key libraries

- `chromadb`: persistent vector store, one cosine collection per root, telemetry disabled.
- `onnxruntime` + `tokenizers`: CPU inference for the `MongoDB/mdbr-leaf-ir` embedding model.
- `chonkie`: markdown parsing (code fences/tables/images separated from prose), size-based chunking
  via a `Pipeline` (recursive chunker + overlap refinery), `FileFetcher` for the markdown file walk,
  and the `BaseEmbeddings` interface that `OnnxEmbedder` implements.
- `huggingface_hub`: one-time model download (the only networked code path).
- `numpy`: embedding arrays.
- `loguru`: logging to stderr.
- `argcomplete`: shell tab completion for the CLI.

Dependencies are limited to the whitelist in `pyproject.toml`. Adding anything else requires explicit
owner approval first (see [AGENTS.md](AGENTS.md#hard-constraints)).
