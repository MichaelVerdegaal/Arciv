# Arciv web app: one Python service that renders the UI and serves the archive.
# Heavier than the CLI because the archive worker drives a real Chrome.
FROM python:3.12-slim-trixie

# Copy UV binaries
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set UV and Arciv environment variables.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    ARCIV_DATA_DIR=/data

WORKDIR /app

# Install dependencies via mount, no project install yet.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --no-editable --group app

# Copy project onto image
COPY arciv ./arciv

# Chrome plus its system libraries for the fetch stage. Cached above the app
# copy so editing the web app does not re-run this heavy step.
RUN uv run patchright install chrome

# Copy web app onto image
COPY arciv_api ./arciv_api

VOLUME ["/data"]
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "arciv_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
