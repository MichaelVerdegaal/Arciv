## Clotho PoC Plan

### Input/Output
- **In:** One or more URLs via CLI
- **Out:** Markdown files in `resources/` folder, ready for Obsidian

### Steps

1. **Crawl** — `trafilatura` fetches URL, extracts as markdown
2. **Extract topic** — First non-empty line/heading, capped at ~80 chars
3. **Slugify** — Topic → filename-safe slug (e.g., `polars-lazy-evaluation.md`)
4. **Dedup** — Skip if file already exists
5. **Write file** — YAML frontmatter (url, date_saved) + topic heading + truncated content + source link
6. **Update index** — Rebuild `_index.md` with backlinks to all resource files

### File Structure
```
resources/
├── some-article-title.md
├── another-resource.md
└── _index.md              # [[backlinks]] only
```

### Dependencies
- `...` — crawling + markdown extraction
- `python-slugify` — filename generation
- `loguru` — logging

### Punt List
- Author/date extraction
- LLM summarization
- Full content (truncate to ~500 chars for now)
- PDFs, auth-required, recursive crawling

### Success Criteria
1. Run with 3 URLs → get 3 markdown files + index
2. Same URL twice → no duplicate
3. Drop `resources/` in Obsidian vault → graph shows connections