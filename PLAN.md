# Plan

Arciv is my main archival tool for all reading material — blog posts, research papers,
documentation. Not books, not videos. The strategy: build the entire backend as a super
streamlined CLI tool first. When that foundation is right, the frontend part will barely have
to do anything.

## Architecture: three isolated parts

The project splits into three parts to keep responsibilities isolated:

1. **CLI tool** (this repo's `arciv/` package) — all archival logic. Runnable easily as a uv
   tool (`uv tool install`), deliberately **not** containerized.
2. **Backend** — calls the CLI for the most part, or works with the SQLite DB directly. Gets a
   dedicated container.
3. **Frontend** — the browsing/insight UI. Gets a dedicated container.

Only the CLI exists today; backend and frontend are the next phases.

## CLI design — ✅ implemented

A layered approach: single URL, single file, single dir.

```bash
arciv get <URL>            # archive one URL directly (single only, on purpose)
arciv get --file <path>    # archive all links within a single file
arciv get --dir <path>     # archive all links of all files within a directory
```

`get` runs the full pipeline — index, then fetch, then parse — under a single command. Each
stage also has a dedicated command, which makes developing the library easier:

- **`arciv index`** — extracts all links from wherever specified (`.md`, `.txt`, and
  `.rst` files). For each link a row is stored with the link value itself, the full
  normalized filepath where it was found, and the time it was indexed.
- **`arciv fetch`** — the patchright/playwright magic: downloads pending URLs (browser for
  HTML, direct HTTP for PDFs) and archives the raw content on disk.
- **`arciv parse`** — looks at the fetched HTML pages / PDFs and parses them to markdown.

### Sources — ✅ implemented

A "Source" is a registered file directory (entirely limited to directories for now):

```bash
arciv add <directory> <name>   # register a source (both args required)
arciv remove <name>            # unregister it (indexed pages are kept)
arciv sources                  # list registered sources
arciv index <name>             # index a single source
arciv index --all              # index every registered source
```

### Data directory — ✅ implemented

The data root defaults to the OS user data dir via platformdirs (Linux:
`~/.local/share/arciv`, Windows: `%LOCALAPPDATA%\arciv`). Chosen with the Docker backend
in mind: it lives outside any repo checkout, so the backend container can mount it directly.
`ARCIV_DATA_DIR` still overrides it (e.g. `ARCIV_DATA_DIR=data` in `.env` when developing
from a clone).

## 1. Backend + Frontend (next phase)

A web UI is a must-have: the CLI alone is too annoying for viewing stored results, and
browsing the archive is the best way to gain insight into what was fetched earlier. Astro for
the frontend, otherwise a blazingly-fast plain HTML site. References:

- https://news.ycombinator.com/item?id=48475483
- https://news.ycombinator.com/item?id=48437609

The backend mostly shells out to the CLI or reads `arciv.db` / `saved/<slug>/` under the
data dir directly — the storage contract it builds against is documented in AGENTS.md. Backend and
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

Only what real usage demands.

- `arciv status` — ✅ implemented: pipeline-state counts and failure summary. Recent
  fetches were dropped from it; that's `arciv list`'s job now.
- `arciv list` — ✅ implemented: fetched pages as `fetched-at TAB domain TAB url`, newest
  first. `--n` caps the row count (0 = everything), `--reverse` flips to oldest first,
  `--domain <d>` restricts to one registered domain (exact match, e.g. `medium.com`).
  Columns stay tab-separated so finer filtering is still `arciv list --n 0 | grep <pat>`.
- `arciv path <URL>` — ✅ implemented: prints the filepath of a page's archived markdown,
  composing with standard tools (`less $(arciv path <URL>)`, `grep ... $(arciv path ...)`)
  instead of reimplementing them. The URL is normalized the same way as at index time, so
  e.g. fragment variants resolve to the same page.
- `arciv db` — ✅ implemented: `db dir` prints the data directory (answers "where does
  my archive live", also without `ARCIV_DATA_DIR` set); `db remove` deletes the SQLite
  DB after confirmation (`--force` skips asking; archived files under `saved/` are kept).
- Parked until the implementation picture is certain:
  - Stale-row pruning (`arciv prune`?) — v1 pruned failed rows whose URLs vanished from
    the notes during indexing; that behavior was dropped in the stage split because partial
    (per-source) indexing made it unsafe. Revisit if dead rows actually accumulate.
- Logging cleanup (later) — prune noisy statements and add a `--verbose` flag, so default
  runs stay quiet and the detail lives behind the flag.

## Known fetch/parse gaps

- ~~Wikipedia pages lost every section heading~~ — fixed: MediaWiki puts an "[edit]" link
  next to each heading inside a small wrapper div, and trafilatura's link-density pruning
  deleted the whole div. The `mw-editsection` spans are now pruned before extraction.
  Re-run `arciv parse --reparse` to repair already-archived pages.
- medium.com is paywalled. Research how the freedium.cfd mirror works (its source code is
  fully available) — could inform a rewrite rule or fetch fallback.
- Cookie-consent walls eat some pages (e.g. gigaom rejected as "too short")
- researchgate.net abstract pages are too short, but link a downloadable PDF
- ~179 long-tail singletons accepted as gaps (JS SPAs, auth-walled, dead domains)

## Parking lot

- FTS5 / semantic search — only once the search gap is actually felt
- RAG over the archive — retrieval first, generation maybe never
- Wayback Machine fallback for paywalled content
- Automatic re-scraping of updated pages

## Rejected

- Obsidian plugin — Arciv is not Obsidian-specific (and is moving further away from that);
  the CLI + web UI path is the direction.

## Principles

- **2am test**: Can I understand and debug this at 2am? If not, rewrite it.
- **Build for what exists, not what might exist**: No frontend scaffolding until the page
  views are decided. Schema can anticipate future needs, but code paths should only exist for
  what's implemented.
- **Retrieval over organization**: The goal is to *find* things, not to *categorize* them.
- **Swap later is fine**: Embedding model, database, scraper — all are replaceable. Ship
  something that works, iterate based on real usage.
