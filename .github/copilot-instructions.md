name: Clotho
description: Build queryable knowledge graph from Obsidian notes using HelixDB
---

# Personal Knowledge Graph with HelixDB

## Role

You're a Python engineer building a personal knowledge graph. Transform Obsidian markdown notes into a queryable graph
using Helix DB as your graph Database. Write type-safe, batched operations using local embeddings.

**Goal:** Query notes with natural language  
**Examples:** "Problems with models in Q3?", "Resources on Polars performance"

---

## Tech Stack

**Python:** 3.13  
**Tools:** UV (packages), Ruff (lint/format), Ty (type check)  
**Core:** `helix-py`, `sentence-transformers`, `chonkie`, `loguru`

---

## Commands

### UV Package Management

```bash
uv add <package>           # Add dependency
uv add --dev <package>     # Add dev dependency

@@ -32,18 +29,6 @@ uv run pytest              # Run tests
uv run ruff check .        # Lint
```

### Helix CLI

```bash
helix check       # Validate config and queries
helix compile     # Compile queries to executable
helix build       # Build instance
helix push        # Deploy/update instance
helix start       # Start stopped instance
helix stop        # Stop instance
helix status      # Show instance status
helix prune       # Clean unused containers
```

---

## Code Standards

@@ -52,181 +37,39 @@ helix prune # Clean unused containers

```python
from collections.abc import Sequence


def resolve_entity(
        candidate: str,
        existing: Sequence[Entity],
        threshold: float = 0.85
) -> Entity | None:
    """Resolve entity with similarity threshold."""
    ...
```

### Error Handling

```python
class EntityResolutionError(Exception):
    """Entity resolution failed with context."""
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

## Helix SDK Patterns

### Client Setup

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

**Naming conventions:**

- **create** or **link** - Creating/linking nodes and edges
- **get** - Searching/retrieving nodes and edges
- **update** - Updating nodes and edges
- **delete** - Deleting nodes and edges

```rust
QUERY createNote(date: Date, title: String, vector: [F64]) =>
    note <- AddN<DailyNote>({date: date, title: title})
    embedding <- AddV<NoteEmbedding>(vector)
    edge <- AddE<HAS_EMBEDDING>::From(note)::To(embedding)
    RETURN note

QUERY getSimilarNotes(query_vector: [F64], k: I64) =>
    embeddings <- SearchV<NoteEmbedding>(query_vector, k)
    notes <- embeddings::In<HAS_EMBEDDING>
    RETURN notes
```

---

## Chunking (Helix SDK Built-in)

```python
from helix import Chunk

# Semantic chunking (best for prose notes)
chunks = Chunk.semantic_chunk(
    content,
    chunk_size=512,
    threshold=0.8
)

# Recursive chunking (respects markdown structure)
chunks = Chunk.recursive_chunk(content, chunk_size=512)

# Batch processing (much faster)
contents = [note.content for note in notes]
batch_chunks = Chunk.semantic_chunk(contents)
```

**Available:** `semantic_chunk`, `recursive_chunk`, `token_chunk`, `sentence_chunk`, `code_chunk`

---

## Embeddings (Local, Free)

```python
# Helix SDK includes sentence-transformers
from sentence_transformers import SentenceTransformer

# Use local Qwen model (768-dim, no API costs)
embedder = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# Single text
embedding = embedder.encode(text).astype(float).tolist()

# Batch (10x faster for 32+ texts)
texts = ["text1", "text2", "text3"]
embeddings = embedder.encode(texts).astype(float).tolist()
```

**Caching embeddings:**

- Use `diskcache` with hash(text) as key
- Check cache before encoding
- Store after encoding
- Avoids recomputing unchanged notes

---

## Processing Patterns

### Incremental Updates

- Track processed files: `{file_path: last_modified_timestamp}`
- Store in JSON at `data/state/processing.json`
- Compare file `stat().st_mtime` to stored timestamp
- Skip if unchanged, process if newer

### Batch Operations

```python
# ✅ Good - batch everything
all_chunks = Chunk.semantic_chunk([n.content for n in notes])
flat_chunks = [c for chunks in all_chunks for c in chunks]
embeddings = embedder.encode(flat_chunks).astype(float).tolist()

# ❌ Bad - one at a time
for note in notes:
    chunks = Chunk.semantic_chunk(note.content)  # Slow!
    for chunk in chunks:
        embedding = embedder.encode(chunk)  # Very slow!
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
    text = "Long note content..." * 100
    chunks = Chunk.semantic_chunk(text, chunk_size=100)
    assert len(chunks) >= 1
    assert all(len(c) > 0 for c in chunks)


def test_embedding_dimensions(embedder):
    vec = embedder.encode("Test text").astype(float).tolist()
    assert len(vec) == 768  # Qwen3 dimension
```

---

@@ -235,20 +78,15 @@ def test_embedding_dimensions(embedder):

✅ **Always do:**

- Type hint all functions with `collections.abc` types
- Use Helix SDK chunking methods (`Chunk.semantic_chunk`)
- Use local embedding models (sentence-transformers), these are free, and don't require an API
- Batch operations (32+ items minimum)
- Cache embeddings by content hash
- Raise specific exceptions with context
- When writing regex, put the pattern inside a constant with the _RE suffix for the variable name (e.g. `DATE_RE`).

⚠️ **Ask first:**

- Adding dependencies beyond core stack
- Changing schema node/edge types
- Modifying query patterns
- Processing strategy changes

🚫 **Never do:**

- Skip type hints on functions
- Process notes one-by-one (always batch)
- Hardcode file paths
- Use lazy imports inside functions