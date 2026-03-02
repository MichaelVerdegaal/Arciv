"""Pool of recent desktop browser User-Agent strings for rotation.

Each entry should look like a real, up-to-date browser. Outdated or exotic
UAs are *more* suspicious than common ones — blend in, don't stand out.

Reads from data/user_agents.txt (one UA per line), which is updated by
running: uv run python -m clotho.scripts.update_user_agents
"""

import random
from pathlib import Path
from config import DATA_DIR

_UA_FILE = DATA_DIR / "user_agents.txt"


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
