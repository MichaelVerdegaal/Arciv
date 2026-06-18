"""Archive orchestration: fetch then parse a batch of URLs in one call.

The ``get`` CLI command and the web app both want the same flow a source
archival needs: take the URLs found by indexing, download them all in one
concurrent batch (the Fetcher shares a single browser context across the
batch, far faster than a browser per URL), then convert the freshly fetched
pages to markdown. This module is that shared step, so neither the CLI nor the
web reimplements the fetch+parse pairing.
"""

from dataclasses import dataclass

from arciv.core.db import Page, PageDatabase
from arciv.core.index import index_source

from .fetch import fetch_urls
from .parse import parse_pending


@dataclass
class ArchiveResult:
    """Outcome of archiving a batch of URLs (or a whole source).

    Attributes:
        urls: The URLs targeted (unique processed URLs for a source).
        fetched: Pages successfully downloaded this run (skips already-fetched
            ones unless refetch was set).
        parsed: How many pages converted to markdown this run.
    """

    urls: list[str]
    fetched: list[Page]
    parsed: int


def archive_urls(
    db: PageDatabase, urls: list[str], refetch: bool = False
) -> ArchiveResult:
    """Fetch the URLs as one batch, then parse what was fetched.

    A refetch resets ``parsed_at`` on the pages it re-downloads, so the plain
    ``parse_pending`` here re-parses them without needing ``reparse``.
    """
    fetched = fetch_urls(db, urls, refetch=refetch)
    parsed = parse_pending(db)
    return ArchiveResult(urls=list(urls), fetched=fetched, parsed=parsed)


def archive_source(db: PageDatabase, name: str) -> ArchiveResult:
    """Index a registered source, then fetch and parse the URLs it found.

    Re-indexing first so a source archived again picks up notes added or
    removed since last time. Raises KeyError if no source with that name is
    registered (propagated from ``index_source``).
    """
    urls = index_source(db, name)
    return archive_urls(db, urls)
