# Plan

Arciv is my main archival tool for all reading material — blog posts, research papers,
documentation. Not books, not videos. The strategy: build the entire backend as a super
streamlined CLI tool first. When that foundation is right, the frontend part will barely have
to do anything.

## Architecture: two parts

The project splits into two deployables to keep responsibilities isolated:

1. **CLI tool** (this repo's `arciv/` package) — all archival logic. Runnable easily as a uv
   tool (`uv tool install`), deliberately **not** containerized.
2. **Web app** (`arciv_api/`) — one Python (FastAPI) service that imports the arciv library
   (never shells out), reads through read-only connections, and renders its own HTML with
   Jinja2 + Datastar (BeerCSS). Gets a dedicated container. (Originally planned as a
   separate backend plus an Astro frontend; collapsing to one server-rendered service dropped
   the second runtime and the internal-vs-public URL juggling the split needed.)

The CLI is complete; the web app implements browse, page detail, domains, sources, status, and
the archive job flow (a single in-process fetch+parse worker behind `POST /archive`).

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
arciv add <directory> <name>   # register a source and archive it
arciv archive <name>           # re-index, fetch, and parse one source
arciv archive --all            # archive every registered source
arciv remove <name>            # unregister it (indexed pages are kept)
arciv sources                  # list registered sources
arciv index <name>             # index a single source (stage only)
arciv index --all              # index every registered source (stage only)
```

`add` archives the source after registering (pass `--no-archive` to skip);
`archive` re-runs the whole pipeline as one batched fetch, so adding or
re-syncing a source is a single command instead of `add` + `index` + `fetch` +
`parse`. The web app exposes the same: add/remove a source, view its indexed
files and the links found in each, and re-archive, with the slow fetch+parse
running in a background batch.

### Data directory — ✅ implemented

The data root defaults to the OS user data dir via platformdirs (Linux:
`~/.local/share/arciv`, Windows: `%LOCALAPPDATA%\arciv`). Chosen with the Docker backend
in mind: it lives outside any repo checkout, so the backend container can mount it directly.
`ARCIV_DATA_DIR` still overrides it (e.g. `ARCIV_DATA_DIR=data` in `.env` when developing
from a clone).

## 1. Web app — ✅ implemented

A web UI is a must-have: the CLI alone is too annoying for viewing stored results, and
browsing the archive is the best way to gain insight into what was fetched earlier. Built as a
single server-rendered FastAPI service (Jinja2 + Datastar, BeerCSS), deliberately not
Astro: Arciv is heading toward CLI parity in the browser (archive a URL with live status),
which is a reactive webapp, not a static content showcase. References:

- https://news.ycombinator.com/item?id=48475483
- https://news.ycombinator.com/item?id=48437609

The web app imports the arciv library (it does not shell out) and reads `arciv.db` /
`saved/<slug>/` under the data dir through read-only connections — the storage contract it
builds against is documented in AGENTS.md. It renders its own HTML (page markdown is rendered
to HTML in Python and sanitized), so there is no separate frontend runtime. It gets a
dedicated container (the CLI does not).

Routes: `GET /` (browse), `/page/{slug}` (+ `/progress` poll), `/domains`, `/sources`
(+ `/sources/{name}` detail, `POST /sources`, `/sources/{name}/archive`,
`/sources/{name}/delete`), `/status`, `/rules`, and `POST /archive`. Source writes use a
short-lived read-write connection in a thread (the rules pattern); the slow fetch+parse runs
in a background batch off the request. Page views (status):

- **Archive index** — ✅ sortable/filterable list: title, domain, word count, fetch date, link
- **Page detail** — ✅ rendered markdown, source files, fetch metadata, live archive status
- **Sources** — ✅ add/remove a source, view its indexed files and the links found in each,
  and re-archive; plus a **Status** dashboard
- **Search** — parked (client-side over titles, or SQLite FTS5 once the gap is felt)

The DB runs in WAL mode; the web app opens it read-only (a `mode=ro` connection that skips the
schema) with one short-lived connection per request — implemented in `PageDatabase`.

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
