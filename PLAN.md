# MicroRAG Project Plan

Local semantic search over markdown files. Fully offline after a one-time model download. CPU-only.
Python.

This document is the source of truth for any coding agent working on this project. When this
document and an agent's own judgement conflict, this document wins. When something is not covered
here, ask before deciding.



## Locked technical decisions

These are decided. Do not revisit, "improve", or abstract over them.

- Vector store: ChromaDB via `PersistentClient`, cosine space (`{"hnsw:space": "cosine"}`). Named
  collections, one per indexed root (default collection `microrag`); each collection is pinned to
  the first root it was built from, recorded in `roots.json` inside the DB dir.
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
- Chunk IDs: `sha256(f"{relative_path}:{chunk_index}:{chunk_text}")` hex digest. Combined with the
  indexer's ID diff against the store, re-indexing only embeds chunks whose IDs are new — unchanged
  content costs no inference.
- Retrieval only in v1. No generation step. "RAG" without the G until the retrieval half is proven;
  local generation is a separate decision with its own constraints.

## Architecture

```
microrag/
    constants.py    # QUERY_PREFIX, model id, paths, chunk sizes, exit codes
    embedder.py     # OnnxEmbedder
    chunker.py      # markdown-aware chunking
    store.py        # thin Chroma wrapper
    collections.py  # collection name validation + per-collection root pinning
    indexer.py      # walk files -> chunk -> embed -> upsert
    cli.py          # argparse entrypoints: download, index, query, status
tests/
evals/              # retrieval-quality suite (dev tool, not shipped)
```

Module boundaries: `embedder` knows nothing about Chroma. `store` knows nothing about ONNX or
tokenizers. `chunker` is pure functions over strings. `collections` owns the roots marker and name
rules. `cli` is the only place these are wired together. If an import crosses these boundaries, it's
wrong. cli.py sits above the ~300-line signal (~445 lines after the multi-collection feature); owner
reviewed and approved the size on 2026-07-19 — recheck only if it grows further.

## Status


## Rules for coding agents
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
- Chunk size and overlap tuning — decide empirically; `evals/` provides the measurement (run it
  before and after a constants change).
- Whether asymmetric mode buys enough recall to justify a second model — measure with a small set of
  queries against the existing index.