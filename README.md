# Clotho

[![CI](https://github.com/MichaelVerdegaal/Clotho/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelVerdegaal/Clotho/actions/workflows/ci.yml)

Clotho is your personal archive for reading material. The blog posts, research papers, and
documentation you collect — linked in your Obsidian daily notes or fed in directly — are fetched
and stored as clean, searchable markdown you can trust years from now. Reading material only: not
books, not videos.

In ancient greek mythology, Clotho is one of the three Fates responsible for spinning the thread
of life. And what is a knowledge archive, if not a web of interconnected threads of knowledge?

## What It Does

Three stages, no writeback into your notes:

1. **Indexing** — extract URLs from your notes
2. **Fetching** — download pages (browser for HTML, direct HTTP for PDFs)
3. **Parsing** — validate and convert to markdown, archived on disk with SQLite tracking state

## Usage

```bash
clotho fetch                          # index your notes, fetch + parse all new URLs
clotho fetch https://example.com/post # fetch specific URLs directly
clotho fetch --dir path/to/notes      # index a different notes directory
clotho fetch --refetch                # re-download already-fetched pages
clotho parse                          # re-parse archived HTML into markdown
```

See [SETUP.md](SETUP.md) for installation, configuration, and the Docker setup.

## Where It's Going

Fetching and parsing are in good shape; the focus now is on getting insight into what's stored —
a web UI for browsing the archive, and collections for grouping related material. See
[PLAN.md](PLAN.md) for the roadmap.
