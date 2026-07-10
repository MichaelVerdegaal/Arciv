# MicroRag

Local semantic search over markdown files exported from Arciv. Fully offline after a one-time model
download. CPU-only.

## Quick start

```bash
uv sync
uv run microrag download
uv run microrag index "C:\Users\Michael.Verdegaal\AppData\Local\arciv\saved"
uv run microrag query "ONNX runtime throughput" -k 5
```

See [SETUP.md](SETUP.md) for detailed setup instructions.
