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
arciv add ~/vault/daily-notes notes  # register a source
arciv sources                        # list registered sources
arciv index notes                    # index one source
arciv index --all                    # index every source
arciv remove notes                   # unregister (archived pages are kept)
```

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

### Global options and pipes

Data goes to stdout; all logs and diagnostics go to stderr, so `arciv list | cat`
shows only data. Global flags go *before* the command:

```bash
arciv -v fetch         # more detail (-v debug, -vv trace)
arciv -q fetch         # errors only
arciv --color never list
arciv --json status    # machine-readable output on stdout
```

With `--json`, `status` emits one JSON object, while `list` and `sources` emit
JSONL (one object per line) so they stream into `head`/`grep`/`jq`. The commands
compose with standard Unix tools:

```bash
# Re-archive every dead-domain page found in the archive
arciv list --json | jq -r .url | grep dead-domain | arciv get -

# NUL-separated output survives odd characters and feeds xargs -0
arciv list --n 0 --null | xargs -0 -n1 echo
```

`arciv get -` reads newline-separated URLs from stdin.

See [SETUP.md](SETUP.md) for installation and configuration.

## Where It's Going

The CLI foundation is in place; the focus now is on getting insight into what's stored — a web
UI for browsing the archive, backed by this CLI. See [PLAN.md](PLAN.md) for the roadmap.

## The Name

"Arciv" is a compact respelling of *archivum*, the Latin root of "archive". Arciv helps you accumulate historical records, just like a physical archive does.
