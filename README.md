# Clotho

[![CI](https://github.com/MichaelVerdegaal/Clotho/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelVerdegaal/Clotho/actions/workflows/ci.yml)

Clotho is your personal archive for reading material. The blog posts, research papers, and
documentation you collect — linked in your notes or fed in directly — are fetched and stored
as clean, searchable markdown you can trust years from now. Reading material only: not books,
not videos.

In ancient greek mythology, Clotho is one of the three Fates responsible for spinning the thread
of life. And what is a knowledge archive, if not a web of interconnected threads of knowledge?

## What It Does

Three stages, no writeback into your notes:

1. **Indexing** — extract links from your files; every link is recorded with the file it came
   from and when it was indexed
2. **Fetching** — download raw pages (browser for HTML, direct HTTP for PDFs)
3. **Parsing** — validate and convert to markdown, archived on disk with SQLite tracking state

## Usage

Archive things directly — a single URL, a single file, or a whole directory:

```bash
clotho get https://example.com/post   # archive one URL
clotho get --file note.md             # archive all links in one file
clotho get --dir path/to/notes        # archive all links in a directory
```

Register directories you index repeatedly as named sources:

```bash
clotho add ~/vault/daily-notes notes  # register a source
clotho sources                        # list registered sources
clotho index notes                    # index one source
clotho index --all                    # index every source
clotho remove notes                   # unregister (archived pages are kept)
```

Run individual pipeline stages:

```bash
clotho fetch                          # download indexed URLs still pending
clotho fetch --refetch                # re-download every known page
clotho parse                          # convert fetched pages to markdown
clotho parse --reparse                # re-parse everything from disk
```

Inspect the archive:

```bash
clotho status                         # pipeline counts + failure summary
clotho list --n 50                    # fetched pages: time, domain, URL
clotho path https://example.com/post  # filepath of its archived markdown
clotho db dir                         # where the archive lives on disk
clotho db remove                      # delete the database (asks first)
```

See [SETUP.md](SETUP.md) for installation and configuration.

## Where It's Going

The CLI foundation is in place; the focus now is on getting insight into what's stored — a web
UI for browsing the archive, backed by this CLI. See [PLAN.md](PLAN.md) for the roadmap.
