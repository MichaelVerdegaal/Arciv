# Setup

How to set up the Clotho project locally.


## Installation
### Requirements

- Python installed, of version as specified in `.python-version`.
- [UV](https://docs.astral.sh/uv/) installed for package management
- A residential proxy provider

## Steps
1. Set up virtual environment
2. `uv venv`
3. `source .venv/bin/activate` (Bash)
4. `uv sync`
5. `patchright install chrome` to install browser engine for Playwright. Use `--force` flag on
   existing install error.

## Post-installation

Run `clotho/scripts/update_user_agents.py`.
