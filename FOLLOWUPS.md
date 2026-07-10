# Follow-ups

Known limitations noted during review, deliberately not fixed in v1 (see PLAN.md scope rules):

- Editing a file leaves the previous version's chunks in the store: chunk IDs hash the chunk
  text, so changed chunks get new IDs and the old ones are never deleted. Same root cause as
  deleted-file handling, which PLAN.md already defers.
- `HEADING_RE` matches `#`-lines inside fenced code blocks, so code samples containing
  `# comments` can be misread as headings. Changing the chunking algorithm requires owner
  approval per PLAN.md.
- A single paragraph longer than the chunk target is never split; oversized chunks are truncated
  at 512 tokens by the embedder (with a logged warning).
- The model cache (`.microrag/`) and Chroma DB (`.microrag-db/`) are relative paths, so all
  commands must run from the same working directory.
- AGENTS.md still contains unfilled template placeholders (Architecture summary, Key Libraries)
  and rules copied from another project (SQLite schema, scraping pipeline).
