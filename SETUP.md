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
5. `playwright install` (to install browser engines for Playwright)

## Post-installation

Run `clotho/update_user_agents.py`.



