"""Link discovery on a live page: fetch one URL, return its links, store nothing.

The engine of ``arciv get --no-save``: this module only does the browser
I/O; the DOM extraction itself lives with the other link extractor in
``arciv.core.index.links``.
"""

import asyncio

from scrapling.fetchers import AsyncStealthySession

from arciv.core.index import extract_links

from .fetcher import TIMEOUT_MS, Fetcher


class LinkFetchError(Exception):
    """The page could not be fetched, so no links could be extracted."""


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
