# Plan

Clotho is my main archival tool for all reading material — blog posts, research papers,
documentation. Not books, not videos. Fetching and parsing are in good shape (see
[ACTION-PLAN.md](ACTION-PLAN.md) for the completed v1 work); the gap is user experience:
getting insight into what was fetched. That means a web UI, and the groundwork for it.

Status of the next-steps notes:

- ✅ Better CLI experience — `clotho fetch [URLS] [--dir] [--refetch]` and `clotho parse` exist
- ✅ Three stages (indexing, fetching, parsing), no writeback
- ✅ `.txt` and `.rst` archived too, not just `.md` (`RAW_TEXT_EXTENSIONS` in url_processor.py)
- ✅ Dockerize early — CLI image + compose setup
- ⏳ Web UI — next up, groundwork done (below)
- ⏳ Collections ("libraries") — design pending (below)


## 1. Web UI

A must-have: the CLI alone is too annoying for viewing stored results, and browsing the archive
is the best way to gain insight into what was fetched earlier. Astro for the frontend, otherwise
a blazingly-fast plain HTML site. References:

- https://news.ycombinator.com/item?id=48475483
- https://news.ycombinator.com/item?id=48437609

Likely shape: a static site under `frontend/` that reads `data/clotho.db` and
`data/saved/<slug>/page.md` at build time — no backend server until something needs one. The
storage contract it builds against is documented in AGENTS.md.

Page views to design before writing any code (ideas, not decisions):

- **Archive index** — sortable/filterable list: title, domain, word count, scraped date, link to
  the original URL
- **Page detail** — rendered markdown, source notes that referenced it, fetch metadata
- **Search** — start dumb (client-side index over titles, or SQLite FTS5 once the gap is felt)
- **Collections** — browse by library, once collections exist

Groundwork already in place: `CLOTHO_DATA_DIR` to point a frontend build at the data root,
Docker for running everything anywhere, storage contract documented. One thing to settle at
implementation time: the DB runs in WAL mode, so a build step reading it should open it
read-only and may need a checkpoint first (or copy the file).

## 2. Collections ("libraries")

Pinchflat's "source" concept is well done and close to the original `DataSource` class idea —
but for reading material: a collection is a named set of pages ("MLOps", "papers", "to read").

Design sketch (not committed): a `collections` table plus a `page_collections` join table;
assignment manual via the CLI first (`clotho collection add <name> <url>`), rule-based
auto-assignment (by domain, by source note) only if manual proves tedious. Decide the schema
together with the web UI views so the data model serves what's actually displayed. Schema
changes are ask-first per AGENTS.md.

## 3. CLI polish (ongoing)

Only what real usage demands. Candidates: `clotho status` (counts, recent fetches, failure
summary without opening the DB), `clotho list --domain <d>`. Not a priority while the web UI
is the main viewing surface.


## Known fetch gaps

- Cookie-consent walls eat some pages (e.g. gigaom rejected as "too short")
- researchgate.net abstract pages are too short, but link a downloadable PDF
- ~179 long-tail singletons accepted as gaps (JS SPAs, auth-walled, dead domains)

## Parking lot (carried over from v1)

- FTS5 / semantic search — only once the search gap is actually felt
- RAG over the archive — retrieval first, generation maybe never
- Wayback Machine fallback for paywalled content
- Obsidian plugin — only if the CLI + web UI path proves insufficient
- Automatic re-scraping of updated pages
- If indexing should ever cover `.txt`/`.rst` *notes* (not just archived URLs), that's a small
  change in `Note.get_note_files`
