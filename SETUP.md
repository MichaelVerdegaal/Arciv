# Setup (developer)

MicroRAG runs fully offline after a one-time model download. This file covers setting up a
development environment. End-users see [README.md](README.md).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Clone and install

```bash
git clone https://github.com/dfg/microrag
cd microrag
uv sync
```

This creates `.venv/` with all runtime dependencies from `uv.lock`, plus the dev tools (`pytest`,
`ruff`).

## Set a Hugging Face token (recommended)

Unauthenticated Hugging Face downloads are rate-limited and slower. Create a token with read scope
at <https://huggingface.co/settings/tokens> and export it:

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

## Install as a tool (optional, for testing outside the project venv)

```bash
uv tool install -e .
```

Now `microrag` is on PATH, using the editable install so source changes are picked up. Uninstall
with `uv tool uninstall microrag` when done.

## Where data lives

All data sits under one home directory, so commands work from anywhere:

- `MICRORAG_HOME` (default `~/.microrag`)
- model files: `$MICRORAG_HOME/model/`
- Chroma database: `$MICRORAG_HOME/db/`

`microrag status` prints the resolved locations and the current chunk count.

## Shell completion (optional)

```bash
eval "$(register-python-argcomplete microrag)"
```

Add to your shell profile to make it permanent.

## Verify

```bash
uv run pytest
```

The embedder tests and the retrieval quality floor are skipped if the model has not been
downloaded yet.

## Retrieval quality evaluation

```bash
uv run python -m evals.run          # human-readable report
uv run python -m evals.run --json   # one JSON object, for diffing runs
```

Indexes the fixture corpus (`evals/corpus/`, deliberately confusable topics) through the real
chunk/embed/store pipeline into a throwaway database, then scores the gold queries in
`evals/queries.json` — paraphrases, not verbatim strings — at the file level: hit@1/3/5 and MRR,
plus every query that did not rank first. Requires the downloaded model. Run it before and after
touching chunking constants or the embedder to see whether retrieval actually improved;
`tests/test_evals.py::test_retrieval_quality_floor` enforces conservative floors in pytest.

## Project structure

```
microrag/
    constants.py    # QUERY_PREFIX, model id, paths, chunk sizes, collection name
    embedder.py     # OnnxEmbedder (loads ONNX model, produces embeddings)
    chunker.py      # heading-aware markdown chunking via chonkie
    store.py        # thin ChromaDB wrapper (upsert, query, ids_by_source)
    indexer.py      # walk files -> chunk -> embed -> upsert
    cli.py          # argparse entrypoints: download, index, query, status
tests/
```

Module boundaries: `embedder` knows nothing about Chroma. `store` knows nothing about ONNX or
tokenizers. `chunker` is pure functions over strings. `cli` is the only place these are wired
together.

## Index your notes

```bash
uv run microrag index ~/notes
```

Re-running `index` is incremental at the chunk level: chunks whose IDs already exist in the store
are skipped without re-embedding, edited files replace only their changed chunks, and chunks whose
source file no longer exists under the indexed directory are pruned (add `--no-prune` to keep
them). A second source directory goes into its own collection:
`index ~/blog --collection blog`.

## Query

```bash
uv run microrag query "ONNX runtime throughput" -k 5
```

Results (and only results) go to stdout; add `--json` for one JSON object per result (JSONL). Use
`-` to read the query text from a pipe: `echo "docker layers" | microrag query -`.
