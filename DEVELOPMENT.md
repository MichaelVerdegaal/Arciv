# Development

Setting up a development environment for MicroRAG. End-users see [README.md](README.md); for how the
code fits together, see [ARCHITECTURE.md](ARCHITECTURE.md).

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

Unauthenticated Hugging Face downloads are rate-limited and slower. Create a token with read scope at
<https://huggingface.co/settings/tokens> and export it:

```bash
export HF_TOKEN=hf_...
```

The token is only used by `microrag download`; every other command is fully offline.

## Download the model

```bash
uv run microrag download
```

This fetches `MongoDB/mdbr-leaf-ir` (fp32 ONNX) into `$MICRORAG_HOME/model/`, the only command that
touches the network. If no token is configured, the command warns and continues unauthenticated.

## Run commands from the source tree

Inside the project venv, prefix any command with `uv run`:

```bash
uv run microrag index ~/notes
uv run microrag query "ONNX runtime throughput" -k 5
```

See [README.md](README.md) for the full command surface; `microrag <command> --help` is the
authoritative per-command reference.

## Install as a tool (optional)

To test outside the project venv:

```bash
uv tool install -e .
```

Now `microrag` is on PATH, using the editable install so source changes are picked up. Uninstall with
`uv tool uninstall microrag` when done.

## Where data lives

All data sits under one home directory, so commands work from anywhere:

- `MICRORAG_HOME` (default `~/.microrag`)
- model files: `$MICRORAG_HOME/model/`
- Chroma database: `$MICRORAG_HOME/db/`

`microrag status` prints the resolved locations and the current chunk count.

## Shell completion (optional)

Typer generates completion for your shell:

```bash
microrag --install-completion        # writes the completion script and prints how to enable it
microrag --show-completion           # or print it to stdout to inspect/source yourself
```

`--install-completion` detects your shell (bash, zsh, fish, PowerShell) and updates the right
profile; restart the shell afterwards to make it permanent.

## Tests and lint

```bash
uv run ruff check --fix . && uv run ruff format . && uv run pytest -x -q --tb=short
```

This is the same gate CI runs on every push (`.github/workflows/ci.yml`). The embedder tests and the
retrieval quality floor are skipped if the model has not been downloaded yet.

## Retrieval quality evaluation

```bash
uv run python -m evals.run          # human-readable report
uv run python -m evals.run --json   # one JSON object, for diffing runs
```

Indexes the fixture corpus (`evals/corpus/`, deliberately confusable topics) through the real
chunk/embed/store pipeline into a throwaway database, then scores the gold queries in
`evals/queries.json` (paraphrases, not verbatim strings) at the file level: hit@1/3/5 and MRR, plus
every query that did not rank first. Requires the downloaded model. Run it before and after touching
chunking constants or the embedder to see whether retrieval actually improved;
`tests/test_evals.py::test_retrieval_quality_floor` enforces conservative floors in pytest.
