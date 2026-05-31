# Plan

Four changes, tackled in order. Each is independently committable.

## 1. Run the browser headless

**Problem:** The scraper launches Chrome with `headless=False`, so a visible browser window pops up
on every run — annoying during normal use.

**Fix:** Add a `headless` flag to `Scraper` (default `True`) and pass it to both the sync and async
`launch_persistent_context` calls.

**Tradeoff:** patchright (the undetected Playwright fork) is slightly more detectable in headless
mode, so a few more pages may hit bot-challenge block pages. The flag makes it trivial to flip back
to `headless=False` when scraping a stubborn site.

## 2. Improve scraping speed

The async batch is slower than expected. Two bottlenecks:

- **`networkidle` wait (5s) held inside the semaphore.** Pages with ads, analytics, or websockets
  never go idle, so every such page burns the full 5s while occupying a concurrency slot. Reduce the
  budget to 3s — enough for SPAs to render, since images/CSS/fonts are already blocked.
- **Low concurrency (5).** Bump the default to 8. Combined with headless mode (lower per-page
  overhead), this raises throughput without hammering hosts.

## 3. Testing suite (pytest + pytest-cov + hypothesis)

Add a `dev` dependency group with `pytest`, `pytest-cov`, and `hypothesis`. Configure pytest +
coverage in `pyproject.toml`. Tests target the pure, deterministic core (no browser, no network):

- `tests/test_url_processor.py` — skip/rewrite/passthrough logic, slug/hash format, PDF + raw-text
  detection. Hypothesis for invariants (slug shape, rewrite idempotency).
- `tests/test_validate.py` — block-page detection and size guards.
- `tests/test_database.py` — CRUD, source mapping, orphan pruning against a temp SQLite file.

## 4. Tiny Astro frontend

A minimal Astro site under `frontend/` that reads `data/clotho.db` at build time (via
`better-sqlite3`) and renders the archive: one searchable, filterable list of archived pages (title,
domain, word count, link to the original URL). No backend server — static output generated from the
database.
