# Plan: merging MicroRag into Arciv

Goal: fold MicroRag (local semantic search over markdown) into the Arciv repo and package, while
keeping Arciv fully usable without it. Search becomes an optional extra: `uv tool install
"arciv[search]"` gets everything, plain `arciv` stays light (no chromadb/onnxruntime/numpy).

This is the step PLAN.md deferred as "FTS5 / semantic search: only once the search gap is actually
felt." The two tools already compose by pipe (`microrag query ... | arciv extract -f -`); this plan
makes that one tool.

## Why this is a good fit

- Same toolchain everywhere: Python 3.12+, uv, hatchling, Typer, loguru, ruff, pytest.
- MicroRag is small and self-contained (~1,500 lines across 7 modules) with strict internal
  boundaries (`cli` is the only wiring point), so it transplants cleanly.
- All of MicroRag's heavy dependencies (`chromadb`, `onnxruntime`, `tokenizers`,
  `huggingface-hub`, `numpy`, `chonkie`) are only needed for search — exactly the shape of an
  optional extra. Arciv's core dependency list is untouched.

## Decisions (locked 2026-07-22)

One name for the feature everywhere: **search**. The subpackage, CLI command, extra, and data
directory all use it, so nothing needs a mental mapping between "rag", "microrag", and "search".

- **D1. Code layout**: subpackage. Modules move to `arciv/search/`; the MicroRag CLI becomes
  `arciv/cli/search.py` (a Typer sub-app). One package identity; mypy/ruff cover it like the rest
  of Arciv.
- **D2. CLI surface**: `arciv search query|index|refresh|download|status|collections`. The
  `microrag` entry point is retired. Without the extra installed, `arciv search` prints a one-line
  install hint and exits with the usage code.
- **D3. Git history**: preserved. MicroRag's history is merged in via
  `git merge --allow-unrelated-histories` after a file-move commit on the MicroRag side.
- **D4. Data home**: the model + Chroma DB default to `DATA_DIR / "search"` (e.g.
  `~/.local/share/arciv/search`), overridable with `ARCIV_SEARCH_HOME`. An existing
  `MICRORAG_HOME` / `~/.microrag` keeps working (see Phase 4) so nothing re-downloads or
  re-indexes.
- **D5. Extra name**: `arciv[search]`.
- **D6. MicroRag repo**: the owner archives it. Its README gets a final note that development
  moved into Arciv; no cross-repo links in either direction.

Also settled: dependency bounds use `>=` (the lockfile pins), and auto-indexing the archive into
search is explicitly not part of this merge (see Non-goals).

## Implementation phases

Each phase leaves the repo green (`ruff check`, `pytest`, `mypy`).

### Phase 1 — import the code

1. Bring MicroRag's code in with history (D3): in a MicroRag clone, `git mv` files to their new
   paths on a branch; in Arciv, add it as a remote, fetch, and
   `git merge --allow-unrelated-histories`. `git blame`/`git log --follow` keep working.
2. Land it at the D1 layout:
   - `arciv/search/{__init__,constants,chunker,embedder,store,indexer,collections}.py`
   - `arciv/cli/search.py` (was `microrag/cli.py`)
   - `tests/search/` (was `microrag/tests/`; avoids the `test_cli.py` filename collision)
   - `evals/` (retrieval-quality suite; dev-only, not shipped — stays out of the wheel)
3. Fix imports (`microrag.` → `arciv.search.`) and drop `microrag/__main__.py`.

### Phase 2 — packaging

1. `pyproject.toml`:

   ```toml
   [project.optional-dependencies]
   search = [
       "chromadb>=1.5.9",
       "onnxruntime>=1.27.0",
       "tokenizers>=0.23.1",
       "huggingface-hub>=1.23.0",
       "numpy>=2.5.1",
       "chonkie>=1.7.0",
   ]
   ```

   MicroRag pinned these `==`; per the locked decision these become `>=` and `uv.lock` does the
   pinning.
2. Merge dev groups (pytest/ruff already shared; keep Arciv's hypothesis, pytest-cov, mypy).
3. Add the search modules to the mypy overrides list where needed (`chromadb.*`, `chonkie.*`,
   `onnxruntime.*`, `tokenizers.*` ship incomplete or no type info).
4. Ruff: MicroRag enforces `ANN`, `D` (google), `PTH`, `PLC0415` beyond Arciv's `I/B/UP`.
   Scope the stricter set to `arciv/search/**` with a per-file-ignores block; widen repo-wide
   later if wanted. `PLC0415` (no function-level imports) must be off for the import-guard
   modules below, and MicroRag's `extend-immutable-calls` for `typer.Argument`/`typer.Option`
   carries over.

### Phase 3 — optionality (the load-bearing part)

1. Nothing in `arciv/search/` may be imported at `arciv` startup. `arciv/cli/cli.py` registers
   the sub-app through a guard:

   ```python
   # arciv/cli/search.py
   try:
       import chromadb  # noqa: F401  (cheapest canary import)
       SEARCH_AVAILABLE = True
   except ImportError:
       SEARCH_AVAILABLE = False
   ```

   When unavailable, register a stub `search` command whose help still shows up in
   `arciv --help` and whose invocation prints:
   `arciv search requires the search extra: uv tool install "arciv[search]"` (exit: usage error).
2. Even when installed, heavy imports (`chromadb`, `onnxruntime`) stay inside the sub-app's
   command bodies so `arciv list` never pays their import cost. MicroRag already lazy-loads the
   embedder; keep that.
3. Wire the search sub-app into Arciv's global conventions: `-v/-q`, `--color`, `--json`,
   stdout-for-data/stderr-for-logs, and Arciv's exit-code constants (both projects already follow
   sysexits, so this is mostly deduplication).

### Phase 4 — data home (D4)

1. `settings.py` gains `SEARCH_HOME` with the resolution order: `ARCIV_SEARCH_HOME` →
   `MICRORAG_HOME` → existing `~/.microrag` (if present) → `DATA_DIR / "search"`.
2. `arciv/search/constants.py` reads paths from settings instead of its own env handling.
3. `arciv db dir` / `arciv status` mention the search home so it's discoverable.

### Phase 5 — tests, CI, evals

1. `tests/search/` gets a conftest guard: `pytest.importorskip("chromadb")` (or a marker), so the
   suite passes on a core-only environment.
2. CI runs two jobs: core (no extra, full suite minus search) and full
   (`uv sync --extra search`, everything). The core job is what proves the extra is truly
   optional.
3. Port MicroRag's `evals/` runner and keep it a dev tool (not in the wheel, not in CI-required).

### Phase 6 — docs and wind-down

1. README: add a Search section (install with the extra, the command tour, the new pipe idiom
   `arciv search query ... | arciv extract -f -`).
2. Fold the relevant parts of MicroRag's ARCHITECTURE.md into Arciv's docs; record the merge and
   the decision outcomes in PLAN.md's decision log.
3. SETUP.md: extra install instructions, `HF_TOKEN` note for the model download.
4. MicroRag repo: README updated to note development moved into Arciv (no cross-repo links);
   the owner archives the repo.

## Non-goals (for this merge)

- **Auto-indexing** — `arciv get` feeding archived markdown into the search index, or
  `arciv search` defaulting to the archive directory — is deliberately out of scope (owner call).
  It's a natural phase 2 once the merge is stable, and doing it now would couple the pipeline to
  the optional extra before the seam has settled.
- **Chroma as the document store.** Chroma remains a derived index: rebuildable from the archive
  at any time, never the only copy of anything. The archive's source of truth stays markdown +
  raw HTML on disk with SQLite tracking state. (Chroma's persistent client does sit on SQLite
  internally, but it stores text chunks keyed to embeddings — no binary blobs, no joins, no
  aggregates — so it cannot replace the archive's relational bookkeeping or file storage.)

## Risks and small print

- **Version**: Arciv is 0.1.0, MicroRag 0.3.4. The merged package continues Arciv's versioning;
  bump minor (0.2.0) when this lands.
- **Wheel contents**: verify `evals/` and `tests/` stay out of the wheel after the move
  (`hatch build` + inspect once).
- **chromadb import cost**: the canary import in the guard is at sub-app registration; if it
  measurably slows `arciv --help`, switch the guard to `importlib.util.find_spec`.
- **`refresh` roots**: `roots.json` stores absolute paths; the D4 fallback logic doesn't touch
  it, so refresh keeps working. Only a manual move of the DB dir would — same as today.
- **Two `test_cli.py` files**: solved by the `tests/search/` subdirectory; pytest needs no config
  change since `testpaths = ["tests"]` already covers it.
