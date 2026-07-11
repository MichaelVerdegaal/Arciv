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

This fetches `MongoDB/mdbr-leaf-ir` (fp32 ONNX) into `$MICRORAG_HOME/model/`. This is the only
command that touches the network. If no token is configured, the command warns and continues
unauthenticated.

## Where data lives

All data sits under one home directory, so commands work from anywhere:

- `MICRORAG_HOME` (default `~/.microrag`)
- model files: `$MICRORAG_HOME/model/`
- Chroma database: `$MICRORAG_HOME/db/`

`microrag status` prints the resolved locations and the current chunk count. Migrating from a
version that stored data relative to the working directory: either re-run `download` and `index`,
or move the old directories into place:

```bash
mkdir -p ~/.microrag
mv .microrag ~/.microrag/model
mv .microrag-db ~/.microrag/db
```

## Shell completion (optional)

Completion for commands and flags via [argcomplete](https://kislyuk.github.io/argcomplete/).
With the venv's `microrag` on your PATH (e.g. after `source .venv/bin/activate`), add to your
shell profile:

```bash
eval "$(register-python-argcomplete microrag)"
```

## Verify

```bash
uv run pytest
```

The embedder tests are skipped if the model has not been downloaded yet.

## Index your notes

```bash
uv run microrag index "$(arciv db dir)/saved"   # or any directory containing *.md files
```

Re-running `index` is incremental: unchanged files are a no-op, edited files replace their old
chunks. Add `--prune` to also drop chunks whose source file no longer exists under the indexed
directory.

## Query

```bash
uv run microrag query "ONNX runtime throughput" -k 5
```

Results (and only results) go to stdout; add `--json` for one JSON object per result (JSONL).
Use `-` to read the query text from a pipe: `echo "docker layers" | microrag query -`.
