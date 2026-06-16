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

1. **Indexing** (`arciv index`, `arciv/core/index/`) — Parse note files (`.md`,
   `.txt`, `.rst`), extract all links, deduplicate, apply filtering/rewrite rules, register
   pending pages. Each link
   gets a row with the URL, the full normalized filepath it was found in, and an indexed-at
   timestamp. Indexing operates on registered sources (`arciv add <dir> <name>`).
2. **Fetching** (`arciv fetch`, `arciv/core/pipeline/fetch.py` + `arciv/core/fetch/`) — Download raw
   content with patchright (async, concurrency-controlled); PDFs via direct HTTP. Writes
   `page.html` / `page.pdf` to disk, no conversion.
3. **Parsing** (`arciv parse`, `arciv/core/pipeline/parse.py` + `arciv/core/parse/`) — Validate
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
  `rules` holds the user-editable URL-processing rules applied in order during
  indexing/archiving: `id` (PK), `match_type`
  (`domain`/`host`/`starts_with`/`ends_with`/`exact`/`regex`), `pattern`, `action`
  (`skip`/`rewrite`), `replacement` (skip reason, or the rewrite target — the new
  host/prefix/suffix/whole URL/regex replacement for the matched span),
  `position` (apply order), `added_at`. A new database is seeded with default
  rules (migrated from the old hardcoded lists, including the media/image-proxy/
  IP-host plumbing skips, which now lead the list); deleting them all is honoured
  (no re-seed on reopen).
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
foundation (layered `get`, separated stages, sources) is in place; the web app phase is now
underway. PLAN.md is the live roadmap.

- The web app is built: a single FastAPI service (`arciv_api/`) imports the arciv library (it
  never shells out), reads through short-lived read-only connections, and renders its own HTML
  with Jinja2 + Datastar (BeerCSS) — there is no separate frontend runtime. It serves
  browse, page detail, domains, sources, and status, plus a `POST /archive` job flow run by a
  single in-process worker started in the app lifespan. Page markdown is rendered to HTML and
  sanitized in Python. Styling is BeerCSS (Material Design 3, dark mode) loaded from the
  jsDelivr CDN, plus a small self-hosted `static/app.css` that pins the brand colors (indigo
  `#4B0082` / thistle `#D8BFD8`) and a few app-specific bits; `datastar.js` is self-hosted.
  There is no CSS build step.

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

# Formatting requirements
Avoid the stylistic tics common to LLM output. Don't inflate importance: skip
phrases like "stands as a testament to", "plays a vital/pivotal/crucial role",
"rich tapestry", "vibrant", "underscores its significance", or claims that some
mundane detail "reflects a broader" trend. Don't tack present-participle
commentary onto sentence ends ("..., highlighting its impact", "...,
cementing its legacy"). Cut the recurring vocabulary: delve, boasts (meaning
has), showcase, foster, robust, meticulous, landscape (figurative), realm,
nestled, leverage. Don't overuse the rule of three or "not only X but Y" /
"it's not just X, it's Y" parallelism. Prefer plain verbs (wrote, not authored;
used, not utilized; has, not features). Use straight quotes and apostrophes, no
em-dashes, no curly quotes. Don't end with a "Conclusion" or "In summary"
restatement, and don't add a "Despite its challenges..." wrap-up. Don't pad with
hedges ("it's important to note", "it's worth mentioning"). Don't add knowledge-
cutoff or "based on available information" disclaimers. Don't over-bold, don't
turn every list item into "**Bolded label**: explanation", and don't put every
section in Title Case. Match length and formality to the task; default to fewer
words, concrete specifics over generic praise, and a real voice over a neutral
encyclopedic hum.

For generated code: don't docstring or comment trivial functions; comment only
where logic is non-obvious. Use specific, contextual names, not generic
data/result/temp/process_data. Add error handling only where a failure can
actually occur; never wrap everything in broad try/except that swallows
exceptions. Don't over-engineer: no repository patterns, abstract base classes,
factories, or dependency injection for problems that don't need them. Prefer
stdlib over pulling a library per sub-problem; don't grow the dependency list
unnecessarily. Clean up after iteration: remove dead code, unused functions, and
orphaned imports rather than leaving them. Calibrate structure to the actual
requirement instead of applying "best practice" boilerplate by default.
