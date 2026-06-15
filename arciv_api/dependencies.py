"""Request-scoped dependencies for the API."""

from collections.abc import Iterator

from fastapi import HTTPException

from arciv.core.db import PageDatabase

from . import config


def get_db() -> Iterator[PageDatabase]:
    """Yield a short-lived read-only database connection for one request.

    Per request (not one shared handle) because FastAPI serves the ``def``
    endpoints from a threadpool and SQLite connections are thread-affine. A
    missing database file means the archive was never created, which is a
    setup problem rather than an empty archive, so surface it as 503 instead
    of a raw connection error.
    """
    if not config.DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Archive database not found. Create it with the arciv CLI.",
        )
    with PageDatabase(config.DB_PATH, read_only=True) as db:
        yield db
