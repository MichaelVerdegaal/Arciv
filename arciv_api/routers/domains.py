"""Domains: GET /domains — registered domains with page counts."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from arciv.core.db import PageDatabase

from ..dependencies import get_db
from ..rendering import render

router = APIRouter()


@router.get("/domains", response_class=HTMLResponse)
def domains(db: PageDatabase = Depends(get_db)) -> str:
    """List domains with their page counts, biggest first."""
    return render("domains.html", domains=db.domain_counts())
