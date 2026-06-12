# Setup

How to set up Clotho.

## Requirements

- Python installed, of version as specified in `.python-version`.
- [UV](https://docs.astral.sh/uv/) installed for package management

## Install as a uv tool (recommended for usage)

Clotho is a plain CLI tool — no container needed:

```bash
uv tool install git+https://github.com/MichaelVerdegaal/Clotho   # or: uv tool install . from a clone
patchright install chrome   # browser engine used for fetching
```

After that `clotho` is on your PATH. Set `CLOTHO_DATA_DIR` (see below) so the archive has a
fixed home regardless of where you run the command.

## Develop from a clone

1. `uv venv` to set up the virtual environment
2. `source .venv/bin/activate` (Bash)
3. `uv sync`
4. `patchright install chrome` to install the browser engine for Playwright. Use `--force`
   flag on existing install error.
5. `uv run clotho --help`

## Configuration

Everything works out of the box — the browser user-agent pool refreshes itself on the first
run. Point Clotho at your notes by registering them as a source:

```bash
clotho add "/path/to/your/vault/Daily notes" notes
clotho index notes
```

Optional override, via environment variable or a `.env` file (see
[.env.example](.env.example)):

- `CLOTHO_DATA_DIR` — where the SQLite database, archived pages, and logs live. Defaults to
  `./data` relative to the working directory, which is fine when running from the repository
  root; set it explicitly when Clotho is installed as a uv tool.
