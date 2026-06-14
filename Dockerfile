# syntax=docker/dockerfile:1

# Builder: resolve the environment with uv, then leave uv behind.
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-default-groups --no-editable --group app

# Runtime: plain official Python (no uv, no build tooling) plus Chrome.
FROM python:3.12-slim-trixie

ENV ARCIV_DATA_DIR=/data \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The resolved venv. Same interpreter path as the builder, so it relocates cleanly.
COPY --from=builder /app/.venv /app/.venv

# Patched Chrome plus system libraries, apt metadata wiped in the same layer.
RUN patchright install --with-deps chrome \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/*

 # Copy source code to container
COPY arciv ./arciv
COPY arciv_api ./arciv_api

# Run app
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "arciv_api.app:app", "--host", "0.0.0.0", "--port", "8000"]