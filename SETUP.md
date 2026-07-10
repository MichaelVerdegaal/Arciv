# Setup

MicroRAG runs fully offline after a one-time model download.

## Install

Requires [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv sync
```

This creates `.venv/` with Python 3.12, the runtime dependencies from `uv.lock`, and the dev
tools (`pytest`, `ruff`).

## Set a Hugging Face token (recommended)

Unauthenticated Hugging Face downloads are rate-limited and slower. Create a token with read
scope at <https://huggingface.co/settings/tokens> and export it before downloading:

```bash
export HF_TOKEN=hf_...
```

The token is only used by `microrag download`; every other command is fully offline.

## Download the model

```bash
uv run microrag download
```

This fetches `MongoDB/mdbr-leaf-ir` (fp32 ONNX) into `.microrag/`. This is the only command that
touches the network. If no token is configured, the command warns and continues unauthenticated.

## Verify

```bash
uv run pytest
```

The embedder tests are skipped if the model has not been downloaded yet.

## Index your notes

```bash
uv run microrag index "$(arciv db dir)/saved"   # or any directory containing *.md files
```

Note: the model cache (`.microrag/`) and the Chroma database (`.microrag-db/`) are created
relative to the current working directory, so run `index` and `query` from the repo root.
`microrag status` shows the resolved locations and the current chunk count.

## Query

```bash
uv run microrag query "ONNX runtime throughput" -k 5
```

Results (and only results) go to stdout; add `--json` for one JSON object per result (JSONL).
