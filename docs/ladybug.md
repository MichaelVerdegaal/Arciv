# LadybugDB: the Kùzu fork you can actually use

**LadybugDB is a fully functional, actively maintained fork of the Kùzu graph database** that emerged in October 2025 after Apple acquired Kùzu Inc. and archived the original project. For your Clotho knowledge management tool, it checks every box: embedded/serverless mode, Python SDK, Cypher query language, graph traversals, and native HNSW vector indexes. The query syntax is **identical to Kùzu's Cypher dialect** — the fork is primarily a rename (`kuzu` → `lbug`), not a rewrite. Documentation lives at **docs.ladybugdb.com**, the Python package is `pip install real_ladybug`, and the project has shipped six releases in four months (v0.12.0 through v0.15.1 as of March 2026).

---

## Why LadybugDB exists and where to find it

Kùzu was a columnar embedded graph database developed by a University of Waterloo spinoff. In October 2025, Apple acquired Kùzu Inc. and the GitHub repository was archived at v0.11.3. Within weeks, **Arun Sharma** (ex-Facebook, ex-Google) launched LadybugDB as an open-source community fork under the MIT license, branding it "DuckDB for graphs."

The project's key resources:

- **GitHub**: github.com/LadybugDB/ladybug (~273 stars, 5,400+ commits)
- **Docs**: docs.ladybugdb.com (full Cypher manual, client API docs, tutorials)
- **Blog**: blog.ladybugdb.com (four posts covering releases and migration)
- **Website**: ladybugdb.com
- **Discord**: active community server
- **PyPI**: `real_ladybug` (the name `ladybug` was taken by an unrelated environmental simulation library)

The v0.12.0 release blog states explicitly: *"The functionality is equivalent to kuzu v0.11.3. The only change would be to rename kuzu to the correct package name in your language."* Since then, genuinely new features have been added on top.

---

## What LadybugDB adds beyond Kùzu

While the Cypher query syntax remains unchanged, several features have been added post-fork. The **Bolt protocol** (v0.12+) enables Neo4j-compatible clients to connect directly. **Parquet-backed storage** (v0.13) allows tables to live on object storage. **DuckDB foreign tables** let you query DuckDB data as graph nodes and relationships — a meaningful capability for hybrid analytical/graph workloads. A new **LLM extension** generates text embeddings via external provider APIs, and an **Azure extension** adds cloud storage support.

The naming convention follows a global find-and-replace: `kuzu` becomes `lbug` across binaries, headers, file extensions, and namespaces. The database file extension is `.lbug` instead of `.kuzu`. Extension files use `.lbug_extension`. The C++ namespace is `lbug::common::`. This rename is mechanical but comprehensive — when reading Kùzu documentation, simply substitute the names.

| Component | Kùzu | LadybugDB |
|---|---|---|
| Python package | `pip install kuzu` | `pip install real_ladybug` |
| Python import | `import kuzu` | `import real_ladybug as lb` |
| CLI binary | `kuzu` | `lbug` |
| Database file | `my_graph.kuzu` | `my_graph.lbug` |
| Extension format | `.kuzu_extension` | `.lbug_extension` |
| npm package | `kuzu` | `lbug` |
| Rust crate | `kuzu` | `lbug` |

---

## Cypher syntax reference for common operations

LadybugDB uses a **schema-required** Cypher dialect. You must define node and relationship table schemas before inserting data — unlike Neo4j, which is schema-optional. Every node table needs a primary key.

### Creating node and relationship tables

```cypher
-- Node tables with typed properties and primary keys
CREATE NODE TABLE Note (
    id SERIAL PRIMARY KEY,
    title STRING,
    content STRING,
    tags STRING[],
    embedding FLOAT[384],
    created_at TIMESTAMP DEFAULT current_timestamp()
);

CREATE NODE TABLE Topic (
    name STRING PRIMARY KEY,
    description STRING
);

CREATE NODE TABLE Person (
    name STRING PRIMARY KEY,
    email STRING
);

-- Relationship tables specify FROM/TO node types
CREATE REL TABLE References (FROM Note TO Note, context STRING);
CREATE REL TABLE CoversTopic (FROM Note TO Topic, relevance DOUBLE);
CREATE REL TABLE AuthoredBy (FROM Note TO Person, authored_date DATE);

-- Relationship table groups (polymorphic edges)
CREATE REL TABLE GROUP Mentions (
    FROM Note TO Person,
    FROM Note TO Topic,
    mentioned_at TIMESTAMP
);
```

### Inserting data

```cypher
-- Single node
CREATE (:Note {title: 'Graph DB Evaluation', content: 'Comparing LadybugDB...'});

-- Multiple nodes in one statement
CREATE (n:Note {title: 'Project Clotho'}),
       (t:Topic {name: 'Knowledge Management'}),
       (p:Person {name: 'Alice'});

-- Creating relationships between existing nodes
MATCH (n:Note {title: 'Project Clotho'}), (t:Topic {name: 'Knowledge Management'})
CREATE (n)-[:CoversTopic {relevance: 0.95}]->(t);

-- Upsert with MERGE
MERGE (t:Topic {name: 'Graph Databases'})
ON CREATE SET t.description = 'Databases using graph structures'
ON MATCH SET t.description = 'Updated description';
```

### Pattern matching and querying

```cypher
-- Basic pattern match
MATCH (n:Note)-[:CoversTopic]->(t:Topic)
RETURN n.title, t.name;

-- Multi-hop pattern
MATCH (p:Person)<-[:AuthoredBy]-(n:Note)-[:References]->(ref:Note)
RETURN p.name, n.title, ref.title;

-- Aggregation (no explicit GROUP BY — implicit from non-aggregated columns)
MATCH (p:Person)<-[:AuthoredBy]-(n:Note)
RETURN p.name, COUNT(n) AS note_count, COLLECT(n.title) AS titles
ORDER BY note_count DESC;

-- Subquery filtering
MATCH (n:Note)
WHERE EXISTS { MATCH (n)-[:CoversTopic]->(t:Topic {name: 'AI'}) }
RETURN n.title;

-- OPTIONAL MATCH (returns NULL for unmatched patterns)
MATCH (n:Note)
OPTIONAL MATCH (n)-[:AuthoredBy]->(p:Person)
RETURN n.title, p.name;
```

### Graph traversals and path queries

This is where graph databases earn their keep. LadybugDB supports **variable-length paths**, **shortest path algorithms**, and three path semantics (WALK, TRAIL, ACYCLIC).

```cypher
-- Variable-length path: 1 to 5 hops through References
MATCH (start:Note {title: 'Project Clotho'})-[:References*1..5]->(related:Note)
RETURN related.title;

-- With intermediate node/edge filtering
MATCH p = (start:Note)-[:References*1..4 (r, n | WHERE n.created_at > timestamp('2025-01-01'))]->(end:Note)
WHERE start.title = 'Project Clotho'
RETURN end.title, length(p);

-- Shortest path between two nodes
MATCH p = (a:Note)-[:References* SHORTEST 1..10]->(b:Note)
WHERE a.title = 'Note A' AND b.title = 'Note Z'
RETURN nodes(p), length(p);

-- All shortest paths
MATCH p = (a:Note)-[:References* ALL SHORTEST 1..10]->(b:Note)
WHERE a.title = 'Note A' AND b.title = 'Note Z'
RETURN p;

-- ACYCLIC: no repeated nodes in path
MATCH (a:Note)-[:References* ACYCLIC 1..6]->(b:Note)
WHERE a.title = 'Project Clotho'
RETURN DISTINCT b.title;

-- TRAIL: no repeated edges in path
MATCH (a:Note)-[:References* TRAIL 1..6]->(b:Note)
WHERE a.title = 'Project Clotho'
RETURN b.title;
```

Default path semantics is **WALK** (nodes and edges may repeat). The default upper bound when omitted is **30 hops**. Path functions include `nodes(p)`, `rels(p)`, `length(p)`, `is_trail(p)`, and `is_acyclic(p)`.

---

## Vector search with HNSW indexes

LadybugDB inherits Kùzu's **disk-based HNSW vector index**, available through the `vector` extension. This is a native, mutable index that updates automatically on insert/delete — no manual reindexing required. It supports **cosine**, **L2**, **dot product**, and **inner product** distance metrics.

```cypher
-- Load the extension (pre-installed since v0.11.3/v0.12.0)
LOAD EXTENSION vector;

-- Vector properties use fixed-length FLOAT arrays
CREATE NODE TABLE Note (
    id SERIAL PRIMARY KEY,
    title STRING,
    content STRING,
    embedding FLOAT[384]
);

-- Create an HNSW index
CALL CREATE_VECTOR_INDEX(
    'Note',              -- table name
    'note_vec_idx',      -- index name
    'embedding',         -- property name
    metric := 'cosine'   -- distance metric
);

-- k-nearest-neighbor query
CALL QUERY_VECTOR_INDEX('Note', 'note_vec_idx', $query_embedding, 5)
RETURN node.title, distance
ORDER BY distance;

-- Combine vector search with graph traversal
CALL QUERY_VECTOR_INDEX('Note', 'note_vec_idx', $query_embedding, 5)
WITH node AS note, distance
MATCH (note)-[:CoversTopic]->(t:Topic)
RETURN note.title, t.name AS topic, distance
ORDER BY distance;

-- Filtered vector search via projected graphs
CALL PROJECT_GRAPH_CYPHER(
    'recent_notes',
    'MATCH (n:Note) WHERE n.created_at > timestamp("2025-06-01") RETURN n'
);
CALL QUERY_VECTOR_INDEX('Note', 'note_vec_idx', $query_embedding, 5,
    graph_name := 'recent_notes')
RETURN node.title, distance;

-- Ad-hoc similarity without index
MATCH (n:Note)
RETURN n.title, array_cosine_similarity(n.embedding, $query_embedding) AS sim
ORDER BY sim DESC LIMIT 10;
```

A **full-text search** extension (`fts`) using BM25 scoring is also available, and the new **LLM extension** can generate embeddings from text via external API calls directly in Cypher.

---

## Python SDK: installation, connection, and CRUD

The Python package is `real_ladybug` on PyPI. It supports Python 3.10–3.13, ships as a self-contained wheel with the C++ engine statically linked (zero dependencies), and provides both synchronous and asynchronous APIs.

```python
# Installation
# pip install real_ladybug

import real_ladybug as lb

# --- Database and Connection ---
db = lb.Database("clotho.lbug")         # on-disk, single file
# db = lb.Database(":memory:")          # in-memory (ephemeral)
conn = lb.Connection(db)

# --- Schema Definition ---
conn.execute("""
    CREATE NODE TABLE Note (
        id SERIAL PRIMARY KEY,
        title STRING,
        content STRING,
        embedding FLOAT[384],
        created_at TIMESTAMP DEFAULT current_timestamp()
    )
""")
conn.execute("CREATE NODE TABLE Topic (name STRING PRIMARY KEY)")
conn.execute("CREATE REL TABLE CoversTopic (FROM Note TO Topic, relevance DOUBLE)")

# --- Insert Data ---
conn.execute("CREATE (:Note {title: 'Graph DB Notes', content: 'Evaluating LadybugDB...'})")
conn.execute("CREATE (:Topic {name: 'Databases'})")

# Parameterized queries (use $variable syntax)
conn.execute(
    "CREATE (:Note {title: $t, content: $c, embedding: $emb})",
    parameters={"t": "Vector Search", "c": "HNSW indexes...", "emb": [0.1] * 384}
)

# --- Create Relationships ---
conn.execute("""
    MATCH (n:Note {title: 'Graph DB Notes'}), (t:Topic {name: 'Databases'})
    CREATE (n)-[:CoversTopic {relevance: 0.9}]->(t)
""")

# --- Query with Results ---
result = conn.execute("""
    MATCH (n:Note)-[r:CoversTopic]->(t:Topic)
    RETURN n.title, t.name, r.relevance
    ORDER BY r.relevance DESC
""")

# Iterate rows (each row is a list)
for row in result:
    print(row)  # ['Graph DB Notes', 'Databases', 0.9]

# Convert to Pandas DataFrame
df = result.get_as_df()

# Convert to Polars DataFrame
pl_df = result.get_as_pl()

# Convert to PyArrow Table
arrow_tbl = result.get_as_arrow()

# --- Update ---
conn.execute("MATCH (n:Note {title: 'Graph DB Notes'}) SET n.content = 'Updated content'")

# --- Delete ---
conn.execute("MATCH (n:Note {title: 'Old Note'}) DETACH DELETE n")  # node + edges

# --- Bulk Load from DataFrame ---
import pandas as pd
df = pd.DataFrame({"name": ["AI", "Graphs", "Memory"]})
conn.execute("COPY Topic FROM df")

# --- Bulk Load from CSV/Parquet ---
conn.execute('COPY Note FROM "notes.parquet"')

# --- Vector Search in Python ---
conn.execute("LOAD EXTENSION vector")
conn.execute("""
    CALL CREATE_VECTOR_INDEX('Note', 'note_idx', 'embedding', metric := 'cosine')
""")

query_vec = [0.1] * 384  # your embedding
result = conn.execute("""
    CALL QUERY_VECTOR_INDEX('Note', 'note_idx', $qv, 5)
    WITH node AS note, distance
    MATCH (note)-[:CoversTopic]->(t:Topic)
    RETURN note.title, t.name, distance
""", parameters={"qv": query_vec})

for row in result:
    print(row)
```

### Async API

```python
import asyncio
import real_ladybug as lb

async def main():
    db = lb.Database("clotho.lbug")
    conn = lb.AsyncConnection(db, max_concurrent_queries=4)
    await conn.execute("MATCH (n:Note) RETURN n.title")

asyncio.run(main())
```

### User-defined functions

```python
def semantic_similarity(a: float, b: float) -> float:
    return abs(a - b)

conn.create_function("semantic_sim", semantic_similarity,
                     [lb.Type.DOUBLE, lb.Type.DOUBLE], lb.Type.DOUBLE)

# Use in Cypher
conn.execute("MATCH (n:Note) RETURN n.title, semantic_sim(n.score, 0.5)")
```

---

## Project status and fitness for Clotho

LadybugDB is in **active early-stage development** — usable but young. The project launched in October 2025 and has shipped six releases through March 2026, with the primary maintainer (@adsharma) contributing most commits. The contributor base is small (3–4 active developers), but development velocity is high and the codebase inherits **5,400+ commits** of mature C++ engine code from Kùzu's multi-year development backed by a VLDB 2023 paper.

**Current maturity assessment**: The core database engine (storage, query processing, transactions) is production-grade code inherited from Kùzu v0.11.3. The fork-specific additions (Bolt protocol, Parquet storage, DuckDB foreign tables) are newer and less battle-tested. Vector and full-text search extensions work but had bug fixes as recently as v0.12.2. The project should be considered **beta-quality** — reliable for development and personal tools, but not yet proven at production scale under the LadybugDB banner.

For your Clotho knowledge management tool, LadybugDB is a strong fit against your requirements:

- **Embedded mode**: Single `.lbug` file, no server, zero dependencies. One read-write process at a time; multiple connections within that process are thread-safe.
- **Python support**: Full sync/async API with Pandas, Polars, and PyArrow output. UDFs supported.
- **Graph edge traversal**: Variable-length paths, shortest paths, TRAIL/ACYCLIC semantics, path filtering — all native Cypher.
- **Vector search**: Native HNSW index with cosine/L2/dot product metrics, mutable (auto-updates on insert/delete), filterable via projected graphs.
- **Bonus**: LangChain integration exists (`langchain-kuzu`, likely being ported), DuckDB attachment for hybrid queries, and the LLM extension can generate embeddings directly in Cypher.

The main risk is **bus factor** — the project depends heavily on one maintainer. However, the MIT license and strong Kùzu foundation mean the code won't disappear, and the venture-backed entity Ladybug Memory (ladybugmem.ai) signals commercial commitment. Since Kùzu's docs remain accessible at kuzudb.github.io/docs/ and the Cypher syntax is identical, you can use Kùzu's comprehensive documentation as your primary syntax reference, substituting only the package/import names.

## Conclusion

LadybugDB is not vaporware — it's a legitimate, well-documented continuation of Kùzu with an active release cadence. The documentation gap you experienced is real but manageable: **Kùzu's docs are your syntax bible**, and the only LadybugDB-specific knowledge you need is the naming table above and `pip install real_ladybug`. The combination of embedded deployment, native vector indexes, and rich Cypher graph traversals makes it arguably the best-fit option for a Python-native knowledge graph with vector search today. The new features beyond Kùzu (Bolt protocol, Parquet storage, DuckDB foreign tables) are genuine value-adds that signal the fork has ambition beyond mere maintenance.