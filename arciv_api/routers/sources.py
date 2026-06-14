"""Sources: GET /sources — registered sources with page counts."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from arciv.db import PageDatabase

from ..dependencies import get_db
from ..rendering import render

router = APIRouter()


@router.get("/sources", response_class=HTMLResponse)
def sources(db: PageDatabase = Depends(get_db)) -> str:
    """List registered sources, each with how many distinct pages it indexed."""
    return render("sources.html", sources=db.list_sources_with_counts())
