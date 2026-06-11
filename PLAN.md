# Plan

Clotho is my main archival tool for all reading material — blog posts, research papers,
documentation. Not books, not videos. The strategy: build the entire backend as a super
streamlined CLI tool first. When that foundation is right, the frontend part will barely have
to do anything.

## Architecture: three isolated parts

The project splits into three parts to keep responsibilities isolated:

1. **CLI tool** (this repo's `clotho/` package) — all archival logic. Runnable easily as a uv
   tool (`uv tool install`), deliberately **not** containerized.
2. **Backend** — calls the CLI for the most part, or works with the SQLite DB directly. Gets a
   dedicated container.
3. **Frontend** — the browsing/insight UI. Gets a dedicated container.

Only the CLI exists today; backend and frontend are the next phases.

## CLI design — ✅ implemented

A layered approach: single URL, single file, single dir.

```bash
clotho get <URL>            # archive one URL directly (single only, on purpose)
clotho get --file <path>    # archive all links within a single file
clotho get --dir <path>     # archive all links of all files within a directory
```

`get` runs the full pipeline — index, then fetch, then parse — under a single command. Each
stage also has a dedicated command, which makes developing the library easier:

- **`clotho index`** — extracts all links from wherever specified. For each link a row is
  stored with the link value itself, the full normalized filepath where it was found, and
  the time it was indexed.
- **`clotho fetch`** — the patchright/playwright magic: downloads pending URLs (browser for
  HTML, direct HTTP for PDFs) and archives the raw content on disk.
- **`clotho parse`** — looks at the fetched HTML pages / PDFs and parses them to markdown.

### Sources — ✅ implemented

A "Source" is a registered file directory (entirely limited to directories for now):

```bash
clotho add <directory> <name>   # register a source (both args required)
clotho remove <name>            # unregister it (indexed pages are kept)
clotho sources                  # list registered sources
clotho index <name>             # index a single source
clotho index --all              # index every registered source
```

## 1. Backend + Frontend (next phase)

A web UI is a must-have: the CLI alone is too annoying for viewing stored results, and
browsing the archive is the best way to gain insight into what was fetched earlier. Astro for
the frontend, otherwise a blazingly-fast plain HTML site. References:

- https://news.ycombinator.com/item?id=48475483
- https://news.ycombinator.com/item?id=48437609

The backend mostly shells out to the CLI or reads `data/clotho.db` / `data/saved/<slug>/`
directly — the storage contract it builds against is documented in AGENTS.md. Backend and
frontend each get a dedicated container (the CLI does not).

Page views to design before writing any code (ideas, not decisions):

- **Archive index** — sortable/filterable list: title, domain, word count, fetch date, link to
  the original URL
- **Page detail** — rendered markdown, source files that referenced it, fetch metadata
- **Search** — start dumb (client-side index over titles, or SQLite FTS5 once the gap is felt)
- **Sources** — browse pages per registered source

One thing to settle at implementation time: the DB runs in WAL mode, so a build step reading
it should open it read-only and may need a checkpoint first (or copy the file).

## 2. CLI polish (ongoing)

Only what real usage demands. Candidates:

- `clotho status` — counts, recent fetches, failure summary without opening the DB
- `clotho list --domain <d>`
- Stale-row pruning (`clotho prune`?) — v1 pruned failed rows whose URLs vanished from the
  notes during indexing; that behavior was dropped in the stage split because partial
  (per-source) indexing made it unsafe. Revisit if dead rows actually accumulate.

## Known fetch gaps

- Cookie-consent walls eat some pages (e.g. gigaom rejected as "too short")
- researchgate.net abstract pages are too short, but link a downloadable PDF
- ~179 long-tail singletons accepted as gaps (JS SPAs, auth-walled, dead domains)

## Parking lot

- FTS5 / semantic search — only once the search gap is actually felt
- RAG over the archive — retrieval first, generation maybe never
- Wayback Machine fallback for paywalled content
- Obsidian plugin — only if the CLI + web UI path proves insufficient
- Automatic re-scraping of updated pages
- Indexing `.txt`/`.rst` files (not just `.md`) — small change in `Note.get_note_files`
- A fixed default data dir (e.g. platformdirs) for the uv-tool install; today it's
  `./data` relative to the working directory unless `CLOTHO_DATA_DIR` is set

## Principles

- **2am test**: Can I understand and debug this at 2am? If not, rewrite it.
- **Build for what exists, not what might exist**: No frontend scaffolding until the page
  views are decided. Schema can anticipate future needs, but code paths should only exist for
  what's implemented.
- **Retrieval over organization**: The goal is to *find* things, not to *categorize* them.
- **Swap later is fine**: Embedding model, database, scraper — all are replaceable. Ship
  something that works, iterate based on real usage.
