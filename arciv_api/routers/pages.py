"""Page read endpoints: the browse list and a single page's detail."""

from fastapi import APIRouter, Depends, HTTPException, Query

from arciv.db import PageDatabase

from .. import config
from ..dependencies import get_db
from ..schemas import PageDetail, PageList, PageSummary

router = APIRouter(prefix="/api", tags=["pages"])


@router.get("/pages", response_model=PageList)
def list_pages(
    db: PageDatabase = Depends(get_db),
    status: str | None = Query(None, description="done, failed, or pending"),
    domain: str | None = Query(None, description="exact registered domain"),
    sort: str = Query("fetched_at", description="fetched_at, title, or word_count"),
    order: str = Query("desc", description="asc or desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PageList:
    """List archived pages for the browse view.

    Includes pending and failed pages, not just parsed ones, so a freshly
    archived page shows up immediately. One extra row is fetched to report
    ``has_more`` without a separate count query.
    """
    try:
        rows = db.list_pages(
            status=status,
            domain=domain,
            sort=sort,
            order=order,
            limit=limit + 1,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    has_more = len(rows) > limit
    items = [PageSummary.from_page(page) for page in rows[:limit]]
    return PageList(items=items, limit=limit, offset=offset, has_more=has_more)


@router.get("/pages/{slug}", response_model=PageDetail)
def get_page(slug: str, db: PageDatabase = Depends(get_db)) -> PageDetail:
    """Return one page by slug: metadata, the markdown body if parsed, and
    the source files that referenced it. 404 if the slug is unknown.

    The markdown lives on disk at ``saved/<slug>/page.md`` and is absent
    until the page is parsed, so it is null for pending and failed pages.
    """
    page = db.get_by_slug(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"No page with slug {slug!r}")
    md_path = config.SAVED_DIR / page.slug / "page.md"
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else None
    sources = db.get_files_for_url(page.url)
    return PageDetail.from_page(page, markdown=markdown, sources=sources)
