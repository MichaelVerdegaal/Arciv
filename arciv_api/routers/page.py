"""Page detail: GET /page/{slug} and its poll target /page/{slug}/progress."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator

from arciv.db import Page, PageDatabase

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
