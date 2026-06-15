"""Page detail: GET /page/{slug} and its poll target /page/{slug}/progress."""

from typing import Any

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator

from arciv.core.db import Page, PageDatabase

from .. import config
from ..dependencies import get_db
from ..jobs import Job
from ..rendering import render, render_markdown

router = APIRouter()


def _main_context(page: Page, job: Job | None) -> dict[str, Any]:
    """Context for the shared `#page-main` region (full view and poll patch).

    The markdown file is absent until a page is parsed, so the body is None for
    pending and failed pages. ``phase`` is the live job phase, if any.
    """
    body_html = None
    if page.parsed_at is not None:
        md_path = config.SAVED_DIR / page.slug / "page.md"
        if md_path.exists():
            body_html = render_markdown(md_path.read_text(encoding="utf-8"))
    return {
        "page": page,
        "body_html": body_html,
        "phase": job.phase.value if job is not None else None,
    }


@router.get("/page/{slug}", response_class=HTMLResponse)
def page_detail(
    slug: str, request: Request, db: PageDatabase = Depends(get_db)
) -> HTMLResponse:
    """Render one page; a known-but-unparsed slug shows a polling pending view,
    an unknown slug is a real 404."""
    page = db.get_by_slug(slug)
    if page is None:
        return HTMLResponse(render("not_found.html", slug=slug), status_code=404)
    job = request.app.state.archive.job_for(slug)
    sources = db.get_files_for_url(page.url)
    return HTMLResponse(
        render("page.html", sources=sources, **_main_context(page, job))
    )


def _redirect_to_page(slug: str) -> DatastarResponse:
    """Redirect back to the page so its detail re-renders and the poll picks up
    the freshly enqueued job."""
    return DatastarResponse(
        ServerSentEventGenerator.redirect(f"/page/{quote(slug, safe='')}")
    )


@router.post("/page/{slug}/refetch")
async def page_refetch(
    slug: str, request: Request, db: PageDatabase = Depends(get_db)
) -> DatastarResponse:
    """Re-download this page from the network and re-parse it, then reload.

    A dev aid for trying out URL/parse changes against a real re-fetch. The
    redirect lands back on the detail view, which starts polling on the queued
    job; an unknown slug just reloads into its 404.
    """
    page = db.get_by_slug(slug)
    if page is not None:
        await request.app.state.archive.resubmit(slug, page.url, refetch=True)
    return _redirect_to_page(slug)


@router.post("/page/{slug}/reparse")
async def page_reparse(
    slug: str, request: Request, db: PageDatabase = Depends(get_db)
) -> DatastarResponse:
    """Re-parse this page from the raw file already on disk (no network), then
    reload. The fast loop for trying out parse/cleanup rules."""
    page = db.get_by_slug(slug)
    if page is not None:
        await request.app.state.archive.resubmit(slug, page.url, refetch=False)
    return _redirect_to_page(slug)


@router.get("/page/{slug}/progress")
def page_progress(
    slug: str, request: Request, db: PageDatabase = Depends(get_db)
) -> DatastarResponse:
    """Poll target: patch the `#page-main` region with the current state.

    While a job is active the fragment carries the polling interval; once the
    page is done or failed it does not, so the browser stops polling on its own.
    """
    page = db.get_by_slug(slug)
    if page is None:
        fragment = render("partials/_not_found.html", slug=slug)
    else:
        job = request.app.state.archive.job_for(slug)
        fragment = render("partials/_page_main.html", **_main_context(page, job))
    return DatastarResponse(ServerSentEventGenerator.patch_elements(fragment))
