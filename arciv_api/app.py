"""FastAPI web app: the server-rendered Arciv UI.

One Python service renders its own HTML (Jinja2) and drives interactivity with
Datastar (``data-*`` attributes that fire requests answered with HTML fragments
or SSE patches). It imports the arciv library directly — it never shells out —
and reads through short-lived read-only connections; the only writes go through
the archive worker started here in the lifespan.

Run locally from the repo root::

    uv run uvicorn arciv_api.app:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .jobs import ArchiveQueue
from .routers import archive, browse, domains, page, rules, sources, status


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the single archive worker, and cancel it on shutdown."""
    queue = ArchiveQueue(config.DB_PATH)
    queue.start()
    app.state.archive = queue
    try:
        yield
    finally:
        await queue.stop()


def create_app() -> FastAPI:
    """Build the app: mount static assets and the page routers."""
    app = FastAPI(title="Arciv", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (browse, page, domains, sources, status, rules, archive):
        app.include_router(module.router)
    return app


app = create_app()
