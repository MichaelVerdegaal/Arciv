# MicroRAG Project Plan

Local semantic search over markdown files. Fully offline after a one-time model download. CPU-only.
Python.

This document is the source of truth for any coding agent working on this project. When this
document and an agent's own judgement conflict, this document wins. When something is not covered
here, ask before deciding.

## Hard constraints (never violate)

- No network calls at runtime. The only permitted network access is the one-time download of model
  files from Hugging Face, performed by an explicit `download` command.
- No embedding APIs, no LLM APIs, no telemetry. Chroma's anonymized telemetry must be disabled
  (`anonymized_telemetry=False` in client settings).
- No `torch`, no `sentence-transformers`, no CUDA/GPU dependencies. Inference runs on `onnxruntime`
  with `CPUExecutionProvider` only.
- Dependencies are limited to the whitelist in `pyproject.toml`. Adding anything else requires
  explicit approval from the project owner first.

## Locked technical decisions

These are decided. Do not revisit, "improve", or abstract over them.

- Vector store: ChromaDB via `PersistentClient`, one collection named `microrag`, cosine space
  (`{"hnsw:space": "cosine"}`).
- Embedding model: `MongoDB/mdbr-leaf-ir`, the fp32 ONNX export from the repo's `onnx/` folder.
  BERT-style, 23M parameters, 768-dim output, 512-token context.
- Embeddings are computed by our own code and passed to Chroma explicitly via the `embeddings=`
  parameter on `upsert` and `query_embeddings=` on `query`. Do NOT attach an `embedding_function` to
  the collection. Rationale: leaf-ir requires a prompt prefix on queries but not on documents, and
  Chroma applies a collection's embedding function identically to both sides. Explicit embeddings
  keep all model logic in one module.
- Query prefix (exact string, defined once as a constant):
  `"Represent this sentence for searching relevant passages: "`. Applied to queries only, never to
  documents.
- Chunk IDs: `sha256(f"{relative_path}:{chunk_index}:{chunk_text}")` hex digest. Combined with
  Chroma `upsert`, re-indexing unchanged files is a natural no-op.
- Retrieval only in v1. No generation step. "RAG" without the G until the retrieval half is proven;
  local generation is a separate decision with its own constraints.

## Architecture

```
microrag/
    constants.py    # QUERY_PREFIX, model id, paths, chunk sizes, collection name
    embedder.py     # OnnxEmbedder
    chunker.py      # markdown-aware chunking
    store.py        # thin Chroma wrapper
    indexer.py      # walk files -> chunk -> embed -> upsert
    cli.py          # argparse entrypoints: download, index, query, status
tests/
```

Module boundaries: `embedder` knows nothing about Chroma. `store` knows nothing about ONNX or
tokenizers. `chunker` is pure functions over strings. `cli` is the only place these are wired
together. If an import crosses these boundaries, it's wrong.

## Status

All v1 phases are implemented and working:

- Phase 0 — skeleton, `pyproject.toml`, download command, `OnnxEmbedder` with shape/norm/prefix
  tests.
- Phase 1 — chunking (heading-aware, breadcrumb, overlap), indexing with incremental reindex and
  prune.
- Phase 2 — query CLI with JSON output, stdin query, status introspection.

The project is a `uv` tool: installable via `uv tool install .` (or a git URL) and callable as
`microrag` from anywhere with no venv activation.

## Rules for coding agents

Code standards:

- Type hint all function parameters and return types; builtin generics (`list`, `dict`), not
  `typing.List`.
- Google-style docstrings on public functions; no docstrings or comments on trivial code.
- `pathlib` everywhere; no hardcoded paths, no `os.path`.
- Specific exceptions with context; no broad `try/except` that swallows errors. Add error handling
  only where failure can actually occur (file IO, model load, malformed markdown).
- Regex patterns as module-level constants with the `_RE` suffix.
- Relative imports within the package; anything imported in `__init__.py` goes in `__all__`.
- No lazy imports inside functions. No `*args`/`**kwargs` without a specific need.

Design discipline:

- No abstract base classes, no factories, no dependency injection, no `VectorStoreInterface` "in
  case we swap stores later". One store, one model, concrete code.
- No config system; `constants.py` is the whole configuration story, plus the single `MICRORAG_HOME`
  env var that relocates the data directory (default `~/.microrag`).
- A module growing past ~300 lines is a signal to stop and check with the owner, not to split it
  into a package.
- Stay within scope. Ideas outside it go in `FOLLOWUPS.md`, not in code.
- Remove dead code and unused imports before finishing a task.

Ask the owner first before: adding any dependency, changing anything in the "Locked technical
decisions" section, changing the chunking algorithm (tuning the constants is fine), or touching the
ID scheme.

## Open questions (intentionally unresolved)

- Chunk size and overlap tuning — decide empirically once real queries run against real data.
- Whether asymmetric mode buys enough recall to justify a second model — measure with a small set of
  queries against the existing index.