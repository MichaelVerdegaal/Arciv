"""FastAPI application: the read API the Astro frontend consumes.

Step 1 is read-only browsing (pages, page detail, domains). The archive job
flow and its background worker come later and will hang off a lifespan
handler added here.

Run locally from the repo root::

    uv run uvicorn arciv_api.app:app --reload
"""

from fastapi import FastAPI

from .routers import domains, pages


def create_app() -> FastAPI:
    """Build the FastAPI app with the read routers mounted."""
    app = FastAPI(title="Arciv API", version="0.1.0")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness check that does not touch the database."""
        return {"status": "ok"}

    app.include_router(pages.router)
    app.include_router(domains.router)
    return app


app = create_app()
