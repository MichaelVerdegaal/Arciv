"""Link discovery on a live page: fetch one URL, return its links, store nothing.

The engine of ``arciv get --no-save``. Extraction runs on the response DOM
via Scrapling's LinkExtractor rather than through trafilatura, whose
boilerplate pruning is trained to strip exactly the link-list pages (a web
book's ToC, a link roundup) this path exists for. Relative links resolve
against the response's final URL, so redirects don't skew the base.
"""

import asyncio
from typing import Any

from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import LinkExtractor

from .fetcher import TIMEOUT_MS, Fetcher


class LinkFetchError(Exception):
    """The page could not be fetched, so no links could be extracted."""


# LinkExtractor's default deny_extensions drops .pdf (and office formats):
# papers are exactly what arciv archives, so extension filtering is disabled.
# canonicalize is off because the downstream get/index pipeline applies the
# rules and canonicalization itself; this stage only discovers.
_EXTRACTOR = LinkExtractor(deny_extensions=(), canonicalize=False)


def extract_links(page: Any) -> list[str]:
    """Absolute, deduped URLs from a fetched page's DOM.

    ``page`` is any Scrapling Selector-family object carrying a base URL
    (a live Response, or a ``Selector(html, url=...)`` in tests).
    """
    return _EXTRACTOR.extract(page)


def fetch_links(url: str, page_timeout: int = TIMEOUT_MS) -> list[str]:
    """Fetch ``url`` through the stealth browser and return its DOM links.

    Nothing is written: no page row, no ``saved/`` folder. Raises
    LinkFetchError with a concise reason when the fetch fails.
    """
    return asyncio.run(_fetch_links_async(url, page_timeout))


async def _fetch_links_async(url: str, page_timeout: int) -> list[str]:
    try:
        async with AsyncStealthySession(
            max_pages=1,
            headless=True,
            disable_resources=True,
            network_idle=True,
            timeout=page_timeout,
            retries=1,
        ) as session:
            response = await session.fetch(url)
    except Exception as e:
        raise LinkFetchError(Fetcher._format_fetch_error(e)) from e
    if response.html_content is None:
        raise LinkFetchError("browser returned no content")
    return extract_links(response)
