# Follow-ups

Known limitations, deliberately not fixed yet (see PLAN.md scope rules):

- Markdown image syntax is dropped during chunking (chonkie's MarkdownChef extracts images
  separately); alt text is not indexed.
- Indexing two different root directories into the same store can collide: sources are stored as
  root-relative paths, so `a.md` under one root overwrites `a.md` under another. One store per
  notes collection is the assumption.
- `index --prune` only compares against the root being indexed; it cannot distinguish "file
  deleted" from "file lives under a different root" (same root cause as the collision above).

## Parking lot (deliberately not built yet)

- Chonkie's `CodeChunker`/`TableChunker` extras for structure-aware splitting of extracted code
  blocks and tables: the base install's character-based splitting is good enough until retrieval
  quality says otherwise.

LLM-free retrieval ideas (from a survey of RAG techniques; anything needing an LLM or a hosted
API is banned for this project and listed under Rejected):

- Document title in the breadcrumb: chunks before the first heading get an empty breadcrumb, and
  the file name is never part of it. Prepending the filename stem (or first H1) is the LLM-free
  version of "contextual chunk headers" and costs nothing at query time.
- Neighbor-chunk expansion at query time: fetch a hit's `(source, index ± 1)` chunks from Chroma
  and show them as surrounding context — the LLM-free version of the "context enrichment window".
  Needs only a metadata `get`, no schema change.
- BM25 + vector fusion retrieval: fully LLM-free, but needs either a new dependency
  (`rank-bm25`, whitelist approval required) or Chroma `$contains` (explicitly out of scope for
  v1). Revisit if exact-keyword queries measurably underperform.
- Chonkie `SemanticChunker`: embedding-driven chunk boundaries, runs offline with `OnnxEmbedder`
  (it is a `BaseEmbeddings`). The chunking algorithm is locked and indexing cost rises, so only
  with owner approval and evidence that retrieval quality demands it.

## Rejected

- `--color auto|always|never`: the CLI emits no colored output (PLAN.md forbids a colors
  library), so the flag would be a knob that does nothing.
- Filtering/paging built into `query`: stdout is clean data; `grep`, `head`, and `jq` (with
  `--json`) already compose.
- Chonkie recipes (`from_recipe`): fetches chunking rules from Hugging Face Hub at runtime,
  which violates the no-network-at-runtime constraint. Rules are constructed locally instead.
- Chonkie `ChromaHandshake` as a replacement for our `Store`: verified against the installed
  source, it conflicts with locked decisions on every axis. It attaches an embedding function to
  the collection and upserts documents *without* explicit embeddings; its `search()` embeds
  queries through the same function, so `QUERY_PREFIX` is never applied (leaf-ir needs the
  prefix on queries only). It generates its own batch-relative chunk IDs (breaking the sha256
  scheme, incremental reindex, and prune, which rely on `source` metadata). Collections it
  creates get neither cosine space nor `anonymized_telemetry=False`.
- Chonkie `EmbeddingsRefinery`: compatible in principle (`OnnxEmbedder` is a `BaseEmbeddings`,
  and `refine()` calls the prefix-free `embed_batch`, correct for documents), but it would only
  relocate the indexer's `embed_documents` call — and it cannot join the chunker's existing
  pipeline anyway, because the heading breadcrumb is prepended *after* chunking, so the refinery
  would embed breadcrumb-less text. The explicit embed call in the indexer stays.
- LLM/API-dependent enrichment from the RAG-techniques survey: HyDE/HyPE, question-generation
  augmentation, query rewriting/step-back/decomposition, contextual compression, LLM-generated
  chunk headers, and reranker-API segment extraction. All require an LLM or hosted API, both
  banned here.

## Resolved

- Stale chunks from edited files: re-indexing now deletes a source's chunks whose IDs are not in
  the new set; deleted files are handled by `index --prune`.
- `#` comments in fenced code blocks misread as headings: fixed by switching chunking to chonkie
  (MarkdownChef separates code from prose).
- Oversized single paragraphs never split: chonkie's RecursiveChunker splits them to size.
- cwd-relative data directories: everything now lives under `MICRORAG_HOME` (default
  `~/.microrag`).
- AGENTS.md placeholders and rules copied from another project: filled in / replaced.
- Shell tab completion: added via argcomplete.
- `microrag query -` (stdin): added.
