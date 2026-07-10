# MicroRag

Local semantic search over markdown files exported from Arciv. Fully offline after a one-time model
download. CPU-only.

## Quick start

```bash
uv sync                                            # install into .venv/
export HF_TOKEN=hf_...                             # recommended: avoids Hugging Face rate limits, faster download
uv run microrag download                           # one-time model fetch (the only networked command)
uv run microrag index "$(arciv db dir)/saved"      # chunk + embed every *.md under the directory
uv run microrag query "ONNX runtime throughput"    # top-5 chunks, best match first
uv run microrag status                             # where the model/index live, chunk count
```

`microrag <command> --help` is the authoritative reference for each command.
See [SETUP.md](SETUP.md) for detailed setup instructions, including how to get an `HF_TOKEN`.

## Conventions

- Results go to stdout; logs, progress, and hints go to stderr — query output pipes cleanly.
- `--json` emits machine-readable output: JSONL for `query`, a single object for `status` and
  the `index` summary.
- `-v`/`-vv` for more log detail, `-q` for errors only, `--version` for the version. Global flags
  work before and after the subcommand.
- Exit codes: 0 on success, 66 when an input is missing (path, model, or index), 2 for usage
  errors.
