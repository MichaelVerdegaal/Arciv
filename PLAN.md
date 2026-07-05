# Plan

Arciv is my archival tool for reading material: blog posts, research papers, documentation.
Not books, not videos. It extracts URLs from notes (`.md`, `.txt`, `.rst`), fetches and parses
them to clean markdown, and stores metadata in SQLite.

This is now a single CLI tool. The web app is being removed (see below): the maintenance cost
isn't worth it while the archival experience is still settling, and dropping it deletes a whole
runtime, the async worker, and the read-only DB contract along with it.

## Architecture: one deliverable

The `arciv/` package, runnable as a uv tool (`uv tool install`), holding all archival logic.
Deliberately not containerized. There is no second service and no separate frontend runtime.

Data lives under the OS user data dir via platformdirs (Linux: `~/.local/share/arciv`),
overridable with `ARCIV_DATA_DIR`. It sits outside any checkout so it survives reinstalls.

## CLI: implemented

Layered pipeline, run whole or per stage.

```bash
arciv get <URL>            # archive one URL
arciv get --file <path>    # archive all links in one file
arciv get --dir <path>     # archive all links in a directory
```

`get` runs index, then fetch, then parse under one command. Each stage is also its own command
(`index`, `fetch`, `parse`) for development.

- `index`: extract links from `.md` / `.txt` / `.rst`, store link, normalized source filepath,
  and index time.
- `fetch`: download pending URLs and save raw content to disk.
- `parse`: convert fetched HTML / PDFs to markdown.

### Sources: implemented

A source is a registered directory.

```bash
arciv source add <dir> <name>          # register and archive (--no-archive to skip)
arciv source update <name> | --all     # re-index, fetch, parse
arciv source remove <name>             # unregister (pages kept)
arciv source remove <name> --remove-files  # also delete files only it links
arciv source                           # list sources
arciv list --source <name>             # pages indexed from one source
```

`source remove --remove-files` deletes archived files of pages this source links exclusively;
pages another source or an ad-hoc `get` still link are kept (URL ownership is computed before
the FK cascade).

### Other commands: implemented

`status`, `list` (tab-separated `fetched-at  domain  url`, newest first, with `-n` / `--reverse`
/ `--domain`), `path <URL>` (prints a page's archived markdown path for `less $(arciv path ...)`),
`db dir` / `db remove`, `prune missing|failed|all`.

### Identity / dedup: resolved

`canonicalize` is the canonical key: lowercase host, drop default ports, strip `www.`, trim
trailing slash, drop tracking params, sort the query. It runs last in URL processing and feeds
both the page identity and the slug, so equivalent forms collapse to one row. No separate dedup
pass or migration needed; single-user means re-index and move on.

## 1. Remove the web app

Delete the FastAPI service, Jinja2/Datastar templates, the asyncio queue worker and lifespan
manager, the read-only `PageDatabase` path, and the AGENTS.md storage contract. This is mostly
subtraction and unblocks the two changes below by shrinking the surface they touch. Salvage
nothing for now; if a read-only viewer is ever wanted it can come back as a small `arciv show`
that renders markdown to a pager or browser, no server.

## 2. Fetch layer: move to Scrapling

Committed. Scrapling's `StealthyFetcher` runs patchright (the engine I already use) wrapped in a
nicer interface, with CDP-leak patching, canvas noise, a Cloudflare Turnstile auto-solver, and
ProxyRotator / spider helpers available for later. So this is an ergonomics-and-extras move, not
an engine change, and there's no stealth regression versus running patchright directly.

The win is a unified fetch layer: `StealthyFetcher` (patchright) for HTML and `Fetcher`
(curl_cffi, TLS-impersonated) for PDFs and direct downloads, both returning one Response type.
This collapses today's patchright + niquests + urllib spread into one library.

Two things to confirm during the migration, since they're where a wrapper can cost you:

- Route blocking still works (drop images/stylesheets/fonts for speed).
- The underlying Playwright Page is still reachable, in case response interception is ever wanted
  for image archiving.

If both hold, the unification is worth the dependency. Budget a focused day or two, mostly
re-testing against the known-gap targets and wiring the session lifecycle into the CLI, not the
"one-line swap" the docs imply.

nodriver is the documented fallback, not a migration: if a specific target I care about blocks
`StealthyFetcher` even with the Turnstile solver, reach for nodriver for that one target. Its
cost (asyncio object model, no Playwright API) isn't worth paying for a hard gate I don't
currently hit.

## 3. Rule system redesign

The current system has two flaws. Code rewriters (github, huggingface, raw.github) are flexible
but not extendible. The data rules are extendible but not flexible, and their behavior is
confusing because the rewrite span is derived from the match type (replace the netloc for a
domain match, the prefix for `starts_with`, and so on). The redesign fixes both by decoupling
matching from action and making rules data, not code or SQL.

### Model

A rule is a match plus an ordered list of actions. The match decides only whether the actions
apply. The actions transform the URL in sequence.

Match types: `domain` (registrable, tldextract), `host` (exact), `starts_with`, `regex`. Drop
`ends_with` and `exact`; nothing real uses them.

Action types:

- `skip`: end processing, don't archive.
- `prepend`: put text in front of the whole URL (mirror gateways).
- `replace`: literal old to new substring.
- `regex_replace`: pattern to replacement with `$1` capture groups.

`append` (suffix) gets added when a URL actually needs it, not before. The split that keeps users
out of regex: `prepend` and `replace` are the regex-free path they live in; `regex_replace` is
the escape hatch I author once for the github family and ship as a default. No user writes a
regex.

### The four real rewrites, as data

- medium: match `domain medium.com`, `prepend https://freedium-mirror.cfd/`. Preserves the
  subdomain the old netloc-hack dropped.
- huggingface pdf: match `regex huggingface\.co/.+/blob/.+\.pdf`, `replace /blob/` with
  `/resolve/`. Regex match so it fires only on the pdf case; regex-free action.
- github: match `regex ^https://github\.com/[^/]+/[^/]+/(?:blob|tree)/(?!.*\.(?:md|txt|rst)$)`,
  `regex_replace ^https://github\.com/([^/]+)/([^/]+)/(?:blob|tree)/.*` to
  `https://github.com/$1/$2`. The negative lookahead in the match keeps READMEs and other
  readable files archived instead of collapsed to repo root, so no halt-the-chain action is
  needed.
- raw.github: match `host raw.githubusercontent.com`,
  `regex_replace ^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/.*` to
  `https://github.com/$1/$2`.

### Plumbing stays in code

The universal "never fetch this" guards run before any rule, as code, not rules: media file
extensions, `/_next/image` proxy, IP-address hosts, localhost. These are immutable plumbing
(nobody un-skips a media file), so a guard is faster than a per-URL regex and keeps the rule list
clean. Policy skips that someone might reasonably edit (youtube, sharepoint, azure, lnkd.in,
google search results) live as default rules with a `skip` action.

### Storage

Rules move out of the DB entirely: delete the `Rule` table, the seed-into-SQL, and the
`rules add` / `rules remove` CRUD. Keep `arciv rules test <url>`, which loads the rules and prints
which rule and action fired.

Format is TOML (`tomllib`, stdlib in 3.12, read-only is all that's needed). Array-of-tables with
nested actions:

```toml
[[rule]]
name = "medium to freedium"
type = "domain"
match = "medium.com"
  [[rule.action]]
  type = "prepend"
  text = "https://freedium-mirror.cfd/"

[[rule]]
name = "huggingface readable pdf"
type = "regex"
match = 'huggingface\.co/.+/blob/.+\.pdf'
  [[rule.action]]
  type = "replace"
  old = "/blob/"
  new = "/resolve/"
```

Chaining is dumb sequential application: no conditionals, no inter-action state, no halt action.
Nothing chains today (every rule is one action); build the list shape because it's nearly free,
but don't add control flow until a real rule needs it.

### Sequencing

1. Build the match/action engine and ship the defaults as a packaged TOML, loaded at runtime
   (this is the "defaults in creation SQL is weird" fix: the SQL goes away, not relocates).
2. Move github/hf/raw.github out of code into those defaults.
3. Then add user rules: a `rules.toml` the user creates in the data dir, loaded ahead of the
   defaults so user rules win on first match. This last step is for once the core rewrite is
   done.

## Known fetch/parse gaps

- medium.com paywall: handled by the freedium mirror rule.
- github / huggingface path surgery: handled by the redesigned rules.
- Cookie-consent walls eat some pages (rejected as "too short").
- researchgate.net abstract pages are too short but link a downloadable PDF.
- ~179 long-tail singletons accepted as gaps (JS SPAs, auth walls, dead domains). A stealthier
  fetcher doesn't fix these; they're payment, consent, or dead-domain problems, not fingerprint
  problems.

## Efficiency follow-ups: implemented

A batch of DB round-trip reductions, done as their own PR to keep the diff
reviewable. All were self-contained and covered by existing tests.

- **Duplicate `db.get()` per URL in a fetch batch** (`fetch/fetcher.py`): the
  batch now looks every candidate up once via a chunked
  `get_many(...)` (`SELECT ... WHERE url IN (...)`) and passes the row into
  both `_needs_fetch` and `_entry_for`.
- **`register_urls` commits once per URL** (`index/index.py`): entries are
  collected in the loop and `ensure_pages` is called once after it, as
  `_index_notes` already did.
- **N+1 queries in run-scoped failure reporting** (`cli/cli.py`
  `_count_failed`, `pipeline/fetch.py` `report`): both use one chunked
  `db.failures_for(urls)` (`SELECT domain, fail_reason ... WHERE url IN (...)`)
  instead of a `db.get(url)` per touched URL.
- **Per-row commit in batch parse/fetch loops** (`db/database.py`): a
  `db.bulk()` context manager defers `upsert` commits and flushes every 50
  writes (and on exit, including on error), used around the parse loop and the
  fetch batch — the fetch-side commit also ran on the event loop, so batching
  helps there twice.
- **Counts materialize full row sets**: `count_unfetched()` and URL-only
  variants (`get_all_urls`, `get_unfetched_urls`, `get_fetched_urls`,
  `get_unparsed_urls`) replace the call sites that built Page objects just to
  count rows or read `.url`.

## Parking lot

- Image archiving: a branch saves images and inlines markdown links to them, parked because it
  added an obscene amount of code for reading material where the text is the point. If revisited,
  do it as response interception in the same `StealthyFetcher` pass, not a second urllib
  round-trip.
- FTS5 / semantic search: only once the search gap is actually felt.
- Wayback Machine fallback for paywalled content.
- Automatic re-scraping of updated pages.
- Crawl / depth.

## Rejected

- Web app, for now: maintenance cost too high while archival is still settling.
- Rules in the DB: the table and CRUD existed to serve the web UI over HTTP; with that gone, a
  hand-edited TOML file is simpler than rows mutated through a CLI.
- Old/new-only rewrite (no regex action): can't express github (variable-length delete, host
  swap), so it would need rewriting on the first real rule.
- YAML for rules: pulls a parser dependency for nothing over stdlib TOML.
- Obsidian plugin: Arciv is not Obsidian-specific.

## Principles

- 2am test: can I understand and debug this at 2am? The plumbing-as-code, rules-as-data split
  follows from this, code for immutable structural facts, data for editable policy.
- Build for what exists, not what might exist: no `append` action, no chain control flow, no
  proxy rotation wiring until a real case needs it.
- Retrieval over organization: find things, don't categorize them.
- Swap later is fine: fetcher, database, parser are all replaceable. Ship what works, iterate on
  real usage.