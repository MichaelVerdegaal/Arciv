# Clotho

## Project Description
Clotho is a personal archival tool for reading material — blog posts, research papers,
documentation. Not books, not videos. It extracts URLs from Obsidian daily notes (or takes them
directly on the CLI), scrapes their content, and archives it as markdown on disk. The goal: a
trustworthy archive of everything worth reading again, retrievable years later. Retrieval today
is ripgrep over the archive; a web UI for browsing it is the next step (see PLAN.md).

### Architecture

Three stages, no writeback into the notes:

1. **Indexing** — Parse Obsidian markdown notes, extract all links, deduplicate, apply
   filtering/rewrite rules, register in the database
2. **Fetching** — Download pages with patchright (async, concurrency-controlled); PDFs via
   direct HTTP
3. **Parsing** — Validate HTML, convert to markdown via trafilatura, archive to
   `data/saved/<slug>/page.html` + `page.md`; SQLite holds pointers and fetch state only

### Storage Contract

The planned web UI reads the data directory directly, so treat this layout as a public
interface — changes to it ripple beyond the Python code:

- `data/clotho.db` — SQLite (WAL mode). `pages` holds one row per URL: `url` (PK, normalized),
  `original_url`, `domain`, `slug`, `fetched` (0/1), `fail_reason`, `title`, `author`,
  `word_count`, `scraped_at`. `page_sources` maps `url` ↔ `note_name`.
- `data/saved/<slug>/` — one folder per page: `page.html` (raw fetch) + `page.md` (parsed
  markdown), or `page.pdf` + `page.md` for PDFs. Slug format is `<domain>-<hash8>`.
- A missing `page.md` for a `fetched=1` row means the parse stage needs a re-run.
- The data root is relocatable via `CLOTHO_DATA_DIR` (defaults to `data/` in the repo).

### Key Libraries

- `patchright` — async web scraping (undetected Playwright fork)
- `trafilatura` — HTML content extraction
- `liteparse` — PDF text extraction
- `tldextract` — domain parsing (registered domain grouping)
- `click` — CLI framework
- `loguru` — logging (one log statement per URL processed)

## Tech Stack

**Python:** 3.13 **Tools:** UV (packages), Ruff (lint/format), pytest (tests), Docker (runtime)

## Commands

```bash
uv add <package>                 # Add dependency
uv add --group dev <package>     # Add dev dependency
uv run ruff check                # Lint
uv run ruff format               # Format code
uv run pytest                    # Run tests (with coverage)
docker compose build             # Build the CLI image
docker compose run --rm clotho   # Run the CLI in a container
```

## Current Direction

The scope is settled: Clotho is the main archival tool for all reading material. Fetching and
parsing work well; the user experience around viewing the archive is what's being built next.
PLAN.md is the live roadmap. Two standing constraints for that work:

- A web UI under `frontend/` (likely Astro, reading the data directory at build time) is
  planned but **not designed yet — do not scaffold any frontend code** until the page views
  are decided.
- "Collections" (Pinchflat-style libraries grouping pages) will need new tables. Schema
  changes are ask-first; sketch designs in PLAN.md instead of implementing.

## Context

This is a solo project — no other developers read or maintain this code. That means:

- No one will explain what "clever" code does when you've forgotten. Write for the version of
  yourself 6 months from now.
- No PR reviews catch mistakes. Lean on type hints, explicit naming, and logging to compensate.
- Refactoring is cheap (no coordination cost), but debugging is expensive (no one to ask).

## Coding Principles

**Maintainability over elegance.** If it takes more than 10 seconds to understand what a line does,
rewrite it. "Clever" is not a compliment.

**Abstractions must earn their keep.** Every new class, pattern, or indirection must justify its
existence with a concrete benefit. "It's more elegant" is not justification.

**Debuggability is a feature.** When something breaks, can you figure out why from the error message
and a stack trace? Can you inspect intermediate state? If not, add logging or simplify the control
flow.

**Prevent, don't post-process.** Fix data quality problems at the source (e.g. configure trafilatura
to exclude code blocks) rather than writing complex cleanup logic downstream.

**Boring and correct beats clever and fragile.** The best solution is the one that obviously works,
not the one that impressively almost works.

## Code Standards

✅ **Always do:**

- Type hint all function parameters and return types. Prefer builtin types (`list`, `dict`) over
  `typing` module types (`List`, `Dict`).
- Use Google docstring style.
- Raise specific exceptions with context.
- Put regex patterns in constants with the `_RE` suffix (e.g. `DATE_RE`).
- When adding imports in `__init__.py`, add to `__all__` as well.
- Use relative imports within the same module.
- Use `pathlib` over `os` for file paths.

⚠️ **Ask first:**

- Adding dependencies beyond core stack
- Changing the SQLite schema
- Modifying URL processing rules or rewriters
- Changing scraping/conversion pipeline flow

🚫 **Never do:**

- Skip type hints on functions
- Hardcode file paths
- Use lazy imports inside functions
- Add `*args` / `**kwargs` without a specific need
- Use premature abstraction, design patterns for their own sake, or metaprogramming where a simple
  function would do