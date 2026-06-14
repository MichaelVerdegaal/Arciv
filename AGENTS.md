# Arciv

## Project Description
Arciv is a personal archival tool for reading material — blog posts, research papers,
documentation. Not books, not videos. It extracts URLs from markdown files (or takes them
directly on the CLI), scrapes their content, and archives it as markdown on disk. The goal: a
trustworthy archive of everything worth reading again, retrievable years later. Retrieval today
is the inspection commands (`arciv list`, `arciv path`) plus ripgrep over the archive; a web
UI for browsing it is the next step (see PLAN.md).

The project splits into three isolated parts: the **CLI tool** (this package — all archival
logic, installable as a uv tool, not containerized), and a future **backend** and **frontend**
which each get a dedicated container.

### Architecture

Three stages, no writeback into the notes. Each stage has a dedicated CLI command;
`arciv get` runs all three in order on a URL, a file (`--file`), or a directory (`--dir`).

1. **Indexing** (`arciv index`, `arciv/pipeline/index.py`) — Parse note files (`.md`,
   `.txt`, `.rst`), extract all links, deduplicate, apply filtering/rewrite rules, register
   pending pages. Each link
   gets a row with the URL, the full normalized filepath it was found in, and an indexed-at
   timestamp. Indexing operates on registered sources (`arciv add <dir> <name>`).
2. **Fetching** (`arciv fetch`, `arciv/pipeline/fetch.py` + `arciv/scrape/`) — Download raw
   content with patchright (async, concurrency-controlled); PDFs via direct HTTP. Writes
   `page.html` / `page.pdf` to disk, no conversion.
3. **Parsing** (`arciv parse`, `arciv/pipeline/parse.py` + `arciv/convert/`) — Validate
   fetched HTML, convert to markdown via trafilatura (HTML) or liteparse (PDF), write
   `page.md` next to the raw file, fill in title/author/word count.

### Storage Contract

The planned backend/frontend read the data directory directly, so treat this layout as a
public interface — changes to it ripple beyond the Python code:

- `<data dir>/arciv.db` — SQLite (WAL mode, foreign keys ON). `pages` holds one row per URL:
  `url` (PK, normalized), `original_url`, `domain`, `slug` (UNIQUE; names the
  on-disk `saved/<slug>/` folder), `content_type` (`html`/`pdf`,
  set at fetch), `title`, `author`, `word_count`, `fail_reason`, `added_at`, `fetched_at`,
  `parsed_at`. Pipeline state is carried by the timestamps: pending (no `fetched_at`),
  fetched (`fetched_at` set), parsed (`parsed_at` set); `fail_reason` marks a failure at
  either stage. `links` holds one row per indexed link: `url`, `file_path` (full normalized
  path), `source_name` (NULL for ad-hoc files; cleared when a source is removed),
  `indexed_at`. `sources` holds registered directories: `name` (PK), `path`, `added_at`.
- `<data dir>/saved/<slug>/` — one folder per page: `page.html` (raw fetch) or `page.pdf`, plus
  `page.md` once parsed. Slug format is `<domain>-<hash8>`, sanitized to be a safe directory
  name on Linux and Windows.
- The data root defaults to the OS user data dir via platformdirs (Linux:
  `~/.local/share/arciv`, Windows: `%LOCALAPPDATA%\arciv`) and is relocatable via
  `ARCIV_DATA_DIR` (e.g. `ARCIV_DATA_DIR=data` in `.env` when developing from a clone).

### Key Libraries

- `patchright` — async web scraping (undetected Playwright fork)
- `trafilatura` — HTML content extraction
- `liteparse` — PDF text extraction
- `tldextract` — domain parsing (registered domain grouping)
- `typer` — CLI framework
- `loguru` — logging (one log statement per URL processed)
- `platformdirs` — OS-appropriate default data directory

## Tech Stack

**Python:** 3.12+ (CI runs the test suite on 3.12, 3.13, and 3.14; `.python-version` pins
the development default) **Tools:** UV (packages), Ruff (lint/format), pytest (tests)

## Commands

```bash
uv add <package>                 # Add dependency
uv add --group dev <package>     # Add dev dependency
uv run ruff check                # Lint
uv run ruff format               # Format code
uv run pytest                    # Run tests (with coverage)
uv run arciv --help             # Run the CLI from the repo
uv tool install .                # Install the CLI as a global tool
```

## Current Direction

The scope is settled: Arciv is the main archival tool for all reading material. The CLI
foundation (layered `get`, separated stages, sources) is in place; the backend + frontend
phase is now underway. PLAN.md is the live roadmap.

- The read path is built: a FastAPI backend (`arciv_api/`) imports the arciv library (it
  never shells out) and serves the archive over HTTP through read-only database connections;
  an Astro SSR frontend (`frontend/`) consumes that API and never opens the database or
  `saved/` directly. The archive/write flow (the background fetch+parse worker) is not built
  yet — build for what exists.

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
