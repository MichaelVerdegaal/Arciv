# Setup
How to set up the Clotho project locally.


## Installation
### Requirements

- Python installed, of version as specified in `.python-version`.
- [UV](https://docs.astral.sh/uv/) installed for package management
- A residential proxy provider
- Docker installted for visualizing the graph database with Ladybug Explorer (optional)

## Steps
1. Set up virtual environment
2. `uv venv`
3. `source .venv/bin/activate` (Bash)
4. `uv sync`
5. `playwright install` (to install browser engines for Playwright)

## Post-installation
### Scraping notes
Run `clotho/update_user_agents.py`.

### Visualize graph DB
Run this command in the terminal, replacing the path with the path to your local `clotho.lbug` file:
```shell
docker run -p 8000:8000 -v "A:\Software\Coding projects\Clotho":/database -e LBUG_FILE=clotho.lbug --rm ghcr.io/ladybugdb/explorer:latest
```


