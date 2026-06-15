"""Browse list: GET / — the filterable, sortable, paged archive index."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from arciv.core.db import PageDatabase

from ..dependencies import get_db
from ..rendering import render

router = APIRouter()

_SORTS = {"fetched_at", "title", "word_count"}
_ORDERS = {"asc", "desc"}
_STATUSES = {"done", "fetched", "skipped", "failed", "pending"}
_LIMIT = 50


@router.get("/", response_class=HTMLResponse)
def browse(
    db: PageDatabase = Depends(get_db),
    domain: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("fetched_at"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
) -> str:
    """Render the archive browse page.

    Hand-typed bad values for sort/order/status fall back to defaults rather
    than erroring, so the page is always renderable.
    """
    sort = sort if sort in _SORTS else "fetched_at"
    order = order if order in _ORDERS else "desc"
    status = status if status in _STATUSES else None
    domain = domain or None

    # Fetch one extra row to know whether a next page exists, no count query.
    rows = db.list_pages(
        status=status,
        domain=domain,
        sort=sort,
        order=order,
        limit=_LIMIT + 1,
        offset=(page - 1) * _LIMIT,
    )
    has_more = len(rows) > _LIMIT

    base = {
        k: v
        for k, v in (
            ("domain", domain),
            ("status", status),
            ("sort", sort),
            ("order", order),
        )
        if v
    }
    prev_href = "/?" + urlencode({**base, "page": page - 1}) if page > 1 else None
    next_href = "/?" + urlencode({**base, "page": page + 1}) if has_more else None

    return render(
        "browse.html",
        pages=rows[:_LIMIT],
        page=page,
        prev_href=prev_href,
        next_href=next_href,
        domain=domain or "",
        status=status or "",
        sort=sort,
        order=order,
    )
