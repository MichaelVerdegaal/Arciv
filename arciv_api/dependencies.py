"""Request-scoped dependencies for the API."""

from collections.abc import Iterator

from arciv.core.db import PageDatabase

from . import config


def get_db() -> Iterator[PageDatabase]:
    """Yield a short-lived read-only database connection for one request.

    Per request (not one shared handle) because FastAPI serves the ``def``
    endpoints from a threadpool and SQLite connections are thread-affine. A
    missing database file means the archive was never created, so initialise
    an empty one (with the schema in place) rather than erroring: the data
    directory advertised by ``arciv db dir`` should always be backed by a
    real database when the frontend is opened.
    """
    if not config.DB_PATH.exists():
        # Opening in write mode creates the file and applies the schema.
        with PageDatabase(config.DB_PATH):
            pass
    with PageDatabase(config.DB_PATH, read_only=True) as db:
        yield db
