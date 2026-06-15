"""Pool of recent desktop browser User-Agent strings for rotation.

Each entry should look like a real, up-to-date browser. Outdated or exotic
UAs are *more* suspicious than common ones; blend in, don't stand out.

The pool is refreshed from the microlink API once per process (triggered by
the first Fetcher init) and cached in data/user_agents.txt. When the refresh
fails (e.g. offline), the cached file is used; a small built-in list is the
last resort. Loading never raises; scraping shouldn't die over a UA refresh.
"""

import json
import random
import urllib.request
from functools import cache

from loguru import logger

from arciv.settings import DATA_DIR

UA_FILE = DATA_DIR / "user_agents.txt"
MICROLINK_URL = "https://microlink.io/user-agents.json"

# Last resort when the refresh fails and no cached file exists. Only raw
# HTTP (PDF) downloads use this pool; the browser sends real Chrome's UA.
_FALLBACK_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
)


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
    with urllib.request.urlopen(request, timeout=10) as response:
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


@cache
def load_user_agents() -> list[str]:
    """Load the User-Agent pool, refreshing it from the network once.

    Tries a fresh fetch first so the pool stays current, then falls back to
    the cached file, then to the built-in list. Cached, so the refresh runs
    at most once per process.

    Returns:
        List of user-agent strings (never empty).
    """
    try:
        agents = _fetch_user_agents()
        _save_user_agents(agents)
        return agents
    except (OSError, ValueError) as e:
        logger.warning(f"User-agent refresh failed ({e}); falling back to cache")

    if UA_FILE.exists():
        agents = [
            line.strip()
            for line in UA_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if agents:
            return agents

    logger.warning("No cached user agents; using built-in fallback pool")
    return list(_FALLBACK_USER_AGENTS)


def random_user_agent() -> str:
    """Return a random User-Agent string from the pool."""
    return random.choice(load_user_agents())
