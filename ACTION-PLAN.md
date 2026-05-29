# Clotho: Action Plan v2

## The Problem

I write daily notes in Obsidian and accumulate links to technical resources — documentation, blog posts, papers, repos. Over time I can't find them again. Two failure modes:

1. **"I know I saved something about X but can't find it"** — Obsidian's keyword search requires remembering the exact words I wrote, not what the linked content was *about*.
2. **"I want to see what I have on topic X"** — No way to get a topical overview across hundreds of links scattered through daily notes.

Root cause: **my links have no semantic context in the vault.** The URL is opaque, the daily note only gives me a date, and search can only match words I happened to write — not the content behind the link.

Key insight from discarded routes (YAKE, KeyNMF topic modeling, domain-based Obsidian graph): I was optimizing *organization* as a proxy for *retrieval*. I don't need to organize my links — I need to **search** them semantically.

---

## Current State (PoC Complete)

### What exists and works

- **Scraping pipeline**: Playwright-based async scraper with concurrency control, URL normalization (GitHub rewrites, Medium→Freedium proxy), deduplication, content validation
- **Content conversion**: HTML→Markdown via trafilatura, ~506 valid conversions from ~650 scraped pages
- **Storage**: SQLite database with page metadata, markdown content, Brotli-compressed HTML archives (175MB → 22MB)
- **Embeddings**: Corpus embedded with pplx-embed (worked but GPU was struggling)
- **Semantic search CLI**: Vibecoded but functional — brute-force cosine similarity over stored embeddings, returns top-k results with URL, title, and snippet. Results were actually good.

### What needs replacing

- **SQLite layer**: Vibecoded, verbose, barely understandable. Fails the 2am test.
- **Embedding model**: pplx-embed too heavy for available GPU. Need a model that fits hardware constraints.
- **Scraper framework**: Custom scraper is slapdash. Scrapling covers the same ground with better robustness.

---

## The Plan

### Step 1: Swap embedding model ⬅️ DO FIRST

The current pplx-embed model is too heavy for the available GPU. Replace with a model that fits hardware constraints while maintaining retrieval quality.

**Candidates to evaluate:**

| Model | Params | Dims | Notes |
|---|---|---|---|
| `BAAI/bge-small-en-v1.5` | 33M | 384 | Strong retrieval performance for size, runs on CPU comfortably |
| `sentence-transformers/all-MiniLM-L6-v2` | 22M | 384 | Tried before for topic modeling, proven baseline |
| `sentence-transformers/static-retrieval-mrl-en-v1` | ~30M | 768 | Static model, extremely fast even on CPU, no transformer inference |
| `Qwen/Qwen3-Embedding-0.6B` | 600M | 1024 | Tested before, good quality but check if GPU can handle it |

**Evaluation approach:**

- Pick 10-15 queries that represent real retrieval needs ("kubernetes networking", "darts forecasting covariates", "MCP protocol specification", etc.)
- Embed corpus with each candidate
- Compare top-5 results qualitatively — does the right document show up?
- Measure embedding time and query latency
- Pick the model that gives good-enough results on reasonable hardware

**Decision criteria:** Good retrieval quality on technical content > raw benchmark scores. Must run locally without GPU pain. Can always swap later — the embedding column is just a blob.

**Estimated effort:** Half a day to a day.

### Step 2: Migrate scraping to Scrapling

Replace the custom Playwright scraper with [Scrapling](https://github.com/D4Vinci/Scrapling).

**Migration checklist:**

- [ ] Verify Scrapling handles async operation / concurrency control
- [ ] Port URL normalization rules (GitHub raw content rewrites, Medium→Freedium proxy)
- [ ] Port domain blacklist / skip rules
- [ ] Port content validation (min word count, cookie banner filtering)
- [ ] Verify trafilatura integration still works downstream (Scrapling fetches HTML → trafilatura extracts content)
- [ ] Test against known-tricky domains from the existing corpus
- [ ] Ensure deduplication logic (URL normalization + seen-URL tracking) still works

**What to keep:** trafilatura for HTML→Markdown conversion. The scraper fetches raw HTML; trafilatura does the content extraction. These are separate concerns.

**Estimated effort:** 1-2 days depending on how many custom rules need porting.

### Step 3: Database migration — graph DB with exploration model

Replace the vibecoded SQLite layer with a graph database. The current SQLite code is verbose, barely understandable, and fails the 2am test.

**Why a graph DB:**

- Documents naturally link to other documents — graph edges express this directly
- The exploration model (see below) is fundamentally about traversing a link graph
- A `type` field + graph edges replaces the need for class hierarchies entirely
- Graph queries like "find all unexplored documents linked from this note" are first-class operations

**The exploration model:**

The core idea is exploratory crawling with provenance tracking. Every piece of content is a single `Document` node, differentiated by type and depth:

1. **Start by inventorying notes** — each Obsidian daily note becomes a Document at depth 0
2. **Extract references** — URLs, internal links, paper references found in a document become new Document nodes, connected via edges, at depth 1
3. **Scrape/fetch** — each Document tracks whether its text content has been retrieved
4. **Explore** — each Document tracks whether its own outbound references have been discovered and created as nodes. If not, you can selectively explore further, creating depth 2+ nodes
5. **Repeat** — this is a targeted crawler. You control how deep to go, and can explore selectively rather than blindly spidering everything

This replaces the Source → Document → LinkDocument/PaperDocument hierarchy with a single node type and graph relationships. Much simpler, much more flexible.

**Document node schema:**

```
Document {
    url: string (unique)
    original_url: string | null       # pre-normalization URL
    domain: string | null             # tldextract registered domain

    type: enum                        # how this document was discovered:
                                      #   "source"    — original Obsidian note
                                      #   "url"       — web link found in a document
                                      #   "internal"  — Obsidian internal link
                                      #   "paper"     — arXiv/research paper reference

    depth: int                        # 0 = original note, 1 = directly linked, 2+ = deeper exploration

    # Content state
    fetch_status: enum                # "pending" | "fetched" | "failed" | "too_short" | "cloudflare"
    fail_reason: string | null
    text: string | null               # extracted markdown content (null if not yet fetched)
    html_archive_path: string | null  # path to .html.br file

    # Exploration state
    explored: bool                    # have all outbound references been discovered as nodes?

    # Metadata
    title: string | null
    author: string | null
    word_count: int | null
    embedding: vector | null
    scraped_at: datetime | null
}
```

**Graph edges:**

```
(Document)--[LINKS_TO]-->(Document)     # web URL found in content
(Document)--[REFERENCES]-->(Document)   # paper/arXiv citation
(Document)--[INTERNAL_LINK]-->(Document) # Obsidian [[wikilink]]
```

> **Note on type vs edges:** The `type` field describes *what* the document is (a note, a web page, a paper). The edges describe *how* documents relate to each other. Both are useful — `type` is easy to filter on, edges capture the relationship graph.

**DB candidates:**

| | SurrealDB | HelixDB |
|---|---|---|
| **Embedded mode** | Yes — runs in-process via Python SDK, no server needed | No — requires running as a service |
| **Vector search** | Built-in vector fields + KNN search | Not built-in |
| **Graph queries** | SurrealQL — SQL-like, works but verbose for deep traversals | Cleaner, more intuitive graph traversal syntax |
| **Python SDK** | Available, maturing | Available |
| **Maturity** | More established, larger community | Newer, smaller community |

Decision deferred to when step 3 starts. Both work. SurrealDB is more pragmatic (embedded + vector search in one). HelixDB has nicer graph ergonomics if you're willing to run a service and handle vector search separately.

**Scope for step 3 (initial implementation):**

- Migrate existing scraped data into graph DB
- Only depth 0 (notes) and depth 1 (URLs found in notes) — no deeper exploration yet
- Rewrite search CLI against new storage layer
- Exploration system is a future extension, not step 3 deliverable

**Estimated effort:** 2-3 days (including rewriting the search CLI against the new storage layer).

### Step 4: Build local frontend with Astro

Once the CLI has been used enough to understand what the UX actually needs, build a proper search interface.

**Why Astro:**

- Lightweight, doesn't force a specific JS framework
- Can start with mostly static pages + islands of interactivity
- Good fit for a local tool that's primarily about displaying search results

**Minimum viable frontend:**

- Search bar → results list (URL, title, domain, snippet, similarity score)
- Click-through to full markdown content
- Filter by domain, status, date range
- Basic stats dashboard (corpus size, domain distribution, recent additions)

**Backend:** Simple Python API (FastAPI or similar) wrapping the same search logic as the CLI.

**Prerequisite:** Use the CLI daily for a few weeks first. Note what's annoying, what's missing, what workflows emerge. Build the frontend to solve observed problems, not imagined ones.

**Estimated effort:** 3-5 days for MVP (this is a real frontend project, don't underestimate it).

### Step 5: PDF / arXiv paper ingestion (future)

Low priority. Build this once steps 1-4 are stable and in daily use.

**Scope when ready:**

- Detect arXiv links during URL extraction (already partially done)
- Download PDFs from arXiv
- Extract text from PDF (pymupdf or similar)
- Store as a Document node with `type: "paper"` — no special subclass needed
- Optionally extend Document schema with paper-specific metadata (arxiv_id, abstract, authors list) when the need is concrete
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