# Review: first read of the codebase

Written as if by a senior Python engineer opening this repository for the first
time: what bothers me, what confuses me, and where the code is harder to read
or more complicated than it needs to be. File references are `path:line` in the
current tree.

## Overall impression

This is a well-kept small codebase. It is ~3,500 lines of source with a test
suite of comparable size, a clean three-stage pipeline (index, fetch, parse), a
schema that fits on one screen, CI that runs lint plus a 3-version test matrix
plus a Windows smoke test, and documentation (README, PLAN.md, AGENTS.md) that
actually matches most of the code. The layering is sound: `core/fetch`,
`core/parse`, `core/index` are mechanisms, `core/pipeline` is orchestration,
`cli` is presentation. Most of what follows is therefore not "this is a mess"
but "these specific things would trip me up", roughly ordered by how much they
bothered me.

The two headline items: the corpse of the deleted web app is still embedded in
the database layer (roughly 200 lines of dead, tested code and stale
docstrings), and `clean_markdown.py` is the one file where I do not trust the
code to leave archived content intact.

---

## 1. The deleted web app is still here

Commit `4dd6b8a` ("Remove the web app") removed the app but not its support
code. `PageDatabase` still carries a whole read-model API whose only callers
are the tests:

- `get_by_slug` (`arciv/core/db/database.py:303`), docstring: "The backend
  uses it to resolve `/page/<slug>` to a page." There is no backend.
- `list_pages` (`database.py:437`), docstring: "for the browse view", along
  with its private machinery `_STATE_PREDICATES` (`database.py:77`) and
  `_SORT_COLUMNS` (`database.py:101`).
- `domain_counts` (`database.py:576`): "so the browse-by-domain view counts
  pending and failed pages too."
- `list_source_links` (`database.py:640`): "so the web source-detail view can
  group links."
- `list_sources_with_counts` (`database.py:737`).
- `get_files_for_url`, `get_urls_for_file`, `get_urls_for_source`
  (`database.py:613-638`): no production callers.
- `get_unfetched` and `get_all` (the Page-returning variants,
  `database.py:315`, `database.py:339`): superseded by the `_urls` variants in
  production code; only tests call them.
- `Page.state` and `is_skip_reason` (`arciv/core/db/models.py:76`,
  `models.py:14`): "Coarse UI state for the web browse view." The whole
  skipped-vs-failed classification machinery (`SKIP_REASON_PREFIX`,
  `_SKIP_LIKE` at `database.py:69`) now exists only to serve `Page.state` and
  `list_pages`, which nothing calls.
- `fetch_pending` (`arciv/core/pipeline/fetch.py:38`): no callers. Worse, the
  `fetch` CLI command (`arciv/cli/cli.py:610`) reimplements its exact body
  inline (`db.get_all_urls() if refetch else db.get_unfetched_urls()`) because
  it needs the URL list for reporting. So the helper is both dead and
  duplicated.

This is the most dangerous kind of dead code: `tests/test_database.py` (786
lines) exercises all of it, so it stays green, gets maintained, and pads the
coverage number while telling a new reader lies about what the system does. I
spent real time looking for the web frontend these docstrings describe.
AGENTS.md itself says "Clean up after iteration: remove dead code" and PLAN.md
says "Salvage nothing for now". Take PLAN.md at its word: delete these methods
and their tests. Git remembers.

Smaller items in the same category:

- `arciv/main.py` is a four-line vestigial entry point. The real ones are the
  `pyproject.toml` script and `arciv/cli/__main__.py`. Three ways to start the
  program, one of them pointing at a module nothing references.
- `data/stopwords_en.txt` is referenced by nothing in the repository. A reader
  will grep for "stopwords", find nothing, and wonder what feature they are
  missing (presumably a leftover from a removed search feature).

## 2. Module naming collisions: fetch vs fetch, parse vs parse

The package layout has `arciv/core/fetch/` and `arciv/core/pipeline/fetch.py`,
plus `arciv/core/parse/` and `arciv/core/pipeline/parse.py`. Four modules, two
names. Reading `cli.py`'s imports:

```python
from arciv.core.fetch import evaluate_url, load_rules, process_url
from arciv.core.pipeline import (..., fetch_urls, parse_pending, ...)
```

Which `fetch` does `fetch_urls` come from? You have to know the convention
(mechanism vs orchestration) before the imports read cleanly, and inside
`pipeline/parse.py` the import block juxtaposes `from arciv.core.parse import
...` with the module's own name in a way that made me double-check I wasn't
looking at a circular import. The layering itself is good; the naming is the
problem. `pipeline/fetch.py` and `pipeline/parse.py` are each under 70 lines;
renaming them (`stages.py`, or `fetch_stage.py`/`parse_stage.py`, matching the
existing `tests/test_parse_stage.py` and `test_archive_stage.py` names, which
already avoid the collision!) would remove the ambiguity for the cost of a
one-line import change.

Related confusion: the URL-processing code lives in `core/fetch/` but is used
just as much by the index stage. "Why does indexing import from fetch?" was a
genuine speed bump. A `core/urls/` package (rules, url_processing,
url_helpers) would describe what the code is rather than which stage first
needed it.

## 3. clean_markdown.py: the code I trust least

This is an archival tool whose promise is "markdown you can trust years from
now" (README), and this file runs blind regex substitutions over every
archived document. Several patterns can corrupt legitimate content:

- `ITALIC_STAR_RE = re.compile(r"(?<!\w)\*(.+?)\*(?!\w)", re.DOTALL)`
  (`arciv/core/parse/clean_markdown.py:16`). With `DOTALL` and a lazy group,
  the two asterisks it pairs can be in different paragraphs. Prose like
  "5 * 3 = 15 and 2 * 2 = 4" has "* 3 = 15 and 2 *" silently deleted of its
  asterisks; a markdown list that uses `*` bullets has its first two bullets
  eaten as an "italic" span. Nothing about being an italic marker requires
  matching across lines.
- `MISSING_SPACE_RE = re.compile(r"([.:;!?])([A-Z])")`
  (`clean_markdown.py:34`) turns "Node.JS" into "Node. JS", "U.S.A" into
  "U. S. A", and any `module.ClassName` mention in prose into
  "module. ClassName". Punctuation followed by a capital is simply not a
  reliable signal of a missing space.
- The pipeline strips all bold, italic, and inline-code markers from the
  stored markdown (`strip_inline_code`, `strip_bold_italic`). That is a lossy,
  irreversible editorial decision applied at archive time. It may well be the
  right call for this tool's goals, but nothing in README or AGENTS.md says
  "the archive deliberately discards emphasis formatting", and I would want
  that decision written down where a future me can reconsider it, because
  re-fetching years later may not be possible (dead links are the reason this
  tool exists).

The irony is that AGENTS.md's own principle covers this: "Prevent, don't
post-process. Fix data quality problems at the source ... rather than writing
complex cleanup logic downstream." This file is exactly the complex downstream
cleanup that principle warns about. At minimum: drop `DOTALL` from the
italic/bold patterns (or bound the group with `[^*\n]`), delete
`fix_missing_spaces`, and document the intentional destructiveness. The
fluent-builder `MarkdownCleaner` class is also more machinery than five regex
passes need; a function calling five `re.sub`s in order would be shorter than
the class plus its `_apply`/`_apply_many` indirection.

## 4. Latent bugs and correctness concerns

### 4.1 Pending rows that can never complete and never be pruned

The fetch stage re-runs URL processing over URLs that are already processed
database keys (`arciv/core/fetch/fetcher.py:257-263`, deliberately, "so a rule
edited after indexing still applies"). Consequences when a rule changes
between index and fetch:

- A rule that now *skips* the stored URL logs a warning and continues. The row
  stays `pending` forever: `status` counts it as pending on every run, `fetch`
  warns about it on every run, and no `prune` mode can remove it, because
  `missing` and `failed` both require `fail_reason IS NOT NULL`
  (`database.py:92-96`) and a fetch-time skip never writes one. The only
  escape is `prune all`.
- A rule that now *rewrites* the stored URL fetches and stores the result
  under the new key, while the old row again stays pending forever with the
  same symptoms.
- A user rule with a non-idempotent action (`prepend` is the obvious one) can
  rewrite an already-rewritten URL a second time. The shipped defaults happen
  to be idempotent-in-effect (the medium prepend changes the domain that its
  own match tests), but nothing checks or documents that requirement for user
  rules.

Suggestion: when fetch-time processing skips or diverts a stored URL, record
that on the row (a `fail_reason` like "skipped by rule X since indexing" would
make it prunable and visible in `status`), and document the idempotency
expectation in the rules docs.

### 4.2 Slug collisions: silent drop at index, batch abort at fetch

Slugs are `domain-` plus 8 hex chars of MD5 (`arciv/core/fetch/url_helpers.py:127`),
i.e. 32 bits. Within one heavily-archived domain, collisions are unlikely but
not fanciful (about 1% at ~10k pages of one domain). What happens on
collision is the problem:

- `ensure_pages` uses `INSERT OR IGNORE` (`database.py:275`). `OR IGNORE`
  swallows *any* constraint violation, including the unique slug index, so a
  new URL colliding with an existing page's slug is silently never registered.
  No log line, no failed row, nothing.
- On the fetch path, `_store_success` goes through the upsert, which conflicts
  on `url` only; a slug collision raises an uncaught `sqlite3.IntegrityError`
  inside `asyncio.gather` (see 4.3), aborting the whole batch.

The codebase clearly knows collisions matter, because
`_ensure_unique_slug_index` (`database.py:158`) has a carefully-written error
message for pre-existing duplicates. But the runtime paths handle the same
event with silence or a crash. Widening the hash to 12-16 characters makes the
whole class of problem negligible and costs nothing.

### 4.3 One unexpected exception kills the whole fetch batch

Both `asyncio.gather` calls in `_fetch_batch_async` (`fetcher.py:301`,
`fetcher.py:322`) run without `return_exceptions=True`, and the per-task code
paths are not exception-proof: `_save_html`/`_save_pdf` can raise `OSError`
(disk full, path too long, permissions), `upsert` can raise
`sqlite3.IntegrityError` (see 4.2). One such failure cancels every other
in-flight fetch in the batch and surfaces as a traceback. For a long overnight
`source update --all`, one bad page discarding hundreds of in-flight fetches
is a real cost. Either wrap the per-URL task in a try/except that records a
failure row, or use `return_exceptions=True` and handle them after the gather.

### 4.4 One unreadable note file kills the whole index run

`Note._read_content` (`arciv/core/notes/note.py:42`) wraps `read_text` and
re-raises as `IOError`. Nothing above it catches: `load_notes` yields notes
into `_index_notes`, so a single non-UTF-8 `.txt` file (or a permission
denied) anywhere in a registered vault aborts the entire `source update` with
a traceback. A note directory is exactly the kind of place a stray
Latin-1-encoded file or a binary file with a `.txt` extension shows up. Skip
the file with a warning and keep indexing. (Also: `raise IOError(...)` without
`from e` discards the cause, and `IOError` has been an alias of `OSError`
since Python 3.3.)

### 4.5 Fetch retry loop: empty failure reason, off-by-one naming

In `_fetch_one` (`fetcher.py:344-374`):

- If `session.fetch` returns without raising but `html_content` is `None`,
  `last_reason` is still `""`, so the page is stored with an empty failure
  reason and `status` shows a failure with no explanation.
- `max_retries` is really "max attempts": `range(1, self.max_retries + 1)`
  with the default of 2 means two total attempts, i.e. one retry. The
  docstring says "Maximum retry attempts for transient failures", and
  `ARCIV_MAX_RETRIES=0` would mean "never fetch anything" (though `_env_int`
  happens to floor at 1). Rename or fix the loop bound.
- The backoff `await asyncio.sleep(2 * attempt)` holds one of the session's
  `max_pages` browser-page slots while sleeping, so transient failures reduce
  effective concurrency for everyone else. Minor, but worth knowing.

### 4.6 canonicalize strips query parameters that can carry identity

`_TRACKING_PARAM_RE` (`url_helpers.py:133`) removes `ref`, `source`, and
`campaign` by exact name. Unlike `utm_*` or `fbclid`, these are generic words
that some sites use as real routing/identity parameters (`?source=rss` styles
of content negotiation, `?ref=` as a page selector on some doc sites). Two
different pages could canonicalize to the same key, and the second one indexed
silently never gets its own archive entry. The comment says "widely-safe
heuristics", which is honest, but the failure mode is silent content loss in
an archival tool. I would keep only the unambiguous tracker names in the
always-on layer and move `ref`/`source`/`campaign` to the editable rules.

### 4.7 Assorted smaller correctness notes

- `source_update` (`cli.py:504`) passes `name: str | None` into
  `archive_source(db, name)` which is typed `str`. Safe at runtime (the
  XOR-check above guarantees it), but it fails a type check, and there is no
  type checker to notice (see section 6).
- `prune` (`cli.py:674-685`) computes targets with `dry_run=True`, prompts,
  then re-runs the selection. The two selections can differ if another arciv
  process writes in between; the count the user confirmed is not necessarily
  the count deleted. Single-user tool, low stakes, but a comment acknowledging
  the race would spare the next reader the analysis.
- `_SKIP_LIKE` is interpolated into SQL via f-string (`database.py:79`). Safe
  today because `SKIP_REASON_PREFIX` is a fixed `"too short"`, but it is a
  string that would break the query if it ever gained a quote or a LIKE
  metacharacter, and nothing marks it as load-bearing SQL. (This whole
  machinery is dead per section 1, so deleting is easier than hardening.)
- The connection opened in `PageDatabase.__init__` has no `busy_timeout`; two
  concurrent arciv invocations (a long fetch plus a `status` in another
  terminal is realistic) can hit `database is locked` on the writer side.
  One `PRAGMA busy_timeout=5000` removes the sharp edge.
- `pipeline/parse.py` counts words as `len(text.split())` for PDFs and raw
  text (`pipeline/parse.py:104`, `:131`) but uses the regex-based
  `count_words` for HTML (`parser.py:38`). Two definitions of "word" feed the
  same `min_words` gate; they differ on punctuation-heavy text. Pick one.

## 5. Design and readability gripes

### 5.1 PageDatabase is an API sprawl

Even after removing the dead web-app methods, the class has near-duplicate
families: `get_unfetched`/`get_unfetched_urls`/`count_unfetched`,
`get_fetched`/`get_fetched_urls`, `get_all`/`get_all_urls`/`count`,
`list_fetched` vs `list_pages`. The URL-only variants exist for good
efficiency reasons (PLAN.md documents the round-trip reduction work), but the
Page-returning versions they superseded were left behind, so the class now
presents two generations of its own API side by side, plus two parallel state
taxonomies: `status_counts`'s five states
(pending/fetch_failed/awaiting_parse/parse_rejected/parsed, `database.py:382`)
and `_STATE_PREDICATES`' five different states
(done/skipped/failed/fetched/pending, `database.py:77`). A reader has to work
out that one taxonomy is live and the other is a dead UI concept. Deleting the
dead generation (section 1) fixes most of this for free.

### 5.2 The Note class is OOP for no benefit

`arciv/core/notes/note.py` declares "Base class for a 'Note' object" with no
subclasses, sets `filename` and `extension` attributes nothing reads, defines
a `__repr__` for logs that never print one, performs file I/O in the
constructor, wraps `Path(note_path)` in a try/except that cannot realistically
fire, and carries a `# TODO: Verify note not empty` from some earlier era.
`load_note` (`notes/__init__.py:14`) is a one-line alias for the constructor.
The real content of this module is `extract_urls` and the frontmatter strip,
which is a pure function of text. AGENTS.md: "Abstractions must earn their
keep." This one does not: a `read_note(path) -> str` function and an
`extract_urls(text) -> list[str]` function would be smaller, easier to test,
and would fix 4.4 naturally at the call site. Also, the sibling packages keep
`__init__.py` as pure re-exports, but this one defines `load_note`/`load_notes`
logic inside `__init__.py`; put logic in the module, exports in the init, like
everywhere else.

### 5.3 GlobalOptionGroup: a clever hack that will bite

`GlobalOptionGroup.parse_args` (`cli.py:101-141`) textually hoists recognized
global tokens to the front of argv before Click parses. It is well-commented,
but it is still a shadow parser with shadow-parser problems:

- It does not respect the `--` end-of-options convention; `arciv get -- --json`
  hoists the `--json` the user was trying to pass through literally.
- Any positional or option value that happens to equal a global token is
  stolen: a source literally named `-v`, `--domain --json`. Unlikely values,
  but the failure is silent re-interpretation, not an error.
- The hardcoded `_GLOBAL_FLAGS`/`_GLOBAL_VALUE_OPTS` sets must be kept in sync
  with the callback's options by hand; adding a global option and forgetting
  the set produces the confusing old behavior only for the after-the-command
  spelling.

README, meanwhile, still says "Global flags go *before* the command"
(README.md:103), while `cli.py`'s docstring says "before or after" - the docs
disagree about whether this hack exists. Given Click explicitly rejects this
UX and the workaround costs 40 lines of token surgery, I would either accept
Click's convention (delete the class, keep the documented before-the-command
form) or at least handle `--` and document the sync requirement loudly.

### 5.4 Import-time side effects in settings.py

Importing `arciv.settings` calls `load_dotenv()` (`settings.py:22`) and
resolves `DATA_DIR` immediately. Consequences visible elsewhere in the repo:

- The test suite has to monkeypatch four copied names (`DATA_DIR`, `DB_PATH`,
  `SAVED_DIR`, `USER_RULES_PATH`) *in the cli module* (`tests/test_cli.py:39-42`),
  because by import time the constants have already been baked into each
  importer's namespace. That fixture is the tell that the config design fights
  the tests.
- `_env_int` logs warnings through loguru during import, before
  `configure_logger` has run, so malformed `ARCIV_*` values print in the
  default loguru format and then the handlers get reset. Cosmetic, but the
  kind of inconsistency users report as a bug.
- Behavior depends on the cwd you happen to run in (nearest `.env` upward),
  which is surprising for an installed tool; SETUP.md pitches `.env` for
  development, but the lookup runs for every user everywhere.

A tiny `get_settings()` (even a cached function returning a frozen dataclass)
would make the test fixture one monkeypatch and remove the import-order
subtleties. Not urgent, but this is the part of the codebase whose testing
story creaks loudest.

### 5.5 Two sources of truth for the active rules

`Fetcher.__init__` defaults `rules` to `load_rules()` with no user path
(`fetcher.py:85`), while the pipeline injects `load_rules(USER_RULES_PATH)`
(`pipeline/fetch.py:33`). The comment explains this is for tests, but the
result is an attractive nuisance: constructing a `Fetcher` the obvious way
silently ignores the user's rules.toml. Defaulting `rules` to `()` (or making
it required) would fail loud instead of differently.

### 5.6 parse_html's min_words parameter

`parse_html(html, clean=True, min_words=...)` (`parser.py:127`) takes the
caller's rejection threshold purely to decide whether it may skip computing
`full_word_count`. The docstring needs eight lines to explain the coupling,
and `ConversionResult.full_word_count` sometimes holds a real count and
sometimes a copy of `word_count`, depending on an optimization the caller
opted into. This works, but it is the most head-scratching interface in the
repo. Making `full_word_count` lazy (a callable or a second function the
gate calls only when `word_count < min_words`, from `pipeline/parse.py` where
the gate lives) would keep the optimization without threading the threshold
into the parser's signature.

### 5.7 Inconsistent skip logging between index and get

`register_urls` warns for every skipped URL (`index/index.py:126`), but
`_index_notes` drops skipped links silently (`index/index.py:56-58`). So
`arciv get <url>` tells you why your URL was refused, while `arciv source
update` quietly ignores any number of links (http:// links, media files,
policy skips) with no trace at any log level. For a tool whose pitch is "every
link is recorded", a debug-level line per skip in the notes path would make
"why isn't this page in my archive" answerable without `rules test`.

## 6. Tooling gaps

- There is no ruff configuration at all: no `[tool.ruff]` in pyproject, no
  `.ruff.toml`. CI runs `ruff check` with defaults, which enables only the
  pyflakes/pycodestyle-error baseline. Import sorting (`I`), bugbear (`B`,
  which would have flagged the `raise ... from` miss in `note.py`),
  pyupgrade (`UP`), and the rest are off. For a project whose AGENTS.md leans
  on conventions ("relative imports within the same module", `_RE` suffix,
  etc.), almost none of that is machine-enforced, and the code has drifted:
  `cli.py` mixes absolute imports for `arciv.*` with a relative one for
  `.output`, and import blocks are not consistently sorted (`arciv.settings`
  before `arciv.core.db` in `cli.py:66-89`).
- No type checker. AGENTS.md says "Lean on type hints ... to compensate" for
  the absence of reviewers, but nothing checks the hints, and section 4.7's
  `str | None` -> `str` mismatch shows they are already drifting. `uv run
  mypy` or pyright in the lint job would make the hints load-bearing. (A
  `py.typed` marker is missing too, though as a CLI-only package that matters
  less.)
- `addopts = "--cov=arciv --cov-report=term-missing"` (pyproject.toml:39)
  forces coverage instrumentation onto every pytest invocation, including
  single-test debugging runs and IDE debuggers, where coverage both slows
  things down and breaks breakpoint tooling. Put coverage flags in CI's
  command line, not in the project defaults.
- `hypothesis` is a full dev dependency used by exactly one test file
  (`tests/test_url_processor.py`). Fine, just noting the ratio.
- Test file naming nit: `test_url_processor.py` tests `url_processing.py`;
  the module was presumably renamed and the test file was not.

## 7. Documentation drift

The documentation is unusually good, which makes the stale parts stand out:

- Docstrings referencing the removed web app: `models.py:78` ("web browse
  view"), `database.py:309` ("The backend uses it"), `database.py:643` ("the
  web source-detail view"). Section 1 removes most of these by deleting their
  hosts.
- `settings.py:6` still says "so the future backend container can mount it
  directly"; PLAN.md has since rejected the web app and containerization.
- README.md:103 vs `cli.py:44` disagree on whether global flags work after
  the command (they do; README says they must come first).
- The 51-line module docstring of `cli.py` restates the README's command
  tour. Two hand-maintained copies of the same tutorial will diverge (the
  global-flags discrepancy above is that divergence already happening). The
  per-command `--help` text is the copy users see; I would cut the module
  docstring to a few lines and let README own the tour.
- PLAN.md mixes live roadmap with completed history ("Efficiency follow-ups:
  implemented" is a PR description preserved in the plan). Useful as a
  journal, but as a first-time reader I could not tell which sections still
  describe intent versus archaeology; a "done" section or dates would help.

On the flip side, a general note on comment density: many comments here earn
their place (the WAL/fsync rationale on `bulk()`, the FK-ordering notes on
prune), but a substantial fraction narrate implementation choices to a
reviewer ("One batched lookup instead of two db.get() round-trips per URL",
"as `_index_notes` already did", the PLAN.md cross-references). Those are
change-description comments, not constraints of the code; they rot the moment
the neighboring code changes, and this codebase has enough of them that the
signal-to-noise of the genuinely load-bearing comments suffers. The commit
history and PLAN.md already record the why-this-change story.

## 8. Nits

- `datetime.now(timezone.utc).isoformat()` is spelled out in five modules;
  `database.py` even has a private `_now()` for it. One shared `utc_now()`
  would do. (Python 3.12 also allows `datetime.now(UTC)`.)
- `NOTE_EXTENSIONS` is a tuple, `RAW_TEXT_EXTENSIONS` a frozenset; same
  concept, two container types.
- `load_notes` scans `sorted(note_dir.glob("**/*"))`, materializing every
  path in the vault (including images and other non-notes) to filter
  afterward; `rglob` per extension or a suffix check inside an unsorted walk
  would scale better with big vaults. The "lazily, one per file" docstring
  claim is true only of the file *contents*.
- `check_html` searches the first 3000/5000 chars for block-page markers,
  numbers with no stated provenance. Fine as heuristics, but a one-line "big
  enough for any real <head>" comment would preempt the obvious question.
- `_MEDIA_EXT_RE` (`url_processing.py:31`) matches anywhere in the URL, so a
  query value ending in `.mp4` skips the page; anchoring to the path (as
  `is_pdf_url` does with `urlparse(url).path`) would be more precise. Also,
  `.json`/`.xml` being "media" surprised me; "non-content" is in the comment,
  but the reason string shown to users says "media/non-content file" for an
  `.xml` sitemap, which reads oddly.
- No index on `links.source_name` or `pages.fetched_at`; `list --source`
  joins and every `list` sorts on these. Irrelevant at personal-archive
  scale, worth a line in the schema comment saying so deliberately.
- `logs/arciv.log` rotates daily but nothing prunes old rotations
  (`settings.py:121-129`); loguru's `retention=` is one argument away.
- `emit` (`cli/output.py:41`) mixes `typer.echo` text mode for newline
  records with raw `buffer` writes for NUL records; on Windows the newline
  path emits `\r\n`. The `--null` comment shows the author knows; a symmetric
  raw write for both would be simpler than remembering the asymmetry.
- `fetcher._fetch_batch_async` returns early *inside* the `db.bulk()` block
  when there is no HTML to fetch (`fetcher.py:306`), while the HTML results
  are collected *outside* it (`fetcher.py:326`); correct, but I had to trace
  the `with` block twice to convince myself `fetched` is always bound. Moving
  the early return above the `with`, or collecting results uniformly inside,
  would read linearly.
- PDFs are fully fetched before the browser session opens
  (`fetcher.py:292-321`); the two pools could run concurrently. Deliberate
  simplicity, presumably, but a "sequential on purpose" comment would stop
  the next person from "fixing" it, or from wondering why a batch with one
  slow PDF delays all HTML.

## 9. What I would do first

1. Delete the dead web-app surface from `PageDatabase`, `models.py`,
   `pipeline/fetch.py`, plus `arciv/main.py` and `data/stopwords_en.txt`, and
   their tests. Biggest comprehension win per hour of work in the repo.
2. Defuse `clean_markdown.py`: remove `DOTALL` from emphasis patterns, drop
   `fix_missing_spaces`, document the intentional formatting strip.
3. Make fetch batches fault-isolated (4.3) and index runs survive unreadable
   files (4.4); these are the two "one bad input ruins the run" paths.
4. Widen the slug hash and make slug collisions loud (4.2).
5. Add a ruff config (at least `I`, `B`, `UP`) and a type checker to CI so
   the conventions AGENTS.md relies on are enforced by machines, not memory.
6. Rename `pipeline/fetch.py`/`pipeline/parse.py` to end the module-name
   collisions.
7. Decide what to do about never-completing pending rows (4.1), even if the
   decision is just a `prune pending` mode and a docs note.
