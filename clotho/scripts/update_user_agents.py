"""Fetch the latest desktop browser User-Agent strings and save to data/user_agents.txt.

Usage:
    uv run python -m clotho.scripts.cli update-agents
"""

import json
import urllib.request

from loguru import logger

from config import DATA_DIR, configure_logger

MICROLINK_URL = "https://microlink.io/user-agents.json"
OUTPUT_PATH = DATA_DIR / "user_agents.txt"


def fetch_user_agents(url: str = MICROLINK_URL) -> list[str]:
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


def save_user_agents(agents: list[str]) -> None:
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
    agents = fetch_user_agents()
    save_user_agents(agents)
    logger.info(f"Sample: {agents[0]}")


if __name__ == "__main__":
    update_agents()
