"""Pool of recent desktop browser User-Agent strings for rotation.

Each entry should look like a real, up-to-date browser. Outdated or exotic
UAs are *more* suspicious than common ones — blend in, don't stand out.

Reads from data/user_agents.txt (one UA per line), which is updated by
running: uv run python -m clotho.scripts.update_user_agents
"""

import random
from pathlib import Path
from config import DATA_DIR
import json
import urllib.request

from loguru import logger

from config import configure_logger


_UA_FILE = DATA_DIR / "user_agents.txt"
MICROLINK_URL = "https://microlink.io/user-agents.json"
OUTPUT_PATH = DATA_DIR / "user_agents.txt"


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
    """Write user-agent strings to a text file, one per line.

    Args:
        agents: List of user-agent strings.
    """
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(agents) + "\n", encoding="utf-8")
    logger.info(f"Saved {len(agents)} user-agents to {OUTPUT_PATH}")


def update_agents() -> None:
    """Fetch and save latest user-agent strings."""
    configure_logger()
    agents = _fetch_user_agents()
    _save_user_agents(agents)
    logger.info(f"Sample: {agents[0]}")


def _load_user_agents(path: Path = _UA_FILE) -> list[str]:
    """Load user-agent strings from a text file (one per line).

    Args:
        path: Path to the user_agents.txt file.

    Returns:
        List of non-empty user-agent strings.

    Raises:
        FileNotFoundError: If the UA file doesn't exist yet. Run
            ``uv run python -m clotho.scripts.update_user_agents`` first.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"User-agent file not found: {path}. "
            "Run 'uv run python -m clotho.scripts.update_user_agents' to create it."
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    agents = [line.strip() for line in lines if line.strip()]
    if not agents:
        raise ValueError(f"User-agent file is empty: {path}")
    return agents


USER_AGENTS: list[str] = _load_user_agents()


def random_user_agent() -> str:
    """Return a random User-Agent string from the pool."""
    return random.choice(USER_AGENTS)
