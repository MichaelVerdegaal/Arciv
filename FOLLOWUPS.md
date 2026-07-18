# Follow-ups

Known limitations, deliberately not fixed yet (see PLAN.md scope rules):

- Indexing a subdirectory of a collection's pinned root is refused (the pin check is an exact
  match), so refreshing one folder means re-indexing the whole root. Fine at current corpus
  sizes; revisit if indexing ever feels slow.

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

- `query -c/--context N` (neighboring chunks around each result): removed as not useful enough —
  the result's `source` path makes it trivial to `cat` or open the file for surrounding context.
- Full heading trail in breadcrumbs (`title > H1 > H2 > ... > H6`): deep nesting plus verbose
  headings made breadcrumbs long enough to eat into the chunk token budget. Breadcrumbs are
  bounded instead: title, top heading, and the section's own heading, each segment trimmed.
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

- One root per index: named collections now hold one root each (`index --collection NAME`,
  default `microrag`); `query` merges results across collections by cosine distance and
  `--collection` narrows it. Roots are recorded per collection in `roots.json` (the legacy
  `root.txt` marker is still honored for the default collection).
- Deleted files lingering in the index: pruning now runs by default on every `index` (opt out
  with `--no-prune`); the mistyped-path danger that motivated opt-in is covered by the root pin
  and the empty-walk guard. Plain `query` output now emits absolute paths, so results pipe
  straight into `cat`/`xargs` regardless of which root they came from.
- Image alt text not indexed: alt texts are now chunked as their own sections under the heading
  in effect at their position (filename-fallback aliases are skipped as noise).
- Root collision and `--prune` ambiguity: the index is now pinned to the first root it was built
  from; `index` refuses a different root. (Since superseded by named collections, one root each —
  see above.)
- Chunks before the first heading carried no document context: every breadcrumb now starts with
  the filename stem (skipped when the top-level heading already matches it) — the LLM-free
  version of "contextual chunk headers".
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
