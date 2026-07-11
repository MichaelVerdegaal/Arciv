# Follow-ups

Known limitations, deliberately not fixed yet (see PLAN.md scope rules):

- None currently.

## Parking lot (deliberately not built yet)

- Chonkie's `CodeChunker`/`TableChunker` extras for structure-aware splitting of extracted code
  blocks and tables: the base install's character-based splitting is good enough until retrieval
  quality says otherwise.

LLM-free retrieval ideas (from a survey of RAG techniques; anything needing an LLM or a hosted
API is banned for this project and listed under Rejected). These two still need an explicit
owner go-ahead per PLAN.md, which is why a blanket "handle the followups" did not cover them:

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

- Image alt text not indexed: alt texts are now chunked as their own sections under the heading
  in effect at their position (filename-fallback aliases are skipped as noise).
- Root collision and `--prune` ambiguity: the index is now pinned to the first root it was built
  from (recorded in a `root` marker inside the DB dir); `index` refuses a different root with a
  hint to use a separate `MICRORAG_HOME` or delete the DB dir to rebuild.
- Chunks before the first heading carried no document context: every breadcrumb now starts with
  the filename stem (skipped when the top-level heading already matches it) — the LLM-free
  version of "contextual chunk headers".
- No way to see a hit's surroundings: `query -c/--context N` prints up to N neighboring chunks
  from the same file on each side of every result — the LLM-free version of the "context
  enrichment window".
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
