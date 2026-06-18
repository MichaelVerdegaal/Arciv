"""Sources: list, view, add, re-archive, and remove registered sources.

``GET /sources`` lists registered sources (read-only connection); ``GET
/sources/{name}`` shows one source's indexed files and the links found in them.
Adding, re-archiving, and removing are writes, so they open a short-lived
read-write connection inside a thread (sqlite handles are thread-affine). Adding
and re-archiving register/re-index synchronously (fast, no network) so the files
and links show immediately, then hand the slow fetch+parse to the archive
worker's background batch.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
    ServerSentEventGenerator,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from arciv.core.db import Page, PageDatabase, Source
from arciv.core.index import index_source

from .. import config
from ..dependencies import get_db
from ..rendering import alert_patch, render

router = APIRouter()


def _result_patch(message: str, kind: str) -> DatastarResponse:
    """Patch the inline #source-result alert (used for validation problems)."""
    return alert_patch("source-result", message, kind)


@router.get("/sources", response_class=HTMLResponse)
def sources(request: Request, db: PageDatabase = Depends(get_db)) -> str:
    """List registered sources, each with how many distinct pages it indexed."""
    rows = db.list_sources_with_counts()
    queue = request.app.state.archive
    archiving = {source.name for source, _ in rows if queue.is_archiving(source.name)}
    return render("sources.html", sources=rows, archiving=archiving)


@router.get("/sources/{name}", response_class=HTMLResponse)
def source_detail(
    name: str, request: Request, db: PageDatabase = Depends(get_db)
) -> HTMLResponse:
    """Show a source's indexed files and the links found in each of them."""
    source = db.get_source(name)
    if source is None:
        body = render(
            "not_found.html",
            message=f"No source named '{name}'.",
            back_href="/sources",
            back_label="Back to sources",
        )
        return HTMLResponse(body, status_code=404)

    # Group the source's links by the note file they were found in, so the view
    # mirrors how they were indexed: file -> the pages it linked to.
    files: dict[str, list[Page]] = {}
    for file_path, page in db.list_source_links(name):
        files.setdefault(file_path, []).append(page)

    return HTMLResponse(
        render(
            "sources_detail.html",
            source=source,
            files=files,
            archiving=request.app.state.archive.is_archiving(name),
        )
    )


@router.post("/sources")
async def add_source(request: Request, signals: ReadSignals) -> DatastarResponse:
    """Register a source from the Datastar signals, index it, then archive it.

    Validation problems are shown inline so the entered values are not lost. On
    success the source is indexed synchronously (its files/links show at once)
    and the fetch+parse runs in the background; the page redirects to the new
    source's detail view.
    """
    data = signals or {}
    name = (data.get("name") or "").strip()
    path = (data.get("path") or "").strip()

    if not name:
        return _result_patch("Enter a name for the source.", "error")
    if not path:
        return _result_patch("Enter the directory path to index.", "error")
    directory = Path(path).expanduser()
    if not directory.is_dir():
        return _result_patch(f"Not a directory on the server: {path}", "error")

    try:
        urls = await asyncio.to_thread(
            _register_and_index, name, str(directory.resolve())
        )
    except ValueError as exc:
        return _result_patch(str(exc), "error")

    request.app.state.archive.archive_source_bg(name, urls)
    return DatastarResponse(
        ServerSentEventGenerator.redirect(f"/sources/{quote(name, safe='')}")
    )


@router.post("/sources/{name}/archive")
async def rearchive_source(name: str, request: Request) -> DatastarResponse:
    """Re-index a source (picking up note changes), then re-archive it."""
    try:
        urls = await asyncio.to_thread(_reindex, name)
    except KeyError:
        return _result_patch(f"No source named '{name}'.", "error")
    request.app.state.archive.archive_source_bg(name, urls)
    return DatastarResponse(
        ServerSentEventGenerator.redirect(f"/sources/{quote(name, safe='')}")
    )


@router.post("/sources/{name}/delete")
async def delete_source(name: str) -> DatastarResponse:
    """Unregister a source (its archived pages are kept), then reload the list."""
    await asyncio.to_thread(_remove, name)
    return DatastarResponse(ServerSentEventGenerator.redirect("/sources"))


def _register_and_index(name: str, path: str) -> list[str]:
    """Register the source and index it; return the URLs found.

    Raises ValueError if the name is already taken (surfaced inline by the
    caller so the user can pick another).
    """
    source = Source(
        name=name, path=path, added_at=datetime.now(timezone.utc).isoformat()
    )
    with PageDatabase(config.DB_PATH) as db:
        if not db.add_source(source):
            raise ValueError(f"A source named '{name}' already exists.")
        return index_source(db, name)


def _reindex(name: str) -> list[str]:
    """Re-index a registered source; return the URLs found (raises KeyError if
    the source is unknown)."""
    with PageDatabase(config.DB_PATH) as db:
        return index_source(db, name)


def _remove(name: str) -> None:
    with PageDatabase(config.DB_PATH) as db:
        db.remove_source(name)
