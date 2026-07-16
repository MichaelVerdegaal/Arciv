# MicroRag

Local semantic search over markdown files. Fully offline after a one-time model download. CPU-only.

## Quick start

```bash
uv tool install microrag                                            # or from git: uv tool install git+...
export HF_TOKEN=hf_...                                              # recommended: avoids Hugging Face rate limits
microrag download                                                    # one-time model fetch (the only networked command)
microrag index ~/notes                                               # chunk + embed every *.md under the directory
microrag query "ONNX runtime throughput"                             # top-5 chunks, best match first
microrag status                                                      # where the model/index live, chunk count
```

`microrag <command> --help` is the authoritative reference for each command. See
[SETUP.md](SETUP.md) for developer setup instructions.

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install microrag
```

No PyPI account needed — install directly from the repo:

```bash
uv tool install git+https://github.com/dfg/microrag@v0.3.0
```

Or from a local clone during development:

```bash
git clone https://github.com/dfg/microrag
cd microrag
uv tool install -e .
```

After installation, `microrag` is on your PATH with no venv activation needed.

## Conventions

- All data lives under `MICRORAG_HOME` (default `~/.microrag`), so commands work from any directory.
- Results go to stdout; logs, progress, and hints go to stderr — query output pipes cleanly.
  `microrag query -` reads the query text from stdin.
- Re-indexing is incremental: unchanged files are a no-op, edited files replace their old chunks,
  and `index --prune` removes chunks for deleted files.
- An index is pinned to the first root directory it was built from; indexing a different root is
  refused (use a separate `MICRORAG_HOME` per notes collection, or delete the DB dir to rebuild).
- `query -c N` also shows the N neighboring chunks around each result for more context.
- `--json` emits machine-readable output: JSONL for `query`, a single object for `status` and the
  `index` summary.
- `-v`/`-vv` for more log detail, `-q` for errors only, `--version` for the version. Global flags
  work before and after the subcommand. Tab completion via argcomplete (see SETUP.md).
- Exit codes: 0 on success, 64 for usage errors we detect, 66 when an input is missing (path, model,
  or index), 69 when the model download fails, 2 for argparse errors.
