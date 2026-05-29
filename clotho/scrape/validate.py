"""Content validation for scraped HTML pages.

Rejects block pages (Cloudflare challenges, CAPTCHAs), suspiciously small
responses, and pathologically large pages before they enter the archive.
"""

import re

MAX_HTML_BYTES = 10 * 1024 * 1024  # 10 MB
MIN_HTML_BYTES = 512

# Titles that indicate a block/challenge page rather than real content
_BLOCK_TITLE_RE = re.compile(
    r"<title[^>]*>\s*("
    r"just a moment"
    r"|attention required"
    r"|access denied"
    r"|403 forbidden"
    r"|you are being redirected"
    r"|please wait"
    r"|checking your browser"
    r"|security check"
    r"|bot verification"
    r"|error \d{3}"
    r")\s*\.{0,3}\s*</title>",
    re.IGNORECASE,
)

# Cloudflare and bot-detection markers in the HTML body
_BLOCK_BODY_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "cf_chl_opt",
    "_cf_chl_tk",
    "enable JavaScript and cookies to continue",
)


def check_html(html: str) -> str | None:
    """Validate fetched HTML before archiving.

    Args:
        html: Raw HTML string from the browser.

    Returns:
        None if the content looks legitimate, or a failure reason string
        explaining why the content should be rejected.
    """
    size = len(html.encode("utf-8"))

    if size > MAX_HTML_BYTES:
        return f"html too large ({size // (1024 * 1024)}MB)"

    if size < MIN_HTML_BYTES:
        return f"html suspiciously small ({size} bytes)"

    # Check title for known block-page patterns
    if _BLOCK_TITLE_RE.search(html[:3000]):
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html[:3000], re.IGNORECASE | re.DOTALL
        )
        title_text = title_match.group(1).strip() if title_match else "unknown"
        return f"block page (title: '{title_text}')"

    # Check for Cloudflare / bot-detection markers
    head = html[:5000]
    for marker in _BLOCK_BODY_MARKERS:
        if marker in head:
            return f"block page (marker: '{marker}')"

    return None
