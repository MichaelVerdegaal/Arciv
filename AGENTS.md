# Clotho

## Project Description
Clotho is a personal knowledge management system. It extracts URLs from Obsidian daily notes,
scrapes their content, and makes it searchable through semantic embeddings. The goal: find
previously saved technical resources using natural language queries instead of remembering exact
keywords or filenames.

### Architecture

1. **URL extraction** — Parse Obsidian markdown notes, extract all links, deduplicate, apply
   filtering/rewrite rules
2. **Web scraping** — Playwright (async, concurrency-controlled), HTML→Markdown via trafilatura
3. **Storage** — SQLite database (markdown content inline, HTML archived as Brotli-compressed files)

### Key Libraries

- `playwright` — async web scraping
- `trafilatura` — HTML content extraction
- `tldextract` — domain parsing (registered domain grouping)
- `loguru` — logging (one log statement per URL processed)

## Tech Stack

**Python:** 3.13 **Tools:** UV (packages), Ruff (lint/format)

## Commands

```bash
uv add <package>                 # Add dependency
uv add --group dev <package>     # Add dev dependency
uv run ruff check                # Lint
uv run ruff format               # Format code
```

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