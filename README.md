# Arciv

[![CI](https://github.com/MichaelVerdegaal/Arciv/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelVerdegaal/Arciv/actions/workflows/ci.yml)

Arciv is your personal archive for reading material. The blog posts, research papers, and
documentation you collect — linked in your notes or fed in directly — are fetched and stored
as clean, searchable markdown you can trust years from now. Reading material only: not books,
not videos.

## What It Does

Three stages, no writeback into your notes:

1. **Indexing** — extract links from your files; every link is recorded with the file it came
   from and when it was indexed
2. **Fetching** — download raw pages (browser for HTML, direct HTTP for PDFs)
3. **Parsing** — validate and convert to markdown, archived on disk with SQLite tracking state

## Usage

Archive things directly — a single URL, a single file, or a whole directory:

```bash
arciv get https://example.com/post   # archive one URL
arciv get --file note.md             # archive all links in one file
arciv get --dir path/to/notes        # archive all links in a directory
```

Register directories you index repeatedly as named sources:

```bash
arciv add ~/vault/daily-notes notes  # register a source and archive it
arciv add ~/vault/notes notes --no-archive  # register only, archive later
arciv archive notes                  # re-index, fetch, and parse one source
arciv archive --all                  # archive every registered source
arciv sources                        # list registered sources
arciv remove notes                   # unregister (archived pages are kept)
```

`add` and `archive` run the whole pipeline (index, then a single batched fetch,
then parse) so a source goes from registered to archived in one command. The
individual `index`, `fetch`, and `parse` stages stay available for development.

Run individual pipeline stages:

```bash
arciv fetch                          # download indexed URLs still pending
arciv fetch --refetch                # re-download every known page
arciv parse                          # convert fetched pages to markdown
arciv parse --reparse                # re-parse everything from disk
```

Inspect the archive:

```bash
arciv status                         # pipeline counts + failure summary
arciv list --n 50                    # fetched pages: time, domain, URL
arciv list --domain medium.com       # only pages from one domain
arciv path https://example.com/post  # filepath of its archived markdown
arciv db dir                         # where the archive lives on disk
arciv db remove                      # delete the database (asks first)
```

Manage URL rules — skip or rewrite URLs before they are fetched (the same
rules the web app edits):

```bash
arciv rules list                                   # rules, in the order they apply
arciv rules add domain medium.com rewrite -r scribe.rip  # rewrite a host
arciv rules add domain youtube.com skip            # skip a domain
arciv rules remove 3                               # remove a rule by id
```

### Global options and pipes

Data goes to stdout; all logs and diagnostics go to stderr, so `arciv list | cat`
shows only data. Global flags go *before* the command:

```bash
arciv -v fetch         # more detail (-v debug, -vv trace)
arciv -q fetch         # errors only
arciv --color never list
arciv --json status    # machine-readable output on stdout
```

With `--json`, `status` and `path` emit one JSON object, while `list`,
`sources`, and `rules list` emit JSONL (one object per line) so they stream
into `head`/`grep`/`jq`.
The commands compose with standard Unix tools:

```bash
# Re-archive every page from a given domain found in the archive
arciv list --json | jq -r .url | grep medium.com | arciv get -

# NUL-separated output survives odd characters and feeds xargs -0
arciv list --n 0 --null | xargs -0 -n1 echo
```

`arciv get -` reads newline-separated URLs from stdin.

See [SETUP.md](SETUP.md) for installation and configuration.

## Web app

A single self-hosted web app browses the archive and archives new URLs from the browser with
live status. It is a FastAPI service that imports this library directly and renders its own
HTML (Jinja2 + Datastar, BeerCSS) — no separate frontend runtime. Sources are managed from
the browser too: add a directory of notes, view the files indexed and the links found in each,
re-archive to pick up changes, or remove a source. Any page's detail view can re-fetch
(re-download then re-parse) or re-parse from disk, so URL and parse rules can be tried out
without dropping to the CLI.

```bash
# With Docker, mounting the same data dir the CLI writes:
ARCIV_DATA_DIR=~/.local/share/arciv docker compose up   # http://localhost:8000

# Or directly from a clone:
uv run uvicorn arciv_api.app:app                         # http://localhost:8000
```

One user per instance — no auth or TLS by design. To reach it beyond your LAN, put a reverse
proxy with auth in front. See [PLAN.md](PLAN.md) for the architecture and roadmap.

## The Name

"Arciv" is a compact respelling of *archivum*, the Latin root of "archive". Arciv helps you accumulate historical records, just like a physical archive does.
