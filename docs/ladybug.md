---
title: Cypher manual
description: Cypher query language reference for LadybugDB — syntax, data types, conventions, and patterns.
---

Cypher is a declarative graph query language for the property graph model. LadybugDB implements openCypher's standard predicates and expressions.

## SQL ↔ Cypher mapping

| SQL | Cypher |
|---|---|
| `SELECT`/`FROM`/`WHERE` | `MATCH`/`WHERE`/`RETURN` |
| `INSERT`/`UPDATE`/`DELETE` | `CREATE`/`SET`/`DELETE` |

Key differences from SQL:
- Joins use graph pattern syntax: `MATCH (a:Person)-[:Follows]->(b:Person)`
- Variable-length joins use Kleene star: `(a)-[:Follows*1..5]->(b)`
- No explicit `GROUP BY` — grouping is implicit from non-aggregated columns in `RETURN`

## Statements and clauses

A **statement** is a complete query ending with `;`. A **clause** is a part of a statement (`MATCH`, `RETURN`, `WHERE`, etc.). Statements can span multiple lines — the parser ignores leading/trailing whitespace and looks only for `;` to mark completion.

Multiple statements can be executed sequentially by separating them with `;`:

```cypher
MATCH (p:Person) WHERE p.age <= 18 RETURN p.name;
MATCH (p:Person) WHERE p.age > 18 RETURN p.name;
```

## Syntax rules

### Case insensitivity

Cypher is case-insensitive for table names, column names, keywords, and variable names. `Person` and `person` are the same table; `MATCH (a)` and `match (a)` are equivalent.

### Naming conventions

| Type | Convention | Do | Don't |
|---|---|---|---|
| Node tables | CamelCase | `CarOwner` | `car_owner` |
| Relationship tables | CamelCase or UPPER_SNAKE | `IsPartOf` / `IS_PART_OF` | `isPartOf` |

Rules: must begin with an alphabetic character (unicode OK), no whitespace or special chars except underscores, must not begin with a number.

### Parameters

Use `$name` syntax in queries, pass values at runtime via the `parameters=` dict. Parameters work for **values only** — not table names, property names, or structural query parts.

```cypher
MATCH (n:Note) WHERE n.title = $title RETURN n.*;
```

### Escaping reserved keywords

Use backticks to escape reserved words used as identifiers:

```cypher
CREATE NODE TABLE `Return` (id INT64 PRIMARY KEY, date TIMESTAMP);
MATCH (n:`Return`) RETURN n.*;
```

### Comments

- Single-line: `// comment`
- Multi-line: `/* comment */`

## Data types

### Numeric

| Type | Size | Notes |
|---|---|---|
| `INT8` | 1 byte | signed |
| `INT16` | 2 bytes | signed |
| `INT32` / `INT` | 4 bytes | signed |
| `INT64` / `SERIAL` | 8 bytes | signed; `SERIAL` = auto-incrementing |
| `INT128` | 16 bytes | signed |
| `UINT8`–`UINT64` | 1–8 bytes | unsigned variants |
| `FLOAT` / `REAL` | 4 bytes | single precision |
| `DOUBLE` / `FLOAT8` | 8 bytes | double precision |
| `DECIMAL(p, s)` | 2–16 bytes | fixed precision; `p` = total digits, `s` = decimal digits |

`SERIAL` is used for auto-incrementing primary keys. It is an alias for `INT64`.

### Text, binary, boolean

| Type | Notes |
|---|---|
| `STRING` | Variable-length, UTF-8 |
| `BOOLEAN` | `true` / `false` |
| `BLOB` / `BYTEA` | Arbitrary binary, up to 4KB |
| `UUID` | 16-byte RFC 4122 identifier |

### Temporal

| Type | Format | Notes |
|---|---|---|
| `DATE` | `YYYY-MM-DD` | 4 bytes |
| `TIMESTAMP` | `YYYY-MM-DD hh:mm:ss[.zzzzzz][+-TT[:tt]]` | Only date is mandatory; defaults to UTC |
| `INTERVAL` / `DURATION` | `'1 year 2 days'` | Date/time difference |

### Composite / nested

**STRUCT** — fixed set of key-value pairs (like a named tuple). Keys are always `STRING`. All values with the same `STRUCT` type must have the same set of keys.

```cypher
RETURN {first: 'Adam', last: 'Smith'};
-- Access: full_name.first or struct_extract(full_name, 'first')
```

**MAP** — dictionary with uniform key type and uniform value type. Unlike `STRUCT`, keys don't have to be `STRING` and the set of keys can vary per row.

```cypher
RETURN map([1, 2], ['a', 'b']) AS m;
```

**UNION** — holds one of several alternative typed values (like C++ `std::variant`). Internally a `STRUCT` with a `"tag"` key.

**JSON** — native JSON type (v0.15.0+). Prefer `JSON` over `STRING` for JSON data. Table functions for manipulation are in the JSON extension.

### LIST and ARRAY

**`LIST`** — variable-length, all elements same type.

```cypher
-- DDL: tags STRING[]
-- Literal: ['ai', 'graphs', 'memory']
-- Nested: STRING[][] for list of lists
```

All elements must be the same type — mixed types throw a binder exception. Use `UNWIND` to expand a list into rows:

```cypher
UNWIND ['a', 'b', 'c'] AS x RETURN x;
```

**`ARRAY`** — fixed-length list, all elements same type. Declared with `TYPE[SIZE]` syntax:

```cypher
-- DDL: embedding FLOAT[384]
-- Literal requires explicit cast: CAST([0.1, 0.2, 0.3], 'FLOAT[3]')
```

`ARRAY` is the correct type for embedding vectors (e.g., `FLOAT[384]`), since the dimensionality is fixed and known upfront.

### Graph-structural types

| Type | Internal representation | Key fields |
|---|---|---|
| `NODE` | `STRUCT` | `_ID`, `_LABEL`, plus all properties |
| `REL` | `STRUCT` | `_SRC`, `_DST`, `_ID`, `_LABEL`, plus properties |
| `RECURSIVE_REL` | `STRUCT{LIST[NODE], LIST[REL]}` | `_NODES`, `_RELS` |

Access path components: `nodes(p)`, `rels(p)`, `length(p)`.

### NULL behavior

`NULL` represents unknown data. Any comparison with `NULL` returns `NULL` (not `false`). `NULL = NULL` also returns `NULL`. Use `IS NULL` / `IS NOT NULL` for null checks. Unspecified properties default to `NULL` unless a `DEFAULT` is declared in the schema.

## Reserved keywords

These cannot be used as variable names, function names, or parameters without backtick escaping:

**Clauses:** `COLUMN`, `CREATE`, `DBTYPE`, `DEFAULT`, `GROUP`, `HEADERS`, `INSTALL`, `MACRO`, `OPTIONAL`, `PROFILE`, `UNION`, `UNWIND`, `WITH`

**Subclauses:** `LIMIT`, `ONLY`, `ORDER`, `WHERE`

**Expressions:** `ALL`, `CASE`, `CAST`, `ELSE`, `END`, `ENDS`, `EXISTS`, `GLOB`, `SHORTEST`, `THEN`, `WHEN`

**Literals:** `NULL`, `FALSE`, `TRUE`

**Modifiers:** `ASC`, `ASCENDING`, `DESC`, `DESCENDING`, `ON`

**Operators:** `AND`, `DISTINCT`, `IN`, `IS`, `NOT`, `OR`, `STARTS`, `XOR`

**Schema:** `FROM`, `PRIMARY`, `TABLE`, `TO`

## LadybugDB-specific behavior (differs from Neo4j)

LadybugDB follows openCypher but diverges from Neo4j in several ways that cause silent failures or errors if you use Neo4j patterns.

### Schema is mandatory

You **cannot** `CREATE (:Foo {bar: 1})` without first defining the `Foo` node table with a primary key. Every node table requires an explicit schema. See the main ladybug.md for DDL patterns.

### Walk semantics (not trail)

LadybugDB defaults to **walk** semantics in `MATCH` — edges and nodes may repeat in paths. Neo4j defaults to trail (no repeated edges). Use `is_trail(p)` or `is_acyclic(p)` to check path properties, or specify `TRAIL` / `ACYCLIC` explicitly in variable-length patterns.

Variable-length relationships **require an upper bound** to guarantee termination. If omitted, the default upper bound is **30 hops** (configurable via `VAR_LENGTH_EXTEND_MAX_DEPTH`).

### Unsupported clauses and workarounds

| Neo4j | LadybugDB equivalent |
|---|---|
| `REMOVE n.prop` | `SET n.prop = NULL` |
| `FOREACH` | `UNWIND` |
| `LOAD CSV FROM` | `LOAD FROM` (supports CSV, Parquet, etc.) |
| `SET n += {map}` | Not supported — update properties one by one |
| `FINISH` | `RETURN COUNT(*)` |
| `CALL <subquery>` | Not supported |
| `USE graph` | Not supported — each graph is a separate database |
| `SHOW FUNCTIONS` | `CALL show_functions() RETURN *` (all `SHOW XXX` → `CALL show_xxx() RETURN *`) |

### WHERE clause restrictions

`WHERE` inside node/relationship patterns is **not supported**:

```cypher
-- ❌ Not supported
MATCH (n:Person WHERE n.name = 'Andy') RETURN n;

-- ✅ Correct
MATCH (n:Person) WHERE n.name = 'Andy' RETURN n;
```

Label filtering in `WHERE` is **not supported**:

```cypher
-- ❌ Not supported
MATCH (n) WHERE n:Person RETURN n;

-- ✅ Correct
MATCH (n:Person) RETURN n;
-- or
MATCH (n) WHERE label(n) = 'Person' RETURN n;
```

### Function name differences

| Neo4j | LadybugDB |
|---|---|
| `labels(n)` | `label(n)` |
| `elementId(n)` | `id(n)` |
| `toInteger(x)`, `toFloat(x)`, etc. | `cast(x, 'INT64')`, `cast(x, 'DOUBLE')` |
| `date()` (current) | `current_date()` |
| `timestamp()` (current) | `current_timestamp()` |
| `tail(list)` | `list_slice()` |
| `head(list)` / `tail(list)` | `list_extract()` or `list[index]` |

Most list functions have a `list_` prefix: `list_concat`, `list_reverse`, `list_reduce`, etc.

### Vector similarity functions

| Function | Purpose |
|---|---|
| `ARRAY_COSINE_SIMILARITY(a, b)` | Cosine similarity |
| `ARRAY_DISTANCE(a, b)` | Euclidean distance |

### Not supported

Spatial functions, `isNaN()`, `e()`, `pi()`, `haversin()`, local datetime, real-time clock, and transaction time clock are not available.

## Subqueries

LadybugDB supports `EXISTS` and `COUNT` subqueries. `CALL <subquery>` is **not** supported. Subqueries are defined in curly braces `{}` and cannot contain a `RETURN` clause.

### EXISTS

Checks if a pattern has at least one match. Can be nested.

```cypher
MATCH (n:Note)
WHERE EXISTS { MATCH (n)-[:CoversTopic]->(t:Topic {name: 'AI'}) }
RETURN n.title;
```

### COUNT

Returns the number of matches for a pattern. Can be aliased and used in `WHERE`.

```cypher
-- As a return expression
MATCH (a:Person)
RETURN a.name, COUNT { MATCH (a)<-[:AuthoredBy]-(n:Note) } AS note_count
ORDER BY note_count DESC;

-- As a filter
MATCH (a:Person)
WHERE COUNT { MATCH (a)<-[:AuthoredBy]-(n:Note) } >= 3
RETURN a.name;
```

`COUNT` supports `DISTINCT`: `COUNT(DISTINCT b)`.

## Transactions

LadybugDB is ACID-compliant. Every query is part of a transaction (auto-committed if not explicitly managed).

**Critical constraint:** At any point there can be multiple read transactions but only **one** write transaction.

### Manual transactions

```cypher
BEGIN TRANSACTION;              -- starts read-write transaction
-- ... queries ...
COMMIT;                         -- or ROLLBACK;

BEGIN TRANSACTION READ ONLY;    -- starts read-only transaction
-- ... read queries ...
COMMIT;
```

### Auto transactions

Any command sent without `BEGIN TRANSACTION` is automatically wrapped in a transaction.

### Checkpoint

`CHECKPOINT;` merges WAL data to database files. Happens automatically when WAL exceeds `CHECKPOINT_THRESHOLD` (default 16MB) and no active transactions exist. Cannot force checkpoint while transactions are active.

## Configuration

Set via standalone `CALL` statements (cannot be combined with other clauses like `RETURN`).

| Option | Description | Default |
|---|---|---|
| `THREADS` | Execution thread count | System max |
| `TIMEOUT` | Query timeout in ms | N/A |
| `VAR_LENGTH_EXTEND_MAX_DEPTH` | Max depth for variable-length paths | 30 |
| `ENABLE_SEMI_MASK` | Semi mask optimization | `true` |
| `PROGRESS_BAR` | CLI progress bar | `false` |
| `CHECKPOINT_THRESHOLD` | WAL size (bytes) before auto-checkpoint | 16777216 (16MB) |
| `WARNING_LIMIT` | Max warnings per connection | 8192 |
| `SPILL_TO_DISK` | Spill to disk on memory pressure during `COPY FROM` | `true` |

```cypher
CALL THREADS=5;
CALL TIMEOUT=3000;
CALL var_length_extend_max_depth=10;
```

## Attach/Detach external databases

Connect to external LadybugDB databases or relational DBMSs for cross-database queries. Attaching to non-LadybugDB databases requires installing an extension.

```cypher
ATTACH '/path/to/other' AS other_db (dbtype lbug);
MATCH (a:other_db.SomeTable) RETURN *;
DETACH other_db;
```