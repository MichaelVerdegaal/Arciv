# Plan
Arciv is my archival tool for reading material: blog posts, research papers, documentation. Not
books, not videos. It extracts URLs from notes (`.md`, `.txt`, `.rst`), fetches and parses them to
clean markdown, and stores metadata in SQLite.

A single CLI tool, no web app. This file is the forward-looking roadmap: the standing shape, open
gaps, the parking lot, and rejected options. What's already shipped is documented in README.md
(usage) and the source code. The design write-ups for finished work; removing the web app, moving
the fetch layer to Scrapling, and turning the URL rules into TOML data, live in git history.

## Architecture: one deliverable
The `arciv/` package, runnable as a uv tool (`uv tool install`), holding all archival logic.
Deliberately not containerized. There is no second service and no separate frontend runtime.

Data lives under the OS user data dir via platformdirs (Linux: `~/.local/share/arciv`), overridable
with `ARCIV_DATA_DIR`. It sits outside any checkout so it survives reinstalls.

## Known fetch/parse gaps
- Cookie-consent walls eat some pages (rejected as "too short").
- researchgate.net abstract pages are too short but link a downloadable PDF.
- ~179 long-tail singletons accepted as gaps (JS SPAs, auth walls, dead domains). A stealthier
  fetcher doesn't fix these; they're payment, consent, or dead-domain problems, not fingerprint
  problems.

(medium paywalls and github/huggingface path surgery are already handled by the shipped rules.)

## Link mining & crawl (shipped)
Link mining shipped as `arciv extract` and `arciv get --no-save` (the manual, grep-able pipe), and
the crawl/depth item shipped on top of it as `arciv get <url> --depth N`: a breadth-first loop over
the existing batch pipeline, where each level is one index→fetch→parse batch and the next frontier
comes from the links of the level's HTML pages, read back from the `page.html` files already on
disk. Rules apply at every hop; the crawl stays on the seeds' registered domains (cross-domain hops
remain the pipe's job); already-fetched pages are skipped but still contribute links, so a killed
crawl resumes on rerun with the database as the checkpoint. Full design notes live in git history,
per convention.

## Semantic search (shipped as the `search` extra)
Local semantic search over markdown, merged in from the standalone MicroRag tool. The engine lives
in `arciv/search/` and the `arciv search` sub-app in `arciv/cli/search.py`, behind the optional
`search` extra so a plain `arciv` install never pulls chromadb/onnxruntime (the sub-app degrades to
an install hint when the extra is absent). Retrieval only, no generation; the "G" in RAG is a
separate decision with its own constraints.

Locked pieces carried over from MicroRag: ChromaDB `PersistentClient`, cosine space, one named
collection per indexed root pinned in `roots.json`; the `MongoDB/mdbr-leaf-ir` fp32 ONNX embedder on
CPU with explicit embeddings (no Chroma embedding function, so the query-only prompt prefix stays
correct); content-addressed chunk IDs for incremental re-index.

Storage boundary: Chroma is a derived index, not a store of record. It holds text chunks keyed to
embeddings and is rebuildable from the archive at any time; the source of truth stays markdown + raw
HTML on disk with SQLite tracking pipeline state. Chroma-as-document-store was considered and
rejected: no blob/image storage, only flat metadata filters (no joins/aggregates for `list
--domain`, `status`, `prune`), and it would force chromadb into the core dependencies.

Follow-ups, deliberately out of the merge:
- Auto-indexing: `arciv get` feeding archived markdown into the search index, or `arciv search`
  defaulting to the archive dir. The natural next step once the seam settles.
- The default collection is still named `microrag`; renaming it would orphan existing indexes, so it
  needs a migration decision.
- `arciv/search` uses Arciv's base ruff (I/B/UP), not MicroRag's stricter ANN/D/PTH/PLC0415 set.
  Re-enable per-directory if wanted.
- `arciv db dir` / `arciv status` don't mention the search home (unchanged output contract);
  `arciv search status` surfaces it instead.
- MicroRag shipped a LICENSE; Arciv has none. Licensing is the owner's call.

## Parking lot
- Image archiving: a branch saves images and inlines markdown links to them, parked because it added
  an obscene amount of code for reading material where the text is the point. If revisited, do it as
  response interception in the same `StealthyFetcher` pass, not a second urllib round-trip.
- FTS5 keyword search over the archive: still open (zero new dependencies, complementary to the
  semantic search that shipped above). Only once the exact-keyword gap is actually felt.
- Wayback Machine fallback for paywalled content.
- Automatic re-scraping of updated pages.
- `arciv show`: a read-only viewer that renders a page's markdown to a pager or browser, if a viewer
  is ever wanted again (the removed web app's only feature worth missing). No server.

## Rejected
- Scrapling's `Spider`/`CrawlSpider` as the crawl engine (the earlier intent): evaluated when the
  crawl unparked, not adopted. What it adds (priority scheduling, fingerprint dedup, per-domain
  limits and delays, robots.txt, pause/resume checkpointing) is engine plumbing for large
  open-ended crawls; what Arciv needs is depth-limited archiving, and the spider has no depth
  concept of its own (it would be hand-rolled through `Request.meta` regardless). Adopting it also
  meant duplicating the archive sink — the Fetcher's storage, PDF routing (a second session, since
  the stealth session errors on downloads), and transient-retry logic — inside spider callbacks,
  plus a second execution model (anyio, its own logging/session management) next to the batch
  fetcher. The BFS over the existing batch pipeline reuses all of that and keeps the database as
  the checkpoint. Revisit only if crawls grow to where politeness/robots.txt actually bite.
- Web app: maintenance cost too high while archival is still settling.
- Rules in the DB: the table and CRUD existed to serve the web UI over HTTP; with that gone, a
  hand-edited TOML file is simpler than rows mutated through a CLI.
- Old/new-only rewrite (no regex action): can't express github (variable-length delete, host swap),
  so it would need rewriting on the first real rule.
- YAML for rules: pulls a parser dependency for nothing over stdlib TOML.
- Obsidian plugin: Arciv is not Obsidian-specific.

## Principles
- 2am test: can I understand and debug this at 2am? The plumbing-as-code, rules-as-data split
  follows from this, code for immutable structural facts, data for editable policy.
- Build for what exists, not what might exist: no `append` action, no chain control flow, no proxy
  rotation wiring until a real case needs it.
- Retrieval over organization: find things, don't categorize them.
- Swap later is fine: fetcher, database, parser are all replaceable. Ship what works, iterate on
  real usage.
