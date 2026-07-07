# AGENTS.md
## Overview
See [README.md](README.md) for an overview of the project.

## Setup instructions
See [SETUP.md](SETUP.md) for setup instructions.

## Long term
See [PLAN.md](PLAN.md) for issues and long-term plans, and

### Architecture
Three stages, no writeback into the notes.

1. Indexing: Parse text files (`.md`,`.txt`, `.rst`), extract all links, deduplicate, apply
   filtering/rewrite rules, register pending pages. Each linkgets a row with the URL, the full
   normalized filepath it was found in, and an indexed-at timestamp. Indexing operates on registered
   sources (`arciv source add <dir> <name>`).
2. Fetching: Download HTML through Scrapling's stealth browser session (patchright, async,
   concurrency-controlled); PDFs and direct downloads through Scrapling's curl_cffi fetcher. Both
   return one `Response` type. Writes `page.html` / `page.pdf` to disk, no conversion.
3. Parsing: Validate fetched HTML, convert to markdown via trafilatura (HTML) or liteparse (PDF),
   write `page.md` next to the raw file, fill in title/author/word count.

Each stage has a dedicated CLI command;`arciv get` runs all three in order on a URL, a file
(`--file`), or a directory (`--dir`).

### Key Libraries
- `scrapling`: unified fetch layer (patchright stealth browser for HTML, curl_cffi for
  PDFs/downloads)
- `trafilatura`: HTML content extraction
- `liteparse`: PDF text extraction
- `tldextract`: domain parsing (registered domain grouping)
- `loguru`: logging (one log statement per URL processed)
- `aiofiles`: async file operations (downloaded files, cache, etc.)

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
- Adding dependencies beyond core stack
- Changing the SQLite schema
- Modifying URL processing rules or rewriters
- Changing scraping/conversion pipeline flow

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