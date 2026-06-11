"""Pool of recent desktop browser User-Agent strings for rotation.

Each entry should look like a real, up-to-date browser. Outdated or exotic
UAs are *more* suspicious than common ones — blend in, don't stand out.

Reads from data/user_agents.txt (one UA per line), which is refreshed by
running: clotho update-agents
"""

import json
import random
import urllib.request
from functools import cache
from pathlib import Path

from loguru import logger

from config import DATA_DIR

UA_FILE = DATA_DIR / "user_agents.txt"
MICROLINK_URL = "https://microlink.io/user-agents.json"


def _fetch_user_agents(url: str = MICROLINK_URL) -> list[str]:
    """Fetch user-agent strings from the microlink API.

    Args:
        url: The API endpoint to query.

    Returns:
        List of user-agent strings.

    Raises:
        ValueError: If the response is missing the 'user' key or it's empty.
        urllib.error.URLError: If the HTTP request fails.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    agents: list[str] = data.get("user", [])
    if not agents:
        raise ValueError(f"No user-agent strings found in response from {url}")
    return agents


def _save_user_agents(agents: list[str]) -> None:
    """Write user-agent strings to UA_FILE, one per line.

    Args:
        agents: List of user-agent strings.
    """
    UA_FILE.parent.mkdir(parents=True, exist_ok=True)
    UA_FILE.write_text("\n".join(agents) + "\n", encoding="utf-8")
    logger.info(f"Saved {len(agents)} user-agents to {UA_FILE}")


def update_user_agents() -> int:
    """Fetch the latest user-agent strings and save them to disk.

    Returns:
        Number of user-agent strings saved.
    """
    agents = _fetch_user_agents()
    _save_user_agents(agents)
    _load_user_agents.cache_clear()
    return len(agents)


@cache
def _load_user_agents(path: Path = UA_FILE) -> list[str]:
    """Load user-agent strings from a text file (one per line).

    Fetches and saves a fresh pool when the file doesn't exist yet. Loaded
    lazily and cached, so importing this module never touches the network
    or filesystem.

    Args:
        path: Path to the user_agents.txt file.

    Returns:
        List of non-empty user-agent strings.

    Raises:
        ValueError: If the UA file exists but contains no user agents.
    """
    if not path.exists():
        agents = _fetch_user_agents()
        _save_user_agents(agents)
    else:
        agents = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    if not agents:
        raise ValueError(f"User-agent file is empty: {path}")

    return agents


def random_user_agent() -> str:
    """Return a random User-Agent string from the pool."""
    return random.choice(_load_user_agents())
