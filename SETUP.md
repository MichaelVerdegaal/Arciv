# Setup

How to set up Arciv.

## Requirements

- Python 3.12 or newer (`.python-version` pins the development default).
- [UV](https://docs.astral.sh/uv/) installed for package management

## Install as a uv tool (recommended for usage)

Arciv is a plain CLI tool, no container needed:

```bash
uv tool install git+https://github.com/MichaelVerdegaal/Arciv   # or: uv tool install . from a clone
scrapling install   # browser engine (patchright Chromium) used for fetching
```

After that `arciv` is on your PATH. The archive lives in the OS user data directory by default (see
Configuration below), so no further setup is needed.

## Develop from a clone

1. `uv venv` to set up the virtual environment
2. `source .venv/bin/activate` (Bash)
3. `uv sync`
4. `scrapling install` to install Scrapling's fetcher dependencies (the patchright Chromium
   browser used for HTML fetching).

## Configuration

Everything works out of the box. Point Arciv at your notes by registering them as a source:

```bash
arciv source add "/path/to/your/vault/Daily notes" notes
```

`source add` registers the directory and archives it in one go. Re-sync it any
time with `arciv source update notes`.

Optional override, via environment variable or a `.env` file (see [.env.example](.env.example)):

- `ARCIV_DATA_DIR`: where the SQLite database, archived pages, and logs live. Defaults to the OS
  user data directory (Linux: `~/.local/share/arciv`, Windows: `%LOCALAPPDATA%\arciv`). Set
  `ARCIV_DATA_DIR=data` in `.env` to keep the archive inside the repository when developing from a
  clone.
