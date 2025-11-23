# GitHub Copilot Instructions for Personal Knowledge Graph

## Project Overview
Transform Obsidian notes into a queryable graph using HelixDB and LinearRAG. Use Helix SDK's built-in chunking and local embeddings.

**Stack**: Python 3.13, UV, Ruff, Ty, HelixDB

---

## Environment

```bash
## Python Environment

- **Python Version**: 3.13
- **Package Manager**: UV
- **Formatter/Linter**: Ruff
- **Type Checking**: Ty

### Package Management Commands

```bash
# Add dependencies
uv add <package>

# Add dev dependencies  
uv add --dev <package>

# Sync environment
uv sync

# Run scripts
uv run python script.py
uv run pytest
uv run ruff check .
```

## Helix CLI Commands

```bash
# Show help information
helix --help, -h

# Display the CLI version
helix --version, -V

# Add a new instance to an existing Helix project
helix add 

# Validate project configuration and query syntax
helix check

# Compile project queries into executable format
helix compile

# Build and prepare an instance for deployment
helix build

# Deploy or update a running instance
helix push

# Start a stopped instance without rebuilding
helix start

# Stop a running instance
helix stop

# Show the status of all instances in the project
helix status

# Remove unused containers, images, and workspace files
helix prune

# Permanently delete an instance and all its data
helix delete
```

### Dependencies
**Core**: `helix-py`, `spacy`, `anthropic`, `sentence-transformers`
**Utils**: `python-frontmatter`, `python-dateutil`
**Dev**: `pytest`, `ruff`, `ty`

**Note**: Use `sentence-transformers` for local embeddings. Don't add `chonkie` separately - it's built into Helix SDK.

**Note**: Don't add `sentence-transformers` or `chonkie` - they're built into Helix SDK.

---

## Code Style

### Type Hints (Required)
```python
from collections.abc import Sequence

def resolve_entity(
    candidate: str,
    existing: Sequence[Entity],
    threshold: float = 0.85
) -> Entity | None:
    """Clear docstring."""
    ...
```

### Error Handling
```python
class EntityResolutionError(Exception):
    """Specific exception with context."""
    pass

if not candidate.strip():
    raise ValueError(f"Empty entity: {candidate!r}")
```

### Logging
```python
from loguru import logger

logger.info(
    "Entity resolved",
    extra={"candidate": name, "similarity": score}
)
```

---

## Helix SDK Usage

### Client
```python
from helix import Client
db = Client(local=True, port=6969, verbose=True)
```

### Schema (schema.hx)
```rust
N::DailyNote {
    date: Date,
    title: String,
    file_path: String
}

V::NoteEmbedding {
    embedding_type: String
}

E::MENTIONED_IN {
    From: Entity,
    To: DailyNote
}
```

### Queries (queries.hx)
```rust
QUERY add_note(date: Date, title: String, vector: [F64]) =>
    note <- AddN<DailyNote>({date: date, title: title})
    embedding <- AddV<NoteEmbedding>(vector)
    edge <- AddE<HAS_EMBEDDING>::From(note)::To(embedding)
    RETURN note

QUERY search_similar_notes(query_vector: [F64], k: I64) =>
    embeddings <- SearchV<NoteEmbedding>(query_vector, k)
    notes <- embeddings::In<HAS_EMBEDDING>
    RETURN notes
```

---

## Chunking (Use Helix SDK)

```python
from helix import Chunk

# Semantic chunking (best for prose)
chunks = Chunk.semantic_chunk(
    content,
    chunk_size=512,
    threshold=0.8
)

# Recursive chunking (respects markdown structure)
chunks = Chunk.recursive_chunk(content, chunk_size=512)

# Batch processing
contents = [note.content for note in notes]
batch_chunks = Chunk.semantic_chunk(contents)
```

**Available methods**: `semantic_chunk`, `recursive_chunk`, `token_chunk`, `sentence_chunk`, `code_chunk`

---

## Embeddings (Use Helix SDK)

```python
from sentence_transformers import SentenceTransformer

# Use local Qwen embedding model (free, no API costs)
embedder = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# Single text
embedding = embedder.encode(text).astype(float).tolist()

# Batch (more efficient)
texts = ["text1", "text2", "text3"]
embeddings = embedder.encode(texts).astype(float).tolist()

# Cache embeddings
import diskcache
cache = diskcache.Cache("data/cache/embeddings")

def get_or_compute_embedding(text: str) -> list[float]:
    cache_key = hash(text)
    if cache_key in cache:
        return cache[cache_key]
    embedding = embedder.encode(text).astype(float).tolist()
    cache[cache_key] = embedding
    return embedding
```

---

## Testing

```python
import pytest
from helix import Chunk, Client
from sentence_transformers import SentenceTransformer

@pytest.fixture
def embedder():
    return SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

@pytest.fixture
def db():
    db = Client(local=True, port=7777)
    yield db
    db.stop()

def test_semantic_chunking():
    chunks = Chunk.semantic_chunk("Long text...", chunk_size=100)
    assert len(chunks) >= 1
    assert all(len(c) > 0 for c in chunks)

def test_embedding(embedder):
    vec = embedder.encode("Test text").astype(float).tolist()
    assert len(vec) == 768  # Qwen3-Embedding-0.6B dimension
    assert all(isinstance(v, float) for v in vec)
```

---

## Common Patterns

### Incremental Processing
```python
from pathlib import Path
import json
from datetime import datetime

class ProcessingState:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load()
    
    def needs_processing(self, path: Path) -> bool:
        last = self.state.get(str(path))
        if not last:
            return True
        return datetime.fromtimestamp(path.stat().st_mtime) > last
    
    def mark_processed(self, path: Path) -> None:
        self.state[str(path)] = datetime.now()
        self._save()
```

### Batch Processing
```python
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

def process_notes_batch(notes: list[Note]) -> None:
    # 1. Batch chunk
    all_chunks = Chunk.semantic_chunk([n.content for n in notes])
    
    # 2. Batch embed
    flat_chunks = [c for chunks in all_chunks for c in chunks]
    embeddings = embedder.encode(flat_chunks).astype(float).tolist()
    
    # 3. Insert
    for note, chunks in zip(notes, all_chunks):
        db.query("add_note", {...})
```

---

## Key Principles
1. Use Helix SDK chunking (don't import `chonkie` directly)
2. Use local Qwen embeddings (free, no API costs)
3. Type everything
4. Fail fast with specific errors
5. Log with structure
6. Batch operations
7. Cache embeddings