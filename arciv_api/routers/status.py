"""Status: GET /status — the pipeline dashboard (counts + failures)."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from arciv.core.db import PageDatabase

from ..dependencies import get_db
from ..rendering import render

router = APIRouter()


@router.get("/status", response_class=HTMLResponse)
def status(db: PageDatabase = Depends(get_db)) -> str:
    """Render pipeline-state counts and a failure summary, like `arciv status`."""
    return render("status.html", counts=db.status_counts(), failures=db.fail_summary())
