# Clotho: Action Plan & Direction

## The Problem

I write daily notes in Obsidian and accumulate a lot of links to technical resources — documentation, blog posts, papers, repos. Over time I can't find them again. Two specific failure modes:

1. **"I know I saved something about X but can't find it"** — Obsidian's keyword search is too primitive. I'd need to remember the exact words I wrote next to the link, not what the linked content was *about*.
2. **"I want to see what I have on topic X"** — Before starting new research, I want to know what I've already collected. There's no way to get a topical overview across hundreds of links scattered through daily notes.

The root cause: **my links have no semantic context in the vault.** The URL is opaque, the daily note only gives me a date, and search can only match words I happened to write — not the content behind the link.

## What I've Built So Far

### Scraping pipeline (keep, this is the real asset)

- Playwright-based async scraper with concurrency control (semaphores)
- URL processing: skip rules, domain rewriters (GitHub normalization, Medium→Freedium proxy), deduplication
- HTML→Markdown conversion via trafilatura (replaced html_to_markdown, much cleaner)
- Content validation (min word count, filtering out cookie banners / landing pages)
- ~650 HTML files scraped, ~506 valid markdown conversions

### URL extraction & grouping (keep the extraction, pivot the grouping)

- Extract all links from Obsidian daily notes
- Deduplication, URL rule filtering
- tldextract for domain grouping — functional but the grouping itself wasn't useful (see discarded routes)

### Embedding & topic modeling knowledge (reusable experience)

- Hands-on experience with sentence-transformers, KeyNMF (turftopic), CountVectorizer tuning
- Tested multiple embedding models: paraphrase-MiniLM-L6-v2, EmbeddingGemma, Qwen3
- Understand the difference between keyword extraction (per-doc) vs topic modeling (corpus-level)
- Know how to tune CountVectorizer params (min_df, max_df, ngram_range) for clean topic separation

## Discarded Routes

### Keyword extraction with YAKE

YAKE is statistical and collection-independent — works per-document without embeddings. Struggled with technical terms and hyphenated compounds (e.g. "Chronos-2"). Embedding-based approaches handle these much better. Not worth pursuing for my domain-heavy technical content.

### Topic modeling with KeyNMF

Worked surprisingly well — got 15 clean topics covering forecasting, ML/DL, agents, MLOps, MCP, Copilot ecosystems. But it didn't solve the actual problem. Topic labels on links don't help me *find* a specific resource. It was a fascinating detour that taught me a lot about embeddings, NMF decomposition, and vectorizer tuning, but it was solving "organize" when I needed "retrieve."

### Domain-based Obsidian graph

Grouped ~788 URLs by registered domain using tldextract, created a 3-level note hierarchy (index → domain notes → page notes) for Obsidian's graph viewer. Result: big clusters (microsoft.com, github.com) were too broad to be useful — microsoft.com covers everything from AKS to Fabric to GenAI. Small clusters (single-page domains) just moved the "remember 700 things" problem to "remember 300 domain names." Graph looked cool, wasn't useful.

### Key takeaway from all discarded routes

I was optimizing *organization* as a proxy for *retrieval*. I don't need to organize my links — I need to **search** them semantically.

## The Plan

### Step 1: SQLite migration (do first)

Migrate the scraping pipeline from file-based storage to a single SQLite database. This is the foundation everything else builds on.

**Schema (`pages` table):**

| Column | Type | Notes |
|---|---|---|
| `url` | TEXT PRIMARY KEY | The processed/normalized URL |
| `original_url` | TEXT | Pre-normalization URL (before GitHub rewrites etc.) |
| `source_notes` | TEXT | JSON list of daily note filenames that referenced this URL |
| `domain` | TEXT | tldextract registered domain |
| `status` | TEXT | `pending`, `scraped`, `failed`, `too_short`, `cloudflare` |
| `fail_reason` | TEXT | Nullable |
| `md_content` | TEXT | Extracted markdown content |
| `html_path` | TEXT | Path to compressed .html.br file |
| `title` | TEXT | HTML `<title>` |
| `author` | TEXT | If extractable |
| `word_count` | INTEGER | For filtering |
| `scraped_at` | TEXT | ISO timestamp |
| `embedding` | BLOB | Added in step 3, nullable for now |

**HTML storage:** Keep as files but compress with Brotli (quality=6). Reduced 175MB → 22MB. This is archival — only touched when redoing conversion.

**Markdown storage:** Inline in SQLite. 7MB total, this is what gets searched and embedded.

**Migration tasks:**

- Create the schema
- Write an import script that reads existing scraped files and populates the database
- Refactor `Scraper` class to write to DB instead of file paths
- Add `source_notes` tracking (which daily note contained the URL)
- Add metadata extraction during scrape (title, author from trafilatura)
- For script, if refetch=False, but reclean=True, load compressed HTML from disk, decompress with brotli and then follow normal process again

### Step 2: Embed the corpus

Embed all scraped markdown documents using **Qwen3-Embedding-0.6B** (known good, tested before).

- Store embeddings as blobs in the `embedding` column of the same `pages` table
- At ~800 docs × 1024-dim float32, total embedding storage is ~3MB — trivial
- No vector database needed at this scale

### Step 3: Build semantic search CLI

The minimum viable product: a CLI that takes a natural language query and returns the most relevant saved URLs.

```
python search.py "kubernetes networking" --top 5
```

**Implementation (dead simple at this scale):**

- Load all embeddings from SQLite into a numpy array (once, on startup)
- Encode the query with the same Qwen3 model
- Cosine similarity, return top-k
- Display: URL, title, domain, snippet from md_content, source notes

No FAISS, no ChromaDB, no ANN index. Brute-force cosine similarity over 800 vectors is <10ms. Add complexity only when the corpus grows past ~50k documents.

### Step 4: Topic tagging (optional, revisit later)

This is where KeyNMF comes back — not as the primary organization, but as a secondary enrichment layer.

- Run topic modeling over the embedded corpus
- Add a `topic` column to the `pages` table
- Enables browsing by topic: `python search.py --topic forecasting --list`
- Could also feed back into Obsidian notes if desired

Not a priority. Steps 1-3 solve the core problem. Only do this if browsing-by-topic turns out to be a real need after using semantic search for a while.

## Future Considerations (parking lot)

- **model2vec / static embeddings**: For faster embedding if corpus grows significantly. Qwen3 is fine for now.
- **SurrealDB**: Interesting for graph queries ("which domains appear together most frequently") but SQLite covers current needs. Revisit if relational queries become limiting.
- **Obsidian integration**: Could build an Obsidian plugin or local API that searches the SQLite DB from within Obsidian. Only worth it if the CLI becomes a daily habit first.
- **Automatic re-scraping**: Periodic refresh of pages that might have updated. Low priority — most saved content is static.
- **RAG with LLM**: Full question-answering over saved content. The embedding search is the retrieval half; adding an LLM for generation is straightforward once retrieval works well. But search alone might be sufficient.