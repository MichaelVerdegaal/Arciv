# Clotho
Clotho is your personal knowledge framework that helps you organize, retrieve, and leverage insights from your Obsidian markdown notes using natural language queries.

In ancient greek mythology, Clotho is one of the three Fates responsible for spinning the thread of life. And what is a knowledge framework, if not a web of interconnected threads of knowledge?

## What It Does

Archives the web pages you link in your Obsidian daily notes as searchable markdown. Three stages:
indexing (extract URLs from notes), fetching (download pages), parsing (convert to markdown).

## Usage

```bash
clotho fetch                          # index your notes, fetch + parse all new URLs
clotho fetch https://example.com/post # fetch specific URLs directly
clotho fetch --dir path/to/notes      # index a different notes directory
clotho fetch --refetch                # re-download already-fetched pages
clotho parse                          # re-parse archived HTML into markdown
```

See [SETUP.md](SETUP.md) for installation and configuration.