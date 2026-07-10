# Setup

MicroRAG runs fully offline after a one-time model download.

## Install

```bash
python -m pip install -e .
```

## Download the model

```bash
python -m microrag download
```

This fetches `MongoDB/mdbr-leaf-ir` (fp32 ONNX) into `.microrag/`.

## Verify

```bash
python -m pytest
```

## Index your notes

```bash
python -m microrag index "C:\Users\Michael.Verdegaal\AppData\Local\arciv\saved"
```

## Query

```bash
python -m microrag query "ONNX runtime throughput" -k 5
```
