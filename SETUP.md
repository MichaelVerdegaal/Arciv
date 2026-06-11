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

Create a `.env` file in the project root to point Clotho at your Obsidian daily notes:

```
CLOTHO_NOTES_PATH=/path/to/your/vault/Daily notes
```

## Post-installation

Run `uv run clotho update-agents` to download a fresh pool of browser user-agent strings.
