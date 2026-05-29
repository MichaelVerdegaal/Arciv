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

---

## The Plan

### Step 1: Lock the data model

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

### Step 2: Rewrite the storage layer

Mostly deletion from the old database.py (embedding and status methods go) plus one async helper
that writes HTML and markdown into the slug folder. The scraper produces content and metadata;
storage just lands it. The patchright swap also lands here — drop-in import swap that passes
Cloudflare and the usual bot checks. Delete the rotating user-agent list and drop playwright-stealth
entirely. Patchright's recommended setup injects no fingerprint and sets no custom user-agent or
headers.

### Step 3: Add quality validation

Validate before marking `fetched`. For an archive you'll trust years from now, the worst outcome is
silently storing a Cloudflare challenge or a 404 page as if it were the article. After fetch, reject
content that:

- Is suspiciously short
- Matches known block-page signatures ("just a moment", "attention required", "enable javascript",
  "browser is no longer supported")
- Exceeds max file size (~10MB)

Mark rejected content `fetched=0` with a reason instead of archiving junk. Log each rejection with
its reason and emit a single summary line at the end.

### Step 4: Run a full baseline over the whole vault

Point it at every note, fetch everything, then query: how many fetched, and group `fail_reason` by
domain. Runtime is minutes to an hour, mostly unattended. The output is the one number that decides
everything downstream — current coverage — plus a ranked list of what's failing and why. **Do not
optimize anything before having this.**

### Step 5: Close the gap to ~95%

Attack the biggest buckets first from the baseline results. Cloudflare → patchright already helped.
"Overview" or "no longer supported" pages → word-count and suffix checks handle most. Dead Medium
links → decide between Internet Archive fallback or accepting as a logged gap. **Stop at 95% and
leave the long tail as known, logged gaps.** A logged gap is fine; a corrupted archive entry is not.

### Step 6: PDFs (only if baseline says they matter)

If arxiv and PDF links are a meaningful share, add a lite-parse path that drops a `page.md` into the
same slug folder. If they're under a few percent, park them. Skip deep OCR tuning either way.

---

## After v1

Declare archival v1 done and actually use it. Interim retrieval is ripgrep over
`/saved/**/*.md`. Add FTS5 only once the search gap is felt, not before. Brotli, proxies,
and the exploration crawler stay parked until a concrete need appears.

Realistically 3–5 focused days of work to a trustworthy v1, with step 5 the swing factor. The
failure mode to watch is letting steps 5 and 6 pull in proxies, OCR, a Medium-mirror
reimplementation, and FTS all at once. Finish the archive, use it, then decide.
- Embed and search alongside web pages

---

## Parking Lot (revisit only when there's a concrete need)

- **Topic tagging with KeyNMF**: Revisit as enrichment layer *after* semantic search is in daily use. Only if browsing-by-topic turns out to be a real need.
- **model2vec / static embeddings**: If corpus grows past ~5k documents and embedding speed becomes a bottleneck.
- **Obsidian plugin / integration**: Only if the CLI→frontend path proves insufficient. Building an Obsidian plugin is its own project.
- **RAG with LLM**: Full question-answering over saved content. The embedding search is the retrieval half; adding an LLM for generation is straightforward once retrieval works. But search alone might be sufficient.
- **Automatic re-scraping**: Periodic refresh of pages that might have updated. Low priority — most saved content is static.
- **Bloom filters for deduplication**: Current URL dedup is fine at this scale.

---

## Discarded Routes (for reference)

### Keyword extraction with YAKE
Statistical, collection-independent, per-document. Struggled with technical terms and hyphenated compounds (e.g. "Chronos-2"). Embedding-based approaches handle these much better.

### Topic modeling with KeyNMF
Got 15 clean topics (forecasting, ML/DL, agents, MLOps, MCP, Copilot). Didn't solve the actual problem — topic labels don't help *find* a specific resource. Was solving "organize" when I needed "retrieve."

### Domain-based Obsidian graph
Grouped ~788 URLs by registered domain. Big clusters (microsoft.com, github.com) too broad; small clusters just moved the "remember 700 things" problem to "remember 300 domain names."

---

## Principles

- **2am test**: Can I understand and debug this at 2am? If not, rewrite it.
- **Build for what exists, not what might exist**: No deep exploration until depth-1 search works well. No frontend until the CLI reveals what's needed. Schema can anticipate future needs, but code paths should only exist for what's implemented.
- **Retrieval over organization**: The goal is to *find* things, not to *categorize* them. Organization is a secondary enrichment, not the core.
- **Swap later is fine**: Embedding model, database, scraper — all are replaceable. Ship something that works, iterate based on real usage.