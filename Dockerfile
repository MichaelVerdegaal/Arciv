# Arciv web app: one Python service that renders the UI and serves the archive.
# Heavier than the CLI because the archive worker drives a real Chrome.
FROM python:3.12-slim

# uv for fast, reproducible installs (pinned to the version that wrote uv.lock).
# Installed from PyPI rather than the ghcr image so the build works on networks
# that don't reach GitHub's container registry.
RUN pip install --no-cache-dir uv==0.8.17

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    ARCIV_DATA_DIR=/data

WORKDIR /app

# Install dependencies (and the arciv library) first, for layer caching.
COPY pyproject.toml uv.lock README.md ./
COPY arciv ./arciv
RUN uv sync --frozen

# Chrome plus its system libraries for the fetch stage. Cached above the app
# copy so editing the web app does not re-run this heavy step.
RUN uv run patchright install --with-deps chrome

# The web app itself (templates, built CSS, self-hosted datastar.js).
COPY arciv_api ./arciv_api

VOLUME ["/data"]
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "arciv_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
