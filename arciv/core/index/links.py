"""Link extraction: URLs out of an input string, whatever its shape.

Two extractors, one job. ``extract_urls`` scans note text (markdown links,
bare URLs) with regexes; ``extract_links`` walks a fetched page's DOM via
Scrapling's LinkExtractor. Everything downstream (rules, canonicalization,
registration) treats their output identically.
"""

import re
from typing import Any

from scrapling.spiders import LinkExtractor

# Splits concatenated URLs on an embedded "https://" boundary.
# Only split when the boundary is not part of a query string value.
_CONCAT_SPLIT_RE = re.compile(r"(?<=[^\s?=&])(?=https?://)")

# Markdown link ``[text](url)``. The balanced-paren group in the URL keeps
# forms like ``(machine_learning)`` intact instead of stopping at the first ")".
_MD_LINK_RE = re.compile(
    r"\[(?:[^\[\]]|\[[^\]]*\])*\]\((https?://(?:\([^\s\)]*\)|[^\s\)])+)\)"
)

# Bare URL not already inside a markdown link's parens.
_BARE_URL_RE = re.compile(r"(?<!\]\()https?://[^\s<>\[\]\"]+")

# LinkExtractor's default deny_extensions drops .pdf (and office formats):
# papers are exactly what arciv archives, so extension filtering is disabled.
# canonicalize is off because the downstream get/index pipeline applies the
# rules and canonicalization itself; this stage only discovers.
_EXTRACTOR = LinkExtractor(deny_extensions=(), canonicalize=False)


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from note text.

    Handles both markdown links ``[text](url)`` and bare URLs. Markdown
    links are matched first to avoid capturing trailing junk after the
    closing paren (e.g. ``[link](https://example.com)seasonalities``).

    Concatenated URLs (multiple ``https://`` in one match) are split.
    Trailing parens are only stripped when unbalanced (more ``)`` than
    ``(``) to preserve URLs like ``Leakage_(machine_learning)``.

    Args:
        text: The note text to scan.

    Returns:
        List of extracted URLs.
    """
    raw_urls: list[str] = []

    # First pass: extract URLs from markdown links [text](url), tried first
    # so trailing junk after the closing paren isn't captured.
    for match in _MD_LINK_RE.finditer(text):
        raw_urls.append(match.group(1))

    # Second pass: bare URLs not inside markdown link parens
    for match in _BARE_URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?'")
        # Strip trailing parens only when unbalanced
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        raw_urls.append(url)

    # Split concatenated URLs (e.g. "...7405d51cd839https://medium.com/...")
    urls: list[str] = []
    for url in raw_urls:
        parts = _CONCAT_SPLIT_RE.split(url)
        urls.extend(p for p in parts if p)

    return urls


def extract_links(page: Any) -> list[str]:
    """Absolute, deduped URLs from a fetched page's DOM.

    ``page`` is any Scrapling Selector-family object carrying a base URL
    (a live Response, or a ``Selector(html, url=...)`` in tests). Relative
    links resolve against that base URL.
    """
    return _EXTRACTOR.extract(page)
