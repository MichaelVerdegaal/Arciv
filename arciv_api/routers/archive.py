"""Archive: POST /archive — enqueue a fetch+parse job for a submitted URL."""

from fastapi import APIRouter, Request
from datastar_py.fastapi import DatastarResponse, ReadSignals, ServerSentEventGenerator

from ..rendering import alert_patch

router = APIRouter()


def _result_patch(message: str, kind: str) -> DatastarResponse:
    return alert_patch("archive-result", message, kind)


@router.post("/archive")
async def archive(request: Request, signals: ReadSignals) -> DatastarResponse:
    """Archive the URL bound to the Datastar ``url`` signal.

    On success, redirect to ``/page/{slug}`` — the slug exists the instant the
    row is registered, so the destination is real before the fetch starts. A
    URL ``process_url`` rejects gets its skip reason shown instead of a slug
    that would never exist.
    """
    url = ((signals or {}).get("url") or "").strip()
    if not url:
        return _result_patch("Enter a URL to archive.", "warning")

    slug, outcome = await request.app.state.archive.submit(url)
    if slug is None:
        return _result_patch(f"Skipped: {outcome}", "error")
    return DatastarResponse(ServerSentEventGenerator.redirect(f"/page/{slug}"))
