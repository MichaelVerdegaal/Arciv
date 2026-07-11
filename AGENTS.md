# AGENTS.md
## Overview
See [README.md](README.md) for an overview of the project.

## Setup instructions
See [SETUP.md](SETUP.md) for setup instructions.

## Long term
See [PLAN.md](PLAN.md) for scope rules and long-term plans, and [FOLLOWUPS.md](FOLLOWUPS.md)
for known limitations.

### Architecture
Local semantic search over markdown notes: `index` walks a directory of `*.md` files, chunks
them (chonkie-based, heading-aware), embeds each chunk with a local ONNX model (CPU only), and
upserts into a persistent ChromaDB collection; `query` embeds the query text (with a model-specific
prefix) and returns the nearest chunks. Everything lives under `MICRORAG_HOME` (default
`~/.microrag`): the downloaded model in `model/`, the Chroma DB in `db/`.

Module boundaries (see PLAN.md): `embedder` knows nothing about Chroma, `store` knows nothing
about ONNX or tokenizers, `chunker` is pure functions over strings, `cli` is the only place they
are wired together. Chunk IDs are `sha256(relative_path:index:chunk_text)`, so re-indexing
unchanged files is a no-op via Chroma upsert.

### Key Libraries
- `chromadb`: persistent vector store, one cosine collection, telemetry disabled.
- `onnxruntime` + `tokenizers`: CPU inference for the `MongoDB/mdbr-leaf-ir` embedding model.
- `chonkie`: markdown parsing (code fences/tables separated from prose), size-based chunking, and
  the `BaseEmbeddings` interface that `OnnxEmbedder` implements.
- `huggingface_hub`: one-time model download (the only networked code path).
- `numpy`: embedding arrays.
- `argcomplete`: shell tab completion for the CLI.

## Context
This is a solo project; no other developers read or maintain this code. That means:

- No one will explain what "clever" code does when you've forgotten. Write for the version of
  yourself 6 months from now.
- No PR reviews catch mistakes. Lean on type hints, explicit naming, and logging to compensate.
- Refactoring is cheap (no coordination cost), but debugging is expensive (no one to ask).

## Code Standards
ALWAYS:
- Type hint all function parameters and return types. Prefer builtin types (`list`, `dict`) over
  `typing` module types (`List`, `Dict`).
- Use Google docstring style.
- Raise specific exceptions with context.
- Put regex patterns in constants with the `_RE` suffix (e.g. `DATE_RE`).
- When adding imports in `__init__.py`, add to `__all__` as well.
- Use relative imports within the same module.
- Use `pathlib` over `os` for file paths.

ASK FIRST:
- Adding dependencies beyond the whitelist in PLAN.md
- Changing anything in PLAN.md's "Locked technical decisions" section
- Changing the chunking approach (tuning the constants is fine)
- Touching the chunk ID scheme

NEVER:
- Skip type hints on functions
- Hardcode file paths
- Use lazy imports inside functions
- Add `*args` / `**kwargs` without a specific need
- Use premature abstraction, design patterns for their own sake, or metaprogramming where a simple
  function would do

## Formatting requirements
Avoid the stylistic tics common to LLM output. Don't inflate importance: skip phrases like "stands
as a testament to", "plays a vital/pivotal/crucial role", "rich tapestry", "vibrant", "underscores
its significance", or claims that some mundane detail "reflects a broader" trend. Don't tack
present-participle commentary onto sentence ends ("..., highlighting its impact", "..., cementing
its legacy"). Cut the recurring vocabulary: delve, boasts (meaning has), showcase, foster, robust,
meticulous, landscape (figurative), realm, nestled, leverage. Don't overuse the rule of three or
"not only X but Y" / "it's not just X, it's Y" parallelism. Prefer plain verbs (wrote, not authored;
used, not utilized; has, not features). Use straight quotes and apostrophes, no em-dashes, no curly
quotes. Don't end with a "Conclusion" or "In summary" restatement, and don't add a "Despite its
challenges..." wrap-up. Don't pad with hedges ("it's important to note", "it's worth mentioning").
Don't add knowledge-cutoff or "based on available information" disclaimers. Don't over-bold, don't
turn every list item into "**Bolded label**: explanation", and don't put every section in Title
Case. Match length and formality to the task; default to fewer words, concrete specifics over
generic praise, and a real voice over a neutral encyclopedic hum.

Don't restate the takeaway after demonstrating it: if a section, example, or code sample already
makes the point, don't add a sentence explaining what it shows or why it matters. In documentation,
describe what something does once; skip the closing "this ensures/enables..." interpretation. State
things plainly instead of through stock indirect formulas: write "this is slow" not "performance
leaves something to be desired". Plain statements are shorter and easier to follow. Don't resolve
everything in one pass. It's fine, often better, to deliver the core change, name what's left open,
and stop. Prefer "X works now; Y and Z are untouched" over silently expanding scope to tie up every
loose end. Open questions and known limitations are allowed to stay open.

For generated code: don't docstring or comment trivial functions; comment only where logic is
non-obvious. Use specific, contextual names, not generic data/result/temp/process_data. Add error
handling only where a failure can actually occur; never wrap everything in broad try/except that
swallows exceptions. Don't over-engineer: no repository patterns, abstract base classes, factories,
or dependency injection for problems that don't need them. Prefer stdlib over pulling a library per
sub-problem; don't grow the dependency list unnecessarily. Clean up after iteration: remove dead
code, unused functions, and orphaned imports rather than leaving them. Calibrate structure to the
actual requirement instead of applying "best practice" boilerplate by default. Stay within the asked
scope: don't opportunistically refactor, rename, or add tests or features that weren't requested;
mention them as follow-ups instead.