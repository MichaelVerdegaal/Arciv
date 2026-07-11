# MicroRAG Project Plan

Local semantic search over markdown files exported from Arciv. Fully offline after a one-time model
download. CPU-only. Python.

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
- Dependencies are limited to the whitelist below. Adding anything else requires explicit approval
  from the project owner first.

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
  `"Represent this sentence for searching relevant passages: "` Applied to queries only, never to
  documents.
- Chunk IDs: `sha256(f"{relative_path}:{chunk_index}:{chunk_text}")` hex digest. Combined with
  Chroma `upsert`, re-indexing unchanged files is a natural no-op.
- Retrieval only in v1. No generation step. "RAG" without the G until the retrieval half is proven;
  local generation is a separate decision with its own constraints.

## Dependency whitelist

Runtime: `chromadb`, `onnxruntime`, `tokenizers`, `huggingface_hub`, `numpy`, `chonkie` (base
install only, no extras), `argcomplete`. Dev: `pytest`, `ruff`. CLI uses stdlib `argparse`.
Markdown parsing and chunking use `chonkie`; its recipe system (`from_recipe`,
`recipe=`/`lang=` parameters) fetches from Hugging Face Hub at runtime and is therefore
forbidden — rules must be constructed locally.

## Architecture

```
microrag/
    __init__.py
    constants.py    # QUERY_PREFIX, model id, paths, chunk sizes, collection name
    embedder.py     # OnnxEmbedder
    chunker.py      # markdown-aware chunking
    store.py        # thin Chroma wrapper
    indexer.py      # walk files -> chunk -> embed -> upsert
    cli.py          # argparse entrypoints: download, index, query
tests/
```

Module boundaries: `embedder` knows nothing about Chroma. `store` knows nothing about ONNX or
tokenizers. `chunker` is pure functions over strings. `cli` is the only place these are wired
together. If an import crosses these boundaries, it's wrong.

### embedder.py

`OnnxEmbedder` loads the ONNX session and the `tokenizer.json` from the downloaded model directory,
both paths passed in via `pathlib.Path` (never hardcoded). It subclasses chonkie's `BaseEmbeddings`
(implementing `embed`, `embed_batch`, `dimension`, `get_tokenizer`), so it plugs into chonkie
components such as `SemanticChunker` and `EmbeddingsRefinery` and inherits `__call__`,
`similarity`, and the async variants.

- At load time, inspect the session's output names. If the graph outputs `sentence_embedding`, use
  it directly. If it outputs token-level states (`last_hidden_state` or similar), apply mean pooling
  over the attention mask, then L2-normalize. Assert the final shape is `(n, 768)` and vectors are
  unit-norm; raise a descriptive exception if not.
- `embed_documents(texts: list[str]) -> np.ndarray` — no prefix.
- `embed_query(text: str) -> np.ndarray` — prepends `QUERY_PREFIX`.
- Process documents in small batches (default 8) sorted by token length to limit padding waste. Do
  not build an adaptive batching system; this is a single-user tool.
- Truncate inputs to the model's max length and log a warning with the source when truncation
  occurs.

### chunker.py

Heading-aware markdown chunking built on chonkie (all components run offline):

- `MarkdownChef` separates fenced code blocks, tables, and images from prose, so `#` comments
  inside code are never mistaken for headings. Code blocks, tables, and image alt texts become
  their own chunks under the heading in effect at their position; image content itself is
  dropped, as are filename-fallback aliases for images without alt text.
- Prose is split into sections on headings (`#` through `####`) with a breadcrumb stack, then
  each section is packed by a chonkie `Pipeline`: `RecursiveChunker` (character tokenizer) to a
  target of ~1200 characters (oversized paragraphs are split further), then `OverlapRefinery`
  (prefix, merged) adds ~200 characters of overlap between adjacent chunks in the same section.
  The chef stays outside the pipeline because the breadcrumb logic runs between parsing and
  chunking. The numbers live in `constants.py` and are tunable; the approach is not.
- Prepend the heading breadcrumb to each chunk text (e.g. `"Arciv Notes > Setup > Docker"`) so
  chunks carry their own context. The breadcrumb starts with the filename stem (skipped when the
  top-level heading already matches it), so even chunks before the first heading carry
  document-level context.
- Return chunks with metadata: source relative path, heading path, chunk index, file mtime.

### store.py

Thin wrapper only: create/get the collection with cosine space and telemetry off, `upsert` with
ids/embeddings/documents/metadatas, `query` with query embeddings and `n_results` returning
documents, metadatas, and distances. No retries, no connection pooling, no interfaces. If a function
in this file exceeds ~15 lines, it's doing too much.

### indexer.py

Walk a directory for `*.md` files (chonkie's `FileFetcher`, recursive and symlink-safe), chunk,
embed, upsert. Log a per-file summary (chunks written)
to stderr and return the (files, chunks, pruned) counts. After upserting a file, chunks for that
source whose IDs are not in the new set are deleted, so edited files never leave stale chunks.
Deleted-file handling is opt-in via `index --prune` (removes chunks whose source no longer exists
under the indexed root; skipped entirely when the walk finds no files, so a mistyped path cannot
wipe the index).

### cli.py

Four subcommands:

- `microrag download` — fetch model files to a local cache dir via `huggingface_hub`. Warns with
  a hint when no `HF_TOKEN` is configured (unauthenticated downloads are rate-limited and slower).
- `microrag index <path> [--prune]` — index a directory; `--prune` also removes chunks for
  deleted files. The index is pinned to the first root it was built from (a `root` marker file
  inside the DB dir); indexing a different root is refused with exit 64, since root-relative
  sources would collide and confuse `--prune`.
- `microrag query "<text>" [-k N] [-c N]` — print top-k results as: distance, source path,
  heading breadcrumb, and the chunk text; `-c/--context N` also prints up to N neighboring
  chunks from the same file on each side of every result. `"-"` reads the query text from
  stdin. Plain text output, no TUI, no colors library.
- `microrag status` — read-only introspection: model dir and presence, DB dir, indexed root,
  chunk count.

CLI conventions (locked):

- stdout is data, stderr is everything else. All stdout writes go through `emit()`/`emit_json()`
  in cli.py; logs, progress, warnings, and hints go to stderr via logging. Default log level is
  INFO for microrag's own logger and WARNING for third-party loggers.
- Global flags `-v/-vv`, `-q` (wins over verbose), `--json`, `--version`; accepted before and
  after the subcommand.
- `--json`: `query` emits JSONL (one object per result); `status` and mutating-command summaries
  emit a single object.
- Exit codes: 0 success, 66 missing input (path/model/index), 2 argparse usage errors. Expected
  failures are one-line stderr errors that name the next command to run — never tracebacks.
- No-args invocation prints help and exits 0.
- These invariants are covered by `tests/test_cli.py`; keep it green when touching the CLI.

## Phases

Phase 0 — skeleton and embedder. Project layout, `pyproject.toml`, download command, working
`OnnxEmbedder` with tests: output shape and unit norm; prefix applied on queries only; sanity check
that similarity("cat", "kitten") > similarity("cat", "carburetor").

Phase 1 — chunker and indexer. Index the Arciv export end to end. Re-running index on unchanged
files produces no duplicate chunks.

Phase 2 — query CLI. End-to-end: question in, ranked chunks out. This is the v1 finish line.

Each phase must be working and reviewed before the next starts. Agents must not begin a later phase
early because it "was convenient".

## Explicitly out of scope for v1

Do not implement any of these, even partially, even behind a flag: asymmetric mode with the arctic
teacher model, MRL truncation, int8/quantized model variants, hybrid search with `$contains`, an
evaluation harness, file watching, a config file system, multilingual model support, a
generation/LLM step, any web or TUI interface. These are follow-ups, not stretch goals.

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
- No config system; `constants.py` is the whole configuration story, plus the single
  `MICRORAG_HOME` env var that relocates the data directory (default `~/.microrag`).
- A module growing past ~300 lines is a signal to stop and check with the owner, not to split it
  into a package.
- Stay within the phase's scope. Ideas outside it go in a `FOLLOWUPS.md` list, not in code.
- Remove dead code and unused imports before finishing a task.

Ask the owner first before: adding any dependency, changing anything in the "Locked technical
decisions" section, changing the chunking algorithm (tuning the constants is fine), or touching the
ID scheme.

## Open questions (intentionally unresolved)

- Chunk size and overlap tuning — decide empirically once real queries run against real data.
- Whether asymmetric mode buys enough recall to justify a second model — measure with a small set of
  hand-labeled queries before building it.
- Whether and how a generation step gets added (llama.cpp is the likely candidate, but it reopens
  the CPU-budget question).