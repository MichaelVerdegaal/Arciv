"""Crawl orchestration: archive URLs, then follow their links a fixed depth.

A breadth-first loop over the existing batch pipeline. Each level runs one
``archive_urls`` batch (one shared browser session, then one parse pass);
the next level's frontier is the links of this level's HTML pages, read
from the raw ``page.html`` already saved on disk. No page is fetched twice
for its links, and an interrupted crawl resumes for free on rerun: the
fetch stage skips already-archived pages, whose links are still on disk.

The crawl stays on the registered domains of the seed URLs. Following
every external link at depth 2 would turn "archive this web book" into
"archive the internet"; the cross-domain hop stays the manual pipe
(``arciv get <url> --no-save | arciv get -``), grep-able in the middle.
"""

from loguru import logger
from scrapling.parser import Selector

from arciv.core.db import Page, PageDatabase
from arciv.core.index import extract_links, register_urls
from arciv.core.urls import load_rules, process_url, registered_domain, split_url
from arciv.settings import SAVED_DIR, USER_RULES_PATH

from .archive_pipeline import ArchiveResult, archive_urls


def _crawl_domain(url: str) -> str:
    """The domain a URL counts as for the same-domain restriction."""
    return registered_domain(url) or split_url(url)[0]


def _saved_page_links(page: Page) -> list[str]:
    """DOM links of an archived HTML page, read from its raw file on disk.

    Pages without archived HTML (pending, failed, or PDFs) have no links
    to follow. A missing or unreadable file is logged and treated the same
    way rather than aborting the crawl.
    """
    if not page.fetched or page.content_type != "html":
        return []
    html_path = SAVED_DIR / page.slug / "page.html"
    try:
        html = html_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"Cannot read archived HTML for {page.url}: {e}")
        return []
    return extract_links(Selector(html, url=page.url))


def crawl_urls(
    db: PageDatabase, urls: list[str], depth: int, refetch: bool = False
) -> ArchiveResult:
    """Archive ``urls``, then follow their same-domain links ``depth`` hops.

    Level 0 archives the seeds; each further level archives the not-yet-seen
    links found in the previous level's HTML pages, after the usual rule
    processing, restricted to the registered domains of the seeds. Stops
    early when a level yields no new links.

    Returns one ArchiveResult aggregated across all levels.
    """
    rules = load_rules(USER_RULES_PATH)
    allowed_domains = {_crawl_domain(url) for url in urls}
    seen: set[str] = set(urls)
    frontier = list(urls)
    all_urls: list[str] = []
    all_fetched: list[Page] = []
    total_parsed = 0

    for level in range(depth + 1):
        if level:
            logger.info(f"Crawl depth {level}/{depth}: {len(frontier)} new page(s)")
        result = archive_urls(db, frontier, refetch=refetch)
        all_urls.extend(result.urls)
        all_fetched.extend(result.fetched)
        total_parsed += result.parsed
        if level == depth:
            break

        next_frontier: list[str] = []
        pages = db.get_many(frontier)
        for url in frontier:
            page = pages.get(url)
            if page is None:
                continue
            for link in _saved_page_links(page):
                processed, _ = process_url(link, rules)
                if processed is None or processed in seen:
                    continue
                if _crawl_domain(processed) not in allowed_domains:
                    continue
                seen.add(processed)
                next_frontier.append(processed)
        if not next_frontier:
            logger.info(f"Crawl stopped at depth {level}: no new links to follow")
            break
        frontier = register_urls(db, next_frontier)

    return ArchiveResult(urls=all_urls, fetched=all_fetched, parsed=total_parsed)
