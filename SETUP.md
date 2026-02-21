# Setup

How to set up the Clotho project locally.

## Prerequisites

- Python version installed, see `.python-version` for the minimum required version.

## Steps

1. Set up virtual environment
    1. `uv venv`
    2. `source .venv/bin/activate` (Bash)
    3. `uv sync`
    4. `playwright install` (to install browser engines for Playwright)