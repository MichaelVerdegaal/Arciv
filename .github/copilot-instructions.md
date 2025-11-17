# GitHub Copilot Instructions for Personal Knowledge Graph

## Project Overview

Personal knowledge base system that transforms 311 daily work notes (Obsidian markdown) into a queryable graph using HelixDB, Python, and GraphRAG techniques. Focus on **simple, maintainable code** that prioritizes clarity over cleverness.

**Architecture**: LinearRAG approach (co-occurrence + semantic similarity, no expensive LLM relation extraction) with semantic entity resolution for deduplication and hybrid retrieval for queries.

---

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

## Helix CLI commands
```bash
# Show help information
helix --help, -h

# Display the CLI version
helix --version, -V

# Add a new instance to an existing Helix project.
helix add 

# Validate project configuration and query syntax.
helix check

# Compile project queries into executable format
helix compile

# Build and prepare an instance for deployment. 
# 1. Validates configuration and queries. 
# 2. Compiles queries. 
# 3. Generates Docker configuration files. 
# 4. Prepares the instance workspace
helix build

# Deploy or update a running instance.
# 1. Builds the instance if needed.
# 2. Creates/updates Docker container for local instances.
# 3. Pushes to cloud provider for remote instances.
# 4. Starts the instance.
helix push

# Start a stopped instance without rebuilding.
helix start

# Stop a running instance.
helix stop

# Show the status of all instances in the project.
helix status

# Remove unused containers, images, and workspace files.
helix prune

# Permanently delete an instance and all its data.
helix delete
```

### Key Dependencies

**Core**:
- `helixdb` - Graph-vector database client
- `spacy` - NLP
- `anthropic` or `openai` - Agent LLM calls

**Utilities**:
- `python-frontmatter` - Parse note metadata
- `markdown` - Parse markdown structure
- `python-dateutil` - Temporal parsing

**Development**:
- `pytest` - Testing
- `ruff` - Linting/formatting
- `ty` - Type checking

---

## Code Style & Conventions

### Type Hints

**Always use comprehensive type hints**. This is a strict requirement.

```python
# ✅ Good - Full type annotations
from collections.abc import Sequence
from typing import TypedDict, Literal

class EntityMatch(TypedDict):
    entity_id: str
    similarity: float
    confidence: float

def resolve_entity(
    candidate: str,
    existing: Sequence[Entity],
    threshold: float = 0.85
) -> EntityMatch | None:
    """Resolve candidate entity against existing entities."""
    ...

# ❌ Bad - Missing or incomplete types
def resolve_entity(candidate, existing, threshold=0.85):
    ...
```

**Type Hint Patterns**:
- Use `list[T]`, `dict[K, V]`, `set[T]` for generic collections (Python 3.12+ syntax)
- Use `collections.abc` types for function parameters (`Sequence`, `Mapping`, `Iterable`)
- Use `TypedDict` for structured dictionaries returned from functions
- Use `Literal` for string/enum-like constants
- Use `None` for optional returns, `| None` for optional parameters
- Use `Protocol` for structural typing when needed
- Avoid `Any` - if type unknown, use `object` or create proper Protocol

### Function Design

**Write small, focused functions with clear contracts**. Each function should do one thing well.

```python
# ✅ Good - Single responsibility, clear types
def extract_wiki_links(content: str) -> list[str]:
    """Extract Obsidian wiki-style links [[Entity]] from markdown content."""
    pattern = r'\[\[(.+?)\]\]'
    return re.findall(pattern, content)

def extract_tags(content: str) -> list[str]:
    """Extract hashtags #topic from markdown content."""
    pattern = r'#([\w-]+)'
    return re.findall(pattern, content)

# ❌ Bad - Does too much, unclear return type
def parse_links_and_tags(content):
    """Get stuff from content."""
    ...  # extracts wiki links, tags, does deduplication, filters, etc.
```

### Naming Conventions

- **Variables**: `snake_case` - descriptive but concise
- **Functions**: `snake_case` - verb phrases (`extract_entities`, `resolve_duplicates`)
- **Classes**: `PascalCase` - noun phrases (`EntityResolver`, `SemanticLinker`)
- **Constants**: `UPPER_SNAKE_CASE` - at module level
- **Private**: Prefix with `_` for internal functions/methods

**Be explicit about domain concepts**:
```python
# ✅ Good - Domain language
note_embedding: NDArray[np.float32]
canonical_entity_id: str
similarity_threshold: float

# ❌ Bad - Generic names
vec: list
result: str
thresh: float
```

### Error Handling

**Fail fast with informative errors**. Don't silently continue on bad data.

```python
# ✅ Good - Specific exceptions with context
class EntityResolutionError(Exception):
    """Raised when entity resolution fails."""
    pass

def resolve_entity(candidate: str, existing: Sequence[Entity]) -> Entity:
    if not candidate.strip():
        raise ValueError(f"Cannot resolve empty entity name: {candidate!r}")
    
    matches = find_similar_entities(candidate, existing)
    if len(matches) > 1 and all(m.similarity > 0.9 for m in matches):
        raise EntityResolutionError(
            f"Ambiguous entity '{candidate}' matches multiple entities: "
            f"{[m.name for m in matches]}"
        )
    
    return matches[0] if matches else create_new_entity(candidate)

# ❌ Bad - Silent failures or generic exceptions
def resolve_entity(candidate, existing):
    try:
        # ... logic
        return result
    except:  # Catches everything!
        return None  # Silently fails
```

### Logging

**Use structured logging with context**. This is critical for debugging graph construction. Use the loguru library.

```python
from loguru import logger

# ✅ Good - Structured with context
logger.info(
    "Entity resolved via semantic blocking",
    extra={
        "candidate": candidate_name,
        "canonical_id": canonical.id,
        "similarity": match_score,
        "method": "embedding_similarity"
    }
)

# For performance tracking
logger.debug(
    "Batch processing complete",
    extra={
        "notes_processed": len(notes),
        "entities_created": new_entity_count,
        "duplicates_blocked": blocked_count,
        "duration_sec": elapsed
    }
)

# ❌ Bad - Unstructured strings
logger.info(f"Resolved {candidate_name}")
```

---

## HelixDB Integration

### Schema Definition

Define schemas in `schemas/v{N}.hql` files. Start minimal, expand via versioning.

```hql
# schemas/v1.hql
schema::1 {
  # Node types
  N::DailyNote {
    date: Date,
    title: String,
    content: String,
    file_path: String
  }
  
  N::Entity {
    id: String,
    name: String,
    type: String,  # Person, Project, Technology, etc.
    description: String
  }
  
  N::VectorEmbedding {
    embedding_type: String,  # full_content, technical_context, resource_context
    vector: Vector<384>  # all-mpnet-base-v2 dimension
  }
  
  # Edge types
  E::MENTIONED_IN {
    From: Entity,
    To: DailyNote,
    section: String  # Which section entity appeared in
  }
  
  E::SIMILAR_TO {
    From: Entity,
    To: Entity,
    similarity: Float,
    computed_at: DateTime
  }
  
  E::HAS_EMBEDDING {
    From: DailyNote,
    To: VectorEmbedding,
    embedding_type: String
  }
}
```

---

## Testing Guidelines

### Test Structure

Write tests that validate **business logic and data transformations**, not framework behavior.

```python
# tests/extractors/test_entities.py
import pytest
from extractors.entities import extract_wiki_links, extract_tags

def test_extract_wiki_links_finds_obsidian_syntax():
    """Wiki links [[Entity]] should be extracted."""
    content = "Working on [[React Dashboard]] with [[Sarah]]."
    
    links = extract_wiki_links(content)
    
    assert links == ["React Dashboard", "Sarah"]

def test_extract_wiki_links_handles_empty_content():
    """Empty content should return empty list."""
    assert extract_wiki_links("") == []

def test_extract_tags_finds_hashtags():
    """Hashtags #topic should be extracted."""
    content = "Debugging #React #performance issue."
    
    tags = extract_tags(content)
    
    assert tags == ["React", "performance"]

def test_extract_tags_ignores_inline_code():
    """Tags in code blocks should be ignored."""
    content = "Use `#include` directive. Also tried #debugging."
    
    # This requires more sophisticated parsing
    tags = extract_tags(content)
    
    # For now, we'll accept this limitation
    assert "debugging" in tags
```

### Test Fixtures

**Use pytest fixtures for common test data**.

```python
# tests/conftest.py
import pytest
from datetime import date
from pathlib import Path

@pytest.fixture
def sample_note_content() -> str:
    """Sample daily note content for testing."""
    return """---
date: 2024-03-15
tags: [react, debugging]
---

## What I Did
- Fixed performance issue in [[React Dashboard]]
- Pair programmed with [[Sarah]]

## Obstacles
- CUDA OOM error with batch size 64

## Resources
- https://react.dev/reference/react/useEffect
- Great article on React optimization
"""

@pytest.fixture
def sample_note_path(tmp_path: Path, sample_note_content: str) -> Path:
    """Create temporary note file for testing."""
    note_path = tmp_path / "2024-03-15.md"
    note_path.write_text(sample_note_content)
    return note_path

# Usage in tests
def test_parse_markdown(sample_note_path: Path):
    """Parser should extract all note sections."""
    parsed = parse_markdown(sample_note_path)
    
    assert parsed.date == date(2024, 3, 15)
    assert "React Dashboard" in parsed.wiki_links
    assert "react" in parsed.tags
```

### Property-Based Testing

**Use Hypothesis for entity resolution edge cases**.

```python
from hypothesis import given, strategies as st

@given(
    entity_name=st.text(min_size=1, max_size=100),
    similarity=st.floats(min_value=0.0, max_value=1.0)
)
def test_semantic_blocking_threshold_properties(entity_name: str, similarity: float):
    """Entity resolution should respect similarity threshold."""
    threshold = 0.85
    
    if similarity >= threshold:
        # Should find match
        result = should_block_creation(entity_name, similarity, threshold)
        assert result is True
    else:
        # Should create new entity
        result = should_block_creation(entity_name, similarity, threshold)
        assert result is False
```

---

## Performance Considerations

### Caching

**Cache embeddings and entity resolutions** to avoid recomputation.

```python
from functools import lru_cache
import diskcache

# In-memory cache for frequent lookups
@lru_cache(maxsize=1000)
def lookup_canonical_entity(alias: str) -> str | None:
    """Fast in-memory lookup of entity aliases."""
    return entity_registry.get(alias)

# Persistent disk cache for embeddings
embedding_cache = diskcache.Cache("data/cache/embeddings")

def get_or_compute_embedding(text: str, embedding_type: EmbeddingType) -> NDArray:
    """Get cached embedding or compute if missing."""
    cache_key = f"{embedding_type}:{hash(text)}"
    
    if cache_key in embedding_cache:
        return embedding_cache[cache_key]
    
    embedding = embedder.encode(text)
    embedding_cache[cache_key] = embedding
    return embedding
```

### Incremental Processing

**Track processing state** to avoid reprocessing unchanged notes.

```python
from datetime import datetime
from pathlib import Path
import json

class ProcessingState:
    """Track which notes have been processed."""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> dict[str, datetime]:
        if self.state_file.exists():
            with open(self.state_file) as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        return {}
    
    def needs_processing(self, note_path: Path) -> bool:
        """Check if note is new or modified since last processing."""
        last_processed = self.state.get(str(note_path))
        if last_processed is None:
            return True
        
        modified_time = datetime.fromtimestamp(note_path.stat().st_mtime)
        return modified_time > last_processed
    
    def mark_processed(self, note_path: Path) -> None:
        """Mark note as processed at current time."""
        self.state[str(note_path)] = datetime.now()
        self._save_state()
    
    def _save_state(self) -> None:
        with open(self.state_file, 'w') as f:
            data = {k: v.isoformat() for k, v in self.state.items()}
            json.dump(data, f, indent=2)

# Usage
state = ProcessingState(Path("data/cache/processing_state.json"))

for note_path in Path("data/notes").glob("*.md"):
    if state.needs_processing(note_path):
        process_note(note_path)
        state.mark_processed(note_path)
```

---

## Documentation

### Docstrings

**Write docstrings for all public functions and classes**. Use Google style.

```python
def resolve_entity(
    candidate: str,
    existing_entities: Sequence[Entity],
    threshold: float = 0.85,
    use_llm_disambiguation: bool = True
) -> Entity | None:
    """Resolve candidate entity against existing entities using semantic similarity.
    
    Uses a three-stage resolution process:
    1. Check canonical entity registry for known aliases
    2. Semantic blocking via embedding similarity
    3. LLM-based disambiguation for ambiguous matches (if enabled)
    
    Args:
        candidate: Entity name to resolve
        existing_entities: Previously extracted entities to check against
        threshold: Similarity threshold for semantic blocking (0.0-1.0)
        use_llm_disambiguation: Whether to use LLM for ambiguous cases
    
    Returns:
        Resolved canonical entity if match found, None if new entity.
        
    Raises:
        ValueError: If candidate is empty or threshold out of range
        EntityResolutionError: If multiple high-confidence matches found
    
    Example:
        >>> entity = resolve_entity("React.js", existing_entities, threshold=0.85)
        >>> print(entity.canonical_name)
        'React'
    """
    ...
```

### README for Each Module

Create `README.md` in each major package explaining purpose and usage.

```markdown
# extractors/

Entity extraction from markdown notes using spaCy NER and custom patterns.

## Extractors

- `entities.py` - Base entity extraction (Person, Project, Technology)
- `patterns.py` - Custom spaCy patterns for domain terms
- `wiki_links.py` - Obsidian wiki-link extraction

## Usage

```python
from extractors.entities import extract_entities

entities = extract_entities(note_content, note_metadata)
```

## Adding New Entity Types

1. Define entity type in `schemas/v{N}.hql`
2. Add extraction pattern in `patterns.py`
3. Update `extract_entities()` to handle new type
4. Add tests in `tests/extractors/test_entities.py`
```

---

## Common Pitfalls to Avoid

### 1. Don't Use LLMs for Graph Construction

```python
# ❌ Bad - Expensive and slow
for e1, e2 in combinations(entities, 2):
    relationship = llm.extract_relationship(e1, e2, context)
    graph.add_edge(e1, relationship, e2)

# ✅ Good - Use co-occurrence + semantic similarity
for entity in entities:
    graph.add_edge(entity, note, edge_type="MENTIONED_IN")

# Add semantic edges separately (offline batch)
compute_semantic_similarities(all_entities)
```

### 2. Don't Create Entities Without Resolution

```python
# ❌ Bad - Creates duplicates
def extract_and_create(text: str) -> list[Entity]:
    raw_entities = spacy_extract(text)
    return [Entity(name=e) for e in raw_entities]  # Duplicates!

# ✅ Good - Resolve first
def extract_and_create(text: str, registry: CanonicalEntityRegistry) -> list[Entity]:
    raw_entities = spacy_extract(text)
    return [get_or_create_entity(e, registry) for e in raw_entities]
```

### 3. Don't Generate Single Embeddings

```python
# ❌ Bad - One embedding fits all queries poorly
note_embedding = embedder.encode(note.full_content)

# ✅ Good - Specialized embeddings for different query types
embeddings = NoteEmbeddings(
    full_content=embedder.encode(note.content),
    technical_context=embedder.encode(technical_text),
    resource_context=embedder.encode(resource_text)
)
```

### 4. Don't Block on Async Operations

```python
# ❌ Bad - Sequential processing
for note in notes:
    embedding = await embedder.encode(note.content)  # Slow!
    
# ✅ Good - Batch async operations
embeddings = await asyncio.gather(*[
    embedder.encode(note.content) for note in notes
])
```

---

## Key Principles Summary

1. **Simple over sophisticated** - LinearRAG over complex relation extraction
2. **Type everything** - Comprehensive type hints, no `Any`
3. **Fail fast** - Explicit errors over silent failures
4. **Log with structure** - Context-rich logging for debugging
5. **Cache aggressively** - Embeddings, entity resolutions, LLM responses
6. **Batch operations** - Don't process one item at a time
7. **Test data flow** - Validate transformations, not framework code
8. **Document intent** - Why decisions were made, not just what code does

---

## References

- HelixDB docs: https://docs.helix-db.com
- LinearRAG paper: https://arxiv.org/abs/2510.10114
- Semantic entity resolution: https://blog.graphlet.ai/the-rise-of-semantic-entity-resolution-45c48d5eb00a

**Philosophy**: When in doubt, choose the simpler approach. Complex abstractions should emerge from real needs, not anticipated ones.