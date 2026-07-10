# Setup

MicroRAG runs fully offline after a one-time model download.

## Install

Requires [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv sync
```

This creates `.venv/` with Python 3.12, the runtime dependencies from `uv.lock`, and the dev
tools (`pytest`, `ruff`).

## Download the model

```bash
uv run microrag download
```

This fetches `MongoDB/mdbr-leaf-ir` (fp32 ONNX) into `.microrag/`. This is the only command that
touches the network.

## Verify

```bash
uv run pytest
```

The embedder tests are skipped if the model has not been downloaded yet.

## Index your notes

```bash
uv run microrag index "C:\Users\Michael.Verdegaal\AppData\Local\arciv\saved"
```

Note: the model cache (`.microrag/`) and the Chroma database (`.microrag-db/`) are created
relative to the current working directory, so run `index` and `query` from the repo root.

## Query

```bash
uv run microrag query "ONNX runtime throughput" -k 5
```
