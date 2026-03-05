# SurrealDB as an embedded Python graph database

**SurrealDB is a strong fit for Clotho.** The Python SDK (v1.0.8) supports synchronous, embedded, file-persisted operation — meaning you can `pip install surrealdb` and use it like SQLite with no server process, while getting native graph relationships, schema enforcement, and vector similarity search built in. The SDK uses `Surreal("file://clotho.db")` for persistent embedded mode and provides a blocking `Surreal` class alongside an async `AsyncSurreal` class, both with identical APIs. Below is everything you need to build Clotho's data layer.

## The Python SDK supports sync and embedded out of the box

Install with **`pip install surrealdb`** (current stable: **1.0.8**, released Jan 7, 2026). The package ships pre-built binary wheels with the SurrealDB engine compiled in via Rust/PyO3 — no separate server installation required. Python 3.9+ is supported (tested on 3.10–3.13).

The two primary classes mirror each other exactly:

```python
from surrealdb import Surreal       # Blocking/synchronous
from surrealdb import AsyncSurreal  # Async (requires await)
```

Both support four connection modes via URI string:

| URI | Mode | Persistence |
|-----|------|-------------|
| `"memory"` or `"mem://"` | Embedded in-memory | None (lost on close) |
| `"file://path"` or `"surrealkv://path"` | Embedded file-based | Full disk persistence |
| `ws://host:port/rpc` | Remote WebSocket | Server-side |
| `http://host:port` | Remote HTTP | Server-side |

For Clotho, you want **`"file://clotho_data"`** — this creates a SurrealKV directory at the specified path that persists all data across restarts, exactly like SQLite's `.db` file. One important quirk: **even in embedded mode, you must call `signin()` and `use()`** to set credentials and select a namespace/database before any operations.

```python
from surrealdb import Surreal

with Surreal("file://clotho_data") as db:
    db.signin({"username": "root", "password": "root"})
    db.use("clotho", "main")
    # Ready to work — all operations are synchronous
```

The SDK was rewritten for 1.0 (January 2025). Older tutorials referencing `SurrealDB` or `AsyncSurrealDB` classes are outdated — the current API uses `Surreal` and `AsyncSurreal`. The SDK is marked **Production/Stable** on PyPI with 227+ tests across all connection modes. One notable limitation: **transactions and multi-session support only work over WebSocket connections**, not in embedded mode. For a single-user tool like Clotho, this is unlikely to matter.

## Schema definition gives you typed fields, enums, and graph constraints

SurrealDB supports both schemaless and schemafull tables. For Clotho, use **`SCHEMAFULL`** to enforce structure. Define your schema via `db.query()` calls with SurrealQL:

```python
db.query("""
    -- Define tables with strict schemas
    DEFINE TABLE note SCHEMAFULL;
    DEFINE FIELD title       ON note TYPE string;
    DEFINE FIELD content     ON note TYPE option<string>;
    DEFINE FIELD file_path   ON note TYPE string;
    DEFINE FIELD tags        ON note TYPE array<string>;
    DEFINE FIELD note_type   ON note TYPE "obsidian" | "url" | "snippet";
    DEFINE FIELD created_at  ON note TYPE datetime DEFAULT time::now();
    DEFINE FIELD updated_at  ON note TYPE datetime VALUE time::now();
    DEFINE FIELD archived    ON note TYPE bool DEFAULT false;
    DEFINE FIELD embedding   ON note TYPE option<array<float>>;

    -- Unique index on file_path, standard index on tags
    DEFINE INDEX idx_path ON note FIELDS file_path UNIQUE;
    DEFINE INDEX idx_tags ON note FIELDS tags;
    DEFINE INDEX idx_type ON note FIELDS note_type;

    -- Graph edge table: constrain what can link to what
    DEFINE TABLE links_to TYPE RELATION IN note OUT note SCHEMAFULL;
    DEFINE FIELD label      ON links_to TYPE option<string>;
    DEFINE FIELD strength   ON links_to TYPE option<float>;
    DEFINE FIELD created_at ON links_to TYPE datetime DEFAULT time::now();

    -- Vector index for semantic search (384 dims for MiniLM)
    DEFINE INDEX idx_embedding ON note FIELDS embedding
        HNSW DIMENSION 384 DIST COSINE;
""")
```

Key type system features relevant to Clotho:

- **`option<T>`** makes a field nullable/optional (e.g., `option<string>` for content that might not exist yet)
- **Literal unions** act as enums: `"obsidian" | "url" | "snippet"` restricts values to those exact strings
- **`array<string>`** for typed arrays, `array<string, 10>` to cap length, `set<string>` for deduplicated arrays
- **`record<note>`** for explicit foreign-key-style links to another table
- **`DEFAULT time::now()`** sets a value on creation; **`VALUE time::now()`** updates on every mutation
- **`READONLY`** prevents field modification after creation
- Assertions for validation: `DEFINE FIELD age ON person TYPE int ASSERT $value >= 0`

## CRUD operations and graph traversals in Python

The SDK provides both convenience methods and raw `query()` for full SurrealQL access.

### Creating records

```python
from surrealdb import RecordID

# Auto-generated ID
note = db.create("note", {
    "title": "SurrealDB Research",
    "file_path": "projects/clotho/surrealdb.md",
    "tags": ["database", "graph", "python"],
    "note_type": "obsidian",
    "content": "Notes on using SurrealDB as embedded DB..."
})
# Returns: {"id": "note:a8f3kz9m...", "title": "SurrealDB Research", ...}

# Specific string ID (useful for URL-based notes)
db.query("""
    CREATE note:obsidian_research SET
        title = 'SurrealDB Research',
        file_path = 'projects/clotho/surrealdb.md',
        tags = ['database', 'graph'],
        note_type = 'obsidian';
""")
```

### Reading and filtering

```python
# Select all notes
all_notes = db.select("note")

# Select one by ID
one = db.select("note:obsidian_research")

# Complex queries with WHERE
results = db.query(
    "SELECT * FROM note WHERE note_type = $type AND tags CONTAINS $tag",
    {"type": "obsidian", "tag": "database"}
)

# Pagination
results = db.query("SELECT * FROM note ORDER BY created_at DESC LIMIT 20 START 0")
```

### Updating and deleting

```python
# Merge (partial update — only changes specified fields)
db.merge("note:obsidian_research", {"archived": True})

# Full replace
db.update("note:obsidian_research", {
    "title": "Updated Title",
    "file_path": "projects/clotho/surrealdb.md",
    "tags": ["database"],
    "note_type": "obsidian"
})

# Append to array
db.query("UPDATE note:obsidian_research SET tags += 'vector-search'")

# Delete
db.delete("note:obsidian_research")

# Conditional delete
db.query("DELETE note WHERE archived = true AND updated_at < d'2025-01-01'")
```

### Creating graph edges (relationships between notes)

Two approaches — raw SurrealQL `RELATE` and the SDK's `insert_relation()`:

```python
# Approach 1: RELATE via query (most flexible)
db.query("""
    RELATE note:obsidian_research->links_to->note:python_embeddings SET
        label = 'references',
        strength = 0.9;
""")

# Approach 2: insert_relation() method
db.insert_relation("links_to", {
    "in": RecordID("note", "obsidian_research"),
    "out": RecordID("note", "python_embeddings"),
    "label": "references",
    "strength": 0.9
})

# Bulk relations
db.insert_relation("links_to", [
    {"in": RecordID("note", "a"), "out": RecordID("note", "b"), "label": "cites"},
    {"in": RecordID("note", "a"), "out": RecordID("note", "c"), "label": "related"},
])
```

### Querying the graph

SurrealDB's arrow syntax makes graph traversal expressive and concise:

```python
# What does this note link TO?
db.query("SELECT ->links_to->note FROM note:obsidian_research")

# What links TO this note? (reverse traversal)
db.query("SELECT <-links_to<-note FROM note:python_embeddings")

# Get full linked note data (not just IDs)
db.query("SELECT ->links_to->note.* FROM note:obsidian_research")

# Filter edges by label
db.query("""
    SELECT ->links_to[WHERE label = 'references']->note.*
    FROM note:obsidian_research
""")

# Multi-hop: notes linked by notes linked to this one
db.query("SELECT ->links_to->note->links_to->note FROM note:obsidian_research")

# Bidirectional (find all connected notes regardless of direction)
db.query("SELECT <->links_to<->note FROM note:obsidian_research")

# Find all notes within 2 hops (useful for "related notes" feature)
db.query("""
    SELECT ->links_to->note->links_to->note AS second_degree
    FROM note:obsidian_research
""")
```

## Vector search enables semantic note discovery

SurrealDB supports **HNSW indexes** for approximate nearest-neighbor search, using the KNN operator `<|K,DIST|>`. Supported distance metrics: **COSINE**, **EUCLIDEAN**, **MANHATTAN**, **MINKOWSKI**, **HAMMING**, and **CHEBYSHEV**. For text embeddings, cosine distance is standard.

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")  # 384 dimensions

# Store embedding when creating/updating a note
embedding = model.encode("SurrealDB is a multi-model database").tolist()
db.merge("note:obsidian_research", {"embedding": embedding})

# Semantic search: find 5 most similar notes
query_vec = model.encode("graph database for knowledge management").tolist()
results = db.query(
    """
    SELECT title, tags, vector::similarity::cosine(embedding, $vec) AS score
    FROM note
    WHERE embedding <|5,COSINE|> $vec
    ORDER BY score DESC
    """,
    {"vec": query_vec}
)
```

The `<|K,METRIC|>` operator has two modes. **Brute-force** uses a metric name like `<|5,COSINE|>` and scans all records. **HNSW-accelerated** uses a numeric ef parameter like `<|5,100|>` where `100` is the search breadth (higher = more accurate but slower). When an HNSW index exists on the field, the query planner can use it automatically.

```python
# Brute-force exact KNN (works without an index)
db.query("SELECT *, vector::distance::knn() AS dist FROM note WHERE embedding <|5,COSINE|> $vec", {"vec": query_vec})

# HNSW-accelerated approximate KNN (requires HNSW index; ef=100)
db.query("SELECT *, vector::distance::knn() AS dist FROM note WHERE embedding <|5,100|> $vec ORDER BY dist", {"vec": query_vec})
```

**Critical caveat**: the HNSW index is currently an **in-memory structure**. It loads into RAM on first use and has a default cache of **256 MiB** (configurable via `SURREAL_HNSW_CACHE_SIZE` env var). For a personal knowledge base with thousands of notes and 384-dim embeddings, this is more than sufficient — but be aware that after a restart, the first vector query may be slower as the index rebuilds.

## Complete Clotho bootstrap example

Here is a self-contained script that initializes the database, defines the schema, populates sample data, creates relationships, and runs queries — all synchronous, all embedded, no server:

```python
from surrealdb import Surreal, RecordID

# --- Initialize embedded database ---
with Surreal("file://clotho_data") as db:
    db.signin({"username": "root", "password": "root"})
    db.use("clotho", "main")

    # --- Define schema ---
    db.query("""
        DEFINE TABLE note SCHEMAFULL;
        DEFINE FIELD title      ON note TYPE string;
        DEFINE FIELD content    ON note TYPE option<string>;
        DEFINE FIELD file_path  ON note TYPE string;
        DEFINE FIELD tags       ON note TYPE set<string>;
        DEFINE FIELD note_type  ON note TYPE "obsidian" | "url" | "snippet";
        DEFINE FIELD created_at ON note TYPE datetime DEFAULT time::now();
        DEFINE FIELD embedding  ON note TYPE option<array<float>>;

        DEFINE INDEX idx_path ON note FIELDS file_path UNIQUE;
        DEFINE INDEX idx_type ON note FIELDS note_type;

        DEFINE TABLE links_to TYPE RELATION IN note OUT note SCHEMAFULL;
        DEFINE FIELD label     ON links_to TYPE option<string>;
        DEFINE FIELD created_at ON links_to TYPE datetime DEFAULT time::now();
    """)

    # --- Insert notes ---
    db.create("note:surreal", {
        "title": "SurrealDB Research",
        "file_path": "projects/clotho/surrealdb.md",
        "tags": ["database", "graph", "embedded"],
        "note_type": "obsidian",
        "content": "Research on using SurrealDB as Clotho's backend."
    })

    db.create("note:obsidian_api", {
        "title": "Obsidian Plugin API",
        "file_path": "projects/clotho/obsidian-api.md",
        "tags": ["obsidian", "plugin"],
        "note_type": "obsidian"
    })

    db.create("note:surrealdb_docs", {
        "title": "SurrealDB Official Docs",
        "file_path": "https://surrealdb.com/docs",
        "tags": ["database", "reference"],
        "note_type": "url"
    })

    # --- Create graph edges ---
    db.query("""
        RELATE note:surreal->links_to->note:surrealdb_docs SET label = 'references';
        RELATE note:surreal->links_to->note:obsidian_api SET label = 'related';
    """)

    # --- Query: all notes ---
    print("All notes:", db.query("SELECT title, note_type, tags FROM note"))

    # --- Query: graph traversal ---
    print("Surreal links to:",
          db.query("SELECT ->links_to->note.title FROM note:surreal"))

    print("What links to docs?",
          db.query("SELECT <-links_to<-note.title FROM note:surrealdb_docs"))

    # --- Query: filter by tag ---
    print("Database-tagged:",
          db.query("SELECT title FROM note WHERE tags CONTAINS 'database'"))

    # --- Update ---
    db.merge("note:surreal", {"content": "Updated research notes."})

    # --- Delete ---
    db.query("DELETE note WHERE note_type = 'snippet'")
```

## Key limitations and practical considerations

**Transactions** are WebSocket-only — embedded mode does not support `begin_transaction()`. For a single-user desktop app, this is unlikely to be a problem since you won't have concurrent writers, but be aware that multi-statement `query()` calls are not atomic in embedded mode.

**HNSW indexes live in memory.** They persist to disk with the data, but load into RAM when accessed. For Clotho's likely scale (hundreds to low thousands of notes), this is trivially fine. The default 256 MiB cache handles millions of 384-dim vectors.

**SurrealDB 3.0 has launched**, but the Python SDK 1.0.8 targets SurrealDB v2.x. A 2.0.0a1 alpha SDK exists (Feb 2026) that may target 3.0, but it's pre-release. Stick with `pip install surrealdb` (1.0.8) for stability. The embedded engine bundled in the wheel determines which SurrealDB version runs in-process.

**Single-process access only.** The embedded file-based store cannot be opened by multiple processes simultaneously — similar to SQLite's default behavior. If you need Clotho to have a background indexer and a UI process, you'd either need to use a client-server setup or serialize access.

**`insert_relation()` vs `RELATE`**: the SDK's `insert_relation()` method is the Pythonic way to create edges, but `RELATE` via `db.query()` is more flexible since it supports `SET` clauses for edge metadata directly. For Clotho, raw `query()` with `RELATE` is the more practical choice.

The combination of embedded file persistence, synchronous Python API, native graph traversals, and built-in vector search makes SurrealDB a compelling single-dependency data layer for Clotho — replacing what would otherwise require SQLite + a graph layer + a vector store like ChromaDB.