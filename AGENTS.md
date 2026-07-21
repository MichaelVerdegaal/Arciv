# AGENTS.md

Instructions for coding agents working on MicroRAG. Start here, then follow the links below for
detail rather than expecting everything on this page.

- Project overview and CLI behavior: [README.md](README.md)
- Development environment, tests, evals: [DEVELOPMENT.md](DEVELOPMENT.md)
- How the code fits together: [ARCHITECTURE.md](ARCHITECTURE.md)
- Locked decisions, scope, and long-term planning: [PLAN.md](PLAN.md)
- Writing style for prose and code: see [Writing style](#writing-style) below

[PLAN.md](PLAN.md) is the source of truth. When it and your own judgement conflict, it wins; when
something isn't covered there, ask the owner before deciding.

## Hard constraints (never violate)

- No network calls at runtime. The only permitted network access is the one-time download of model
  files from Hugging Face, performed by the explicit `download` command.
- No embedding APIs, no LLM APIs, no telemetry. Chroma's anonymized telemetry must be disabled
  (`anonymized_telemetry=False` in client settings).
- No `torch`, no `sentence-transformers`, no CUDA/GPU dependencies. Inference runs on `onnxruntime`
  with `CPUExecutionProvider` only.
- Dependencies are limited to the whitelist in `pyproject.toml`. Adding anything else requires
  explicit owner approval first.

## Verification

Before committing, run the full gate and fix all failures:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -x -q --tb=short
```

Ruff enforces the mechanical standards (type hints, Google docstring style, `pathlib` over `os`,
top-level imports, builtin generics); see `[tool.ruff.lint]` in `pyproject.toml`. After touching
chunking constants or the embedder, also run the retrieval evals
(see [DEVELOPMENT.md](DEVELOPMENT.md#retrieval-quality-evaluation)).

## Code standards

ALWAYS:
- Raise specific exceptions with context.
- Put regex patterns in constants with the `_RE` suffix (e.g. `DATE_RE`).
- When adding imports in `__init__.py`, add to `__all__` as well.
- Use relative imports within the same module.

NEVER:
- Hardcode file paths.
- Add `*args` / `**kwargs` without a specific need.
- Use premature abstraction, design patterns for their own sake, or metaprogramming where a simple
  function would do.

ASK THE OWNER FIRST before:
- Adding any dependency beyond the whitelist in `pyproject.toml`.
- Changing anything in [PLAN.md](PLAN.md#locked-technical-decisions)'s locked technical decisions.
- Changing the chunking approach (tuning the constants is fine).
- Touching the chunk ID scheme.

## Working style

- One store, one model, concrete code. No abstract base classes, factories, dependency injection, or
  a `VectorStoreInterface` "in case we swap stores later".
- No config system. `constants.py` is the whole configuration story, plus the single `MICRORAG_HOME`
  env var that relocates the data directory.
- A module growing past ~300 lines is a signal to stop and check with the owner, not to split it into
  a package.
- Stay within scope. Ideas outside it go in [PLAN.md](PLAN.md), not into code.
- Remove dead code and unused imports before finishing a task.
- Follow the writing style below for anything you write, code and prose alike.

## Writing style

How generated prose and code should read on this project. Applies to documentation, commit messages,
comments, and any other text you produce here.

### Prose

Avoid the stylistic tics common to LLM output. Don't inflate importance: skip phrases like "stands as
a testament to", "plays a vital/pivotal/crucial role", "rich tapestry", "vibrant", "underscores its
significance", or claims that some mundane detail "reflects a broader" trend. Don't tack
present-participle commentary onto sentence ends ("..., highlighting its impact", "..., cementing its
legacy"). Cut the recurring vocabulary: delve, boasts (meaning has), showcase, foster, robust,
meticulous, landscape (figurative), realm, nestled, leverage. Don't overuse the rule of three or "not
only X but Y" / "it's not just X, it's Y" parallelism. Prefer plain verbs (wrote, not authored; used,
not utilized; has, not features). Use straight quotes and apostrophes, no em-dashes, no curly quotes.
Don't end with a "Conclusion" or "In summary" restatement, and don't add a "Despite its
challenges..." wrap-up. Don't pad with hedges ("it's important to note", "it's worth mentioning").
Don't add knowledge-cutoff or "based on available information" disclaimers. Don't over-bold, don't
turn every list item into "**Bolded label**: explanation", and don't put every section in Title Case.
Match length and formality to the task; default to fewer words, concrete specifics over generic
praise, and a real voice over a neutral encyclopedic hum.

Don't restate the takeaway after demonstrating it: if a section, example, or code sample already
makes the point, don't add a sentence explaining what it shows or why it matters. In documentation,
describe what something does once; skip the closing "this ensures/enables..." interpretation. State
things plainly instead of through stock indirect formulas: write "this is slow" not "performance
leaves something to be desired". Plain statements are shorter and easier to follow. Don't resolve
everything in one pass. It's fine, often better, to deliver the core change, name what's left open,
and stop. Prefer "X works now; Y and Z are untouched" over silently expanding scope to tie up every
loose end. Open questions and known limitations are allowed to stay open.

### Code

Don't docstring or comment trivial functions; comment only where logic is non-obvious. Use specific,
contextual names, not generic data/result/temp/process_data. Add error handling only where a failure
can actually occur; never wrap everything in broad try/except that swallows exceptions. Don't
over-engineer: no repository patterns, abstract base classes, factories, or dependency injection for
problems that don't need them. Prefer stdlib over pulling a library per sub-problem; don't grow the
dependency list unnecessarily. Clean up after iteration: remove dead code, unused functions, and
orphaned imports rather than leaving them. Calibrate structure to the actual requirement instead of
applying "best practice" boilerplate by default. Stay within the asked scope: don't opportunistically
refactor, rename, or add tests or features that weren't requested; mention them as follow-ups
instead.
