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

## Open decisions

Each has a recommendation the rest of this plan assumes. Overruling any of them changes the
plan mechanically, not structurally.

### D1. Code layout — recommended: `arciv/rag/` subpackage

Move `chunker.py`, `embedder.py`, `store.py`, `indexer.py`, `collections.py`, `constants.py`
into `arciv/rag/`; the MicroRag CLI becomes `arciv/cli/search.py` (a Typer sub-app). One package
identity, and mypy/ruff cover the code like the rest of Arciv.

Alternative: keep a top-level `microrag/` package shipped from the Arciv repo (wheel includes
both packages). Less churn and preserves `import microrag`, but it's cohabitation, not a merge.

### D2. CLI surface — recommended: `arciv search` sub-app, retire the `microrag` command

`arciv search query|index|refresh|download|status|collections`. When the extra isn't installed,
`arciv search ...` prints a one-line install hint and exits with the usage code. The pipe idiom
becomes `arciv search query ... | arciv extract -f -`.

Alternative A: also keep a `microrag` console script pointing at the same code, for existing
shell habits. Cheap to do, but two names for one tool forever.
Alternative B: keep only the separate `microrag` command. Weakest integration; not recommended.

### D3. Git history — recommended: preserve it

Bring MicroRag in with its history: in a MicroRag clone, `git mv` files to their new paths on a
branch; in Arciv, `git remote add microrag ... && git fetch` and `git merge --allow-unrelated-histories`.
`git blame`/`git log --follow` keep working on the moved files. Cost: one slightly unusual merge
commit.

Alternative: plain copy in one commit whose message records the source repo and version
(microrag v0.3.4, commit sha). Cleaner history; the archived MicroRag repo stays the record.

### D4. Search data home — recommended: move under Arciv's data dir, honor the old one

Default the model + Chroma DB to `DATA_DIR / "rag"` (e.g. `~/.local/share/arciv/rag`), overridable
with `ARCIV_RAG_HOME`. Compatibility: if `MICRORAG_HOME` is set, or `~/.microrag` exists while the
new location doesn't, use the old location and log a hint once — nothing re-downloads or
re-indexes.

Alternative: keep `~/.microrag` as-is. Zero migration surface, but search data lives outside
`arciv db dir` forever.

### D5. Extra name — recommended: `search`

`arciv[search]` matches the user-facing verb (`arciv search`). Alternative: `rag` (matches the
subpackage name) or `semantic`.

### D6. Fate of the MicroRag repo — recommended: archive after the merge lands

Final release note in its README pointing at Arciv, then GitHub-archive it. Its history is either
merged into Arciv (D3 recommended) or referenced by the import commit.

## Implementation phases

Each phase leaves the repo green (`ruff check`, `pytest`, `mypy`).

### Phase 1 — import the code

1. Bring MicroRag's code in per D3 (history-preserving merge or copy).
2. Land it at the D1 layout:
   - `arciv/rag/{__init__,constants,chunker,embedder,store,indexer,collections}.py`
   - `arciv/cli/search.py` (was `microrag/cli.py`)
   - `tests/rag/` (was `microrag/tests/`; avoids the `test_cli.py` filename collision)
   - `evals/` (retrieval-quality suite; dev-only, not shipped — stays out of the wheel)
3. Fix imports (`microrag.` → `arciv.rag.`) and drop `microrag/__main__.py`.

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

   MicroRag pins these `==`; Arciv's convention is `>=`. Adopt `>=` and let `uv.lock` do the
   pinning, unless a known incompatibility argues for keeping a pin.
2. Merge dev groups (pytest/ruff already shared; keep Arciv's hypothesis, pytest-cov, mypy).
3. Add the search modules to the mypy overrides list where needed (`chromadb.*`, `chonkie.*`,
   `onnxruntime.*`, `tokenizers.*` ship incomplete or no type info).
4. Ruff: MicroRag enforces `ANN`, `D` (google), `PTH`, `PLC0415` beyond Arciv's `I/B/UP`.
   Decide once: adopt the stricter set repo-wide, or scope it to `arciv/rag/**` with a
   per-file-ignores block. Recommended: scope it, widen later if wanted. Note `PLC0415`
   (no function-level imports) must be off for the import-guard modules below, and keep
   MicroRag's `extend-immutable-calls` for `typer.Argument`/`typer.Option`.

### Phase 3 — optionality (the load-bearing part)

1. Nothing in `arciv/rag/` may be imported at `arciv` startup. `arciv/cli/cli.py` registers the
   sub-app through a guard:

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

1. `settings.py` gains `RAG_HOME` with the resolution order: `ARCIV_RAG_HOME` →
   `MICRORAG_HOME` → existing `~/.microrag` (if present) → `DATA_DIR / "rag"`.
2. `arciv/rag/constants.py` reads paths from settings instead of its own env handling.
3. `arciv db dir` / `arciv status` mention the search home so it's discoverable.

### Phase 5 — tests, CI, evals

1. `tests/rag/` gets a conftest guard: `pytest.importorskip("chromadb")` (or a marker), so the
   suite passes on a core-only environment.
2. CI runs two jobs: core (`uv sync --no-extra`, full suite minus rag) and full
   (`uv sync --extra search`, everything). The core job is what proves the extra is truly optional.
3. Port MicroRag's `evals/` runner and keep it a dev tool (not in the wheel, not in CI-required).

### Phase 6 — docs and wind-down

1. README: add a Search section (install with the extra, the command tour, the new pipe idiom).
2. Fold the relevant parts of MicroRag's ARCHITECTURE.md into Arciv's docs; record the merge and
   the D1–D6 outcomes in PLAN.md's decision log.
3. SETUP.md: extra install instructions, `HF_TOKEN` note for the model download.
4. MicroRag repo: final README pointing here, then archive (D6).

## Non-goals (for this merge)

Deeper integration — e.g. `arciv get` auto-indexing archived markdown into the search index, or
`arciv search` defaulting to the archive directory — is deliberately out of scope. It's a natural
phase 2 once the merge is stable, and doing it now would couple the pipeline to the optional extra
before the seam has settled.

## Risks and small print

- **Version**: Arciv is 0.1.0, MicroRag 0.3.4. The merged package continues Arciv's versioning;
  bump minor (0.2.0) when this lands.
- **Wheel contents**: verify `evals/` and `tests/` stay out of the wheel after the move
  (`hatch build` + inspect once).
- **chromadb import cost**: the canary import in the guard is at sub-app registration; if it
  measurably slows `arciv --help`, switch the guard to `importlib.util.find_spec`.
- **`refresh` roots**: `roots.json` stores absolute paths; moving the data home per D4's fallback
  logic doesn't touch it, so refresh keeps working. Only a manual move of the DB dir would — same
  as today.
- **Two `test_cli.py` files**: solved by the `tests/rag/` subdirectory; pytest needs no config
  change since `testpaths = ["tests"]` already covers it.
