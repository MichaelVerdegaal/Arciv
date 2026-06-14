"""Domain endpoint: page counts per registered domain, for browse facets."""

from fastapi import APIRouter, Depends

from arciv.db import PageDatabase

from ..dependencies import get_db
from ..schemas import DomainCount, DomainList

router = APIRouter(prefix="/api", tags=["domains"])


@router.get("/domains", response_model=DomainList)
def list_domains(db: PageDatabase = Depends(get_db)) -> DomainList:
    """List domains with their page counts, biggest groups first."""
    domains = [DomainCount(domain=name, count=n) for name, n in db.domain_counts()]
    return DomainList(domains=domains)
