"""Pool of recent desktop browser User-Agent strings for rotation.

Each entry should look like a real, up-to-date browser. Outdated or exotic
UAs are *more* suspicious than common ones — blend in, don't stand out.

Update this list every few months when major browser versions ship.
Last updated: 2026-02-23 (Chrome 133, Firefox 135, Edge 133, Safari 18.3).
"""

import random

# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
_WINDOWS_CHROME = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_WINDOWS_EDGE = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
]

_WINDOWS_FIREFOX = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
]

# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------
_MACOS_CHROME = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

_MACOS_SAFARI = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]

_MACOS_FIREFOX = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
]

_MACOS_EDGE = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
]

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
_LINUX_CHROME = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

_LINUX_FIREFOX = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
]

# ---------------------------------------------------------------------------
# Combined pool — weighted towards Chrome/Windows (largest real-world share)
# ---------------------------------------------------------------------------
USER_AGENTS: list[str] = [
    *_WINDOWS_CHROME,
    *_WINDOWS_CHROME,  # double-weight: Chrome+Windows is ~45% of real traffic
    *_WINDOWS_EDGE,
    *_WINDOWS_FIREFOX,
    *_MACOS_CHROME,
    *_MACOS_SAFARI,
    *_MACOS_FIREFOX,
    *_MACOS_EDGE,
    *_LINUX_CHROME,
    *_LINUX_FIREFOX,
]


def random_user_agent() -> str:
    """Return a random User-Agent string from the pool."""
    return random.choice(USER_AGENTS)
