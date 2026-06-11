# Clotho CLI image: Python + UV + Chrome (for patchright fetching).
#
# Google Chrome only ships for x86_64 Linux, so build with
# --platform=linux/amd64 on ARM hosts (compose.yaml sets this).
FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first so source changes don't bust this layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Chrome plus its system dependencies (the heaviest, most stable layer)
RUN patchright install --with-deps chrome && rm -rf /var/lib/apt/lists/*

COPY . .
RUN uv sync --frozen --no-dev

# Chrome refuses to run as root; data/ is the volume mount point
RUN useradd --create-home clotho \
    && mkdir -p /app/data \
    && chown -R clotho:clotho /app
USER clotho

ENTRYPOINT ["clotho"]
CMD ["--help"]
