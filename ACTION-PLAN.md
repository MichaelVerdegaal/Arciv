# Clotho: Action Plan v3 — Trustworthy Archive

## The Problem

I write daily notes in Obsidian and accumulate links to technical resources — documentation, blog
posts, papers, repos. Over time I can't find them again. The URL is opaque, the daily note only
gives me a date, and search can only match words I happened to write — not the content behind the
link.

## What This Tool Does

Clotho extracts URLs from Obsidian daily notes, scrapes their content, and archives them as
searchable markdown files on disk. Good archival tool, not half-baked archival-plus-retrieval. An
archive you can ripgrep is already useful on day one.

## CLI

```bash
clotho scrape                    # Scrape all new URLs
clotho scrape --refetch          # Re-download all pages
clotho scrape --reparse          # Re-parse existing HTML into markdown
clotho update-agents             # Fetch latest browser user-agent strings
```

## The Plan

### Step 1: Lock the data model ✅

Storage layout is `/saved/<slug>/page.html` and `/saved/<slug>/page.md`, reusing the existing
`<domain>-<hash>` slug convention. Co-locating the two files kills the "two subfolders per page"
annoyance, and md-present-or-not on disk becomes an instant parse-status signal.

The DB holds pointers and minimal state, not content:

```sql
pages:
  url          TEXT PRIMARY KEY            -- normalized URL
  original_url TEXT NOT NULL               -- pre-rewrite URL (debugging the rewriter)
  domain       TEXT NOT NULL               -- microsoft, arxiv, substacks dominate
  slug         TEXT NOT NULL               -- folder under /saved/, e.g. "github.com-a1b2c3d4"
  fetched      INTEGER NOT NULL DEFAULT 0  -- 1 = valid HTML archived
  fail_reason  TEXT                        -- null on success; else "cloudflare"/"too_short"/"http_404"
  title        TEXT
  author       TEXT
  word_count   INTEGER NOT NULL DEFAULT 0
  scraped_at   TEXT

page_sources:                              -- unchanged
  url, note_name  (PRIMARY KEY url, note_name)
```

Dropped: `status` (collapsed to `fetched` bool + `fail_reason`), `md_content` (on disk now),
`html_path` (replaced by `slug`), `embedding`.

### Step 2: Rewrite the storage layer ✅

Mostly deletion from the old database.py (embedding and status methods go) plus one async helper
that writes HTML and markdown into the slug folder. The scraper produces content and metadata;
storage just lands it. The patchright swap also lands here — drop-in import swap that passes
Cloudflare and the usual bot checks. Delete the rotating user-agent list and drop playwright-stealth
entirely. Patchright's recommended setup injects no fingerprint and sets no custom user-agent or
headers.

### Step 3: Add quality validation ✅

Validate before marking `fetched`. For an archive you'll trust years from now, the worst outcome is
silently storing a Cloudflare challenge or a 404 page as if it were the article. After fetch, reject
content that:

- Is suspiciously short
- Matches known block-page signatures ("just a moment", "attention required", "enable javascript",
  "browser is no longer supported")
- Exceeds max file size (~10MB)

Mark rejected content `fetched=0` with a reason instead of archiving junk. Log each rejection with
its reason and emit a single summary line at the end.

### Step 4: Run a full baseline over the whole vault ✅

Ran against ~1098 URLs. Raw archival: 830/1098 (76%). Adjusted for non-archivable content (JS SPAs,
auth-walled, login pages, search pages): ~88-90%. The validation layer proved its value — 41 dead
freedium redirects caught, Cloudflare blocks detected, too-short pages filtered.

### Step 5: Close the gap to ~95% ✅

Executed the full remediation plan based on baseline results:

**Tier 1 (highest recovery per effort):**
- **arxiv PDFs (16):** Added `/pdf/` → `/abs/` rewrite in url_processor. No PDF parser needed.
- **Medium via freedium (41):** Removed the dead freedium-mirror.cfd rewrite entirely. Medium URLs
  now fetched directly — patchright clears most of Medium's soft wall. Lesson learned: third-party
  mirror rewrites are fragility, not reliability.
- **URL extraction regex:** Rewrote `extract_urls()` to use a two-pass approach: first extracts
  from markdown link syntax `[text](url)`, then catches bare URLs. Eliminates trailing junk like
  `)seasonalities`, `)/`, `)+` that were creating broken or near-duplicate entries.

**Tier 2 (worth doing):**
- **Patchright best practice:** Switched to `launch_persistent_context()` with `channel="chrome"`,
  `headless=False`, `no_viewport=True`, no custom user-agent or headers. This is patchright's
  recommended stealth configuration. Recovers Cloudflare-protected sites (neptune.ai,
  machinelearningmastery, openai docs, acm).
- **Retry for transient failures:** Added automatic retry (up to 2 attempts) for timeouts and
  connection resets. Covers kubernetes.io, lightning.ai, giskard.ai etc. that fail under concurrency.
  Increased base timeout from 10s to 15s.
- **Raw text URLs:** `.md`, `.txt`, `.rst` files (e.g. raw.githubusercontent.com) now skip
  trafilatura and store content directly. Trivial fix, fits the existing URL-strategy approach.

**Tier 3 (accepted gaps):**
- Added a skip-list for non-content URLs: `claude.ai` (chat links), `lnkd.in` (shorteners),
  `support.dfg.nl` (internal), `google.com/search`. These are marked "skipped (not content)"
  instead of cluttering the failure summary.
- ~179 long-tail singletons (JS SPAs, auth-walled, dead domains) left as known, logged gaps.

**Other cleanup:**
- Removed `liteparse` dependency. arxiv `/pdf/` → `/abs/` rewrite covers the PDF need without a
  parser. The handful of true non-arxiv PDFs don't justify a whole PDF path yet.
- Added Click CLI with `scrape` (with `--refetch` and `--reparse` flags) and `update-agents`
  commands.
- Removed `.pdf` from `SKIP_SUFFIXES` (arxiv PDFs get rewritten, not skipped).

### Step 6: PDFs — Parked

The gate says no. arxiv PDFs are covered by the `/pdf/` → `/abs/` rewrite. The handful of true
non-arxiv PDFs (SSRN, d-nb) don't justify a PDF parsing path. Revisit only if abstract-only arxiv
entries prove insufficient during actual archive use.



## After v1

Declare archival v1 done and actually use it. Interim retrieval is ripgrep over `/saved/**/*.md`.
Add FTS5 only once the search gap is felt, not before. Brotli, proxies, and the exploration crawler
stay parked until a concrete need appears.
- Embed and search alongside web pages



## Parking Lot (revisit only when there's a concrete need)

- **PDF parsing (liteparse)**: Only if arxiv abstracts prove insufficient during actual use.
- **Topic tagging with KeyNMF**: Revisit as enrichment layer *after* semantic search is in daily
  use. Only if browsing-by-topic turns out to be a real need.
- **model2vec / static embeddings**: If corpus grows past ~5k documents and embedding speed becomes
  a bottleneck.
- **Obsidian plugin / integration**: Only if the CLI→frontend path proves insufficient. Building an
  Obsidian plugin is its own project.
- **RAG with LLM**: Full question-answering over saved content. The embedding search is the
  retrieval half; adding an LLM for generation is straightforward once retrieval works. But search
  alone might be sufficient.
- **Automatic re-scraping**: Periodic refresh of pages that might have updated. Low priority — most
  saved content is static.
- **Bloom filters for deduplication**: Current URL dedup is fine at this scale.
- **Wayback Machine fallback**: For member-only Medium articles and other paywalled content.
  Worth considering if direct Medium fetching proves insufficient.



## Discarded Routes (for reference)

### Keyword extraction with YAKE
Statistical, collection-independent, per-document. Struggled with technical terms and hyphenated
compounds (e.g. "Chronos-2"). Embedding-based approaches handle these much better.

### Topic modeling with KeyNMF
Got 15 clean topics (forecasting, ML/DL, agents, MLOps, MCP, Copilot). Didn't solve the actual
problem — topic labels don't help *find* a specific resource. Was solving "organize" when I needed
"retrieve."

### Domain-based Obsidian graph
Grouped ~788 URLs by registered domain. Big clusters (microsoft.com, github.com) too broad; small
clusters just moved the "remember 700 things" problem to "remember 300 domain names."

### Freedium mirror rewrite
Rewrote Medium URLs to `freedium-mirror.cfd`. The mirror died, returning 39-byte empty responses for
all 41 Medium links. Third-party mirror rewrites are fragility, not reliability. Removed in favor of
direct Medium fetching with patchright.



## Principles

- **2am test**: Can I understand and debug this at 2am? If not, rewrite it.
- **Build for what exists, not what might exist**: No deep exploration until depth-1 search works
  well. No frontend until the CLI reveals what's needed. Schema can anticipate future needs, but
  code paths should only exist for what's implemented.
- **Retrieval over organization**: The goal is to *find* things, not to *categorize* them.
  Organization is a secondary enrichment, not the core.
- **Swap later is fine**: Embedding model, database, scraper — all are replaceable. Ship something
  that works, iterate based on real usage.