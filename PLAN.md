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

## Link mining (in progress)
Notes are often just carriers for the URLs in them, and some webpages (a web book's ToC, a link
roundup) are pure link hubs. The archive pipeline shouldn't be the only way to get at those links,
so two composable pieces:

- `arciv extract <file|->`: offline link extraction from note text (the same `extract_urls` the
  index stage uses), one URL per line on stdout, no database writes. The "my note is boring but its
  links aren't" case: `arciv extract note.md | arciv get -`.
- `arciv get <url> --no-save`: fetch the page, print its links (absolute, deduped) to stdout, store
  nothing — no page row, no `saved/` folder. Link extraction runs on the live response DOM via
  Scrapling's `LinkExtractor`, so relative links resolve against the real base URL; trafilatura is
  deliberately not in this path (its boilerplate pruning is trained to kill link-list pages). The
  ToC case: `arciv get <toc-url> --no-save | arciv get -`.

Decisions made along the way:
- `LinkExtractor` must be configured with `deny_extensions=()`: its default drops `.pdf`, which
  would silently discard exactly the paper links Arciv exists to archive.
- The printed links are raw (only deduped): the downstream `arciv get -` re-applies the rules and
  plumbing guards anyway, and filtering belongs to grep in the middle of the pipe.
- `canonicalize()` keeps its opinionated layer (strip `www.`, trailing slash, tracking params) and
  delegates the mechanical normalization (percent-encoding, query sorting) to w3lib's
  `canonicalize_url` (already in the tree via Scrapling). No migration: the archive is pre-1.0 and
  gets recreated.
- Both extractors live together in `arciv.core.index.links` — same job (URLs out of an input
  string), different method (regex over note text vs. `LinkExtractor` over a DOM). Discovery is the
  index stage's identity; `notes` keeps only file reading, `fetch` keeps only the browser I/O.
- The min-words knob (`ARCIV_MIN_WORDS`) is gone: nobody can dial it meaningfully. A fixed low
  floor stays as the only guard against consent walls and empty JS shells posing as parsed pages,
  and the rejection reason now names the threshold so the gate is transparent.

This is the foundation for the parked crawl/depth item, not the item itself: when that unparks,
Scrapling's `CrawlSpider`/`SitemapSpider` (same `LinkExtractor` underneath, plus scheduling, dedup,
politeness, checkpointing) becomes the engine, with Arciv supplying URL rules and the archive sink.
The pipe stays the manual, human-in-the-middle version — grep-able between stages.

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
- Crawl / depth (see "Link mining" above for the shipped foundation and the intended engine).
- `arciv show`: a read-only viewer that renders a page's markdown to a pager or browser, if a viewer
  is ever wanted again (the removed web app's only feature worth missing). No server.

## Rejected
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
