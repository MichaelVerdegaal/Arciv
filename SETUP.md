# Setup

How to set up the Clotho project locally.


## Installation
### Requirements

- Python installed, of version as specified in `.python-version`.
- [UV](https://docs.astral.sh/uv/) installed for package management

## Steps
1. `uv venv` to set up the virtual environment
2. `source .venv/bin/activate` (Bash)
3. `uv sync`
4. `patchright install chrome` to install browser engine for Playwright. Use `--force` flag on
   existing install error.

## Configuration

Create a `.env` file in the project root (see [.env.example](.env.example)) to point Clotho at
your Obsidian daily notes:

```
CLOTHO_NOTES_PATH=/path/to/your/vault/Daily notes
```

Alternatively, pass `--dir` to `clotho fetch` per run. Everything else works out of the box —
the browser user-agent pool refreshes itself on the first run.

Optional overrides:

- `CLOTHO_DATA_DIR` — where the SQLite database, archived pages, and logs live. Defaults to
  `data/` in the repository root. Useful when the archive should live outside the repo (e.g. a
  Docker volume or a synced drive).

## Docker

The image packages Python, UV, and the Chrome browser used for fetching. The archive itself
stays on the host: `./data` is mounted into the container, and `CLOTHO_NOTES_PATH` from `.env`
is mounted read-only at `/notes`.

```bash
docker compose build
docker compose run --rm clotho fetch                          # full pipeline
docker compose run --rm clotho fetch https://example.com/post # specific URLs
docker compose run --rm clotho parse                          # re-parse archived HTML
```

The image targets `linux/amd64` because Google Chrome isn't published for ARM Linux; on Apple
Silicon hosts Docker runs it under emulation.
