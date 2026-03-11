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

## Query clauses reference

### MATCH patterns

**Multi-label nodes:** `MATCH (a:User:City)` matches nodes with label `User` OR `City`. Properties not present in a label return as `NULL`.

**Multi-label relationships:** `MATCH (a)-[e:Follows|:LivesIn]->(b)` matches either relationship type.

**Equality predicate sugar:** `MATCH (a:User {name: 'Adam'})-[e:Follows {since: 2020}]->(b:User)` is equivalent to adding `WHERE a.name = 'Adam' AND e.since = 2020`.

**Undirected relationships:** Use `-` instead of `->` or `<-`: `MATCH (a)-[e:Follows]-(b)` matches both directions.

**Omitting variables:** Variables can be omitted for nodes/rels you don't reference later: `MATCH (a:User)-[:Follows]->(:User)-[:LivesIn]->(c:City)`.

**Multiple patterns (comma-separated):** Required for cyclic patterns: `MATCH (a)-[:Follows]->(b)-[:Follows]->(c), (a)-[:Follows]->(c)`. Labels only need to be specified on first occurrence of a variable.

### Recursive relationships (variable-length paths)

Syntax: `-[:Label*min..max]->`. Default semantics is **WALK** (nodes/edges may repeat). Default max is **30** if omitted.

**Path semantics keywords** (placed after `*`):

| Keyword | Meaning |
|---|---|
| *(default)* | WALK — nodes and edges may repeat |
| `TRAIL` | No repeated edges |
| `ACYCLIC` | No repeated nodes (but source/destination not considered) |

```cypher
MATCH (a:User)-[e:Follows* TRAIL 1..4]->(b:User) WHERE a.name = 'Adam' RETURN b.name;
MATCH (a:User)-[e:Follows* ACYCLIC 1..6]->(b:User) WHERE a.name = 'Adam' RETURN b.name;
```

**Filtering intermediate nodes/edges:** Use `(r, n | WHERE <predicate>)` syntax. First variable = relationship, second = node. Only predicates on nodes alone OR relationships alone (or conjunctions of these) are supported — predicates mixing both (`n.age > 45 OR r.since < 2022`) are **not** supported.

```cypher
MATCH p = (a:User)-[:Follows*1..2 (r, n | WHERE r.since < 2022 AND n.age > 45)]->(b:User)
WHERE a.name = 'Adam'
RETURN b.name;
```

**Projecting intermediate properties:** Use `{r.prop}, {n.prop}` after the filter to limit which properties are returned. Improves performance and memory.

```cypher
MATCH (a:User)-[e:Follows*1..2 (r, n | WHERE r.since > 2020 | {r.since}, {n.name})]->(b:User)
RETURN nodes(e), rels(e);
```

**Path functions:** `nodes(p)`, `rels(p)`, `length(p)`, `properties(nodes(p), 'name')`, `properties(rels(p), '_ID')`, `is_trail(p)`, `is_acyclic(p)`, `cost(e)` (for weighted shortest).

### Shortest path variants

| Syntax | Behavior |
|---|---|
| `-[* SHORTEST 1..max]-` | Single shortest path per destination |
| `-[* ALL SHORTEST 1..max]-` | All shortest paths (same minimum length) |
| `-[* WSHORTEST(prop) 1..max]-` | Weighted shortest path using relationship property |
| `-[* ALL WSHORTEST(prop) 1..max]-` | All weighted shortest paths |

Lower bound is forced to 1 for shortest path queries.

```cypher
MATCH (a:User)-[e* SHORTEST 1..4]->(b:City) WHERE a.name = 'Adam'
RETURN b.name, length(e);

MATCH p = (a:User)-[e:Follows* WSHORTEST(score)]->(b:User) WHERE a.name = 'Adam'
RETURN properties(nodes(p), 'name'), cost(e);
```

### RETURN

**Return all properties:** `RETURN a.*` expands to all properties of `a` (without `_ID`, `_LABEL`). `RETURN *` returns all bound variables.

**Implicit GROUP BY:** Non-aggregated expressions in `RETURN` become group-by keys automatically. NULL keys are grouped together; NULL values are ignored in aggregations.

```cypher
MATCH (a:User)-[:Follows]->(b:User)
RETURN a.name, avg(b.age) AS avg_friend_age;
```

### WITH

Projects expressions (optionally with aggregations) as an intermediate step. Two primary uses: computing aggregations for later predicates, and top-k before further querying.

**`ORDER BY` after `WITH` requires `LIMIT` or `SKIP`** — otherwise ordering is meaningless since subsequent operators ignore order.

```cypher
-- Use aggregation result as filter
MATCH (a:User)
WITH avg(a.age) AS avgAge
MATCH (b:User) WHERE b.age > avgAge
RETURN b.name;

-- Top-k then further query
MATCH (a:User)
WITH a ORDER BY a.age DESC LIMIT 1
MATCH (a)-[:Follows]->(b:User)
RETURN b.name;
```

### UNWIND

Explodes a list into rows. `WHERE` **cannot** follow `UNWIND` directly — use `WITH` as intermediary:

```cypher
-- ❌ Parser error
UNWIND [1, 2, 3] AS x WHERE x > 1 RETURN x;

-- ✅ Correct
UNWIND [1, 2, 3] AS x WITH x WHERE x > 1 RETURN x;
```

### OPTIONAL MATCH

Semantically a left outer join. Unmatched patterns produce `NULL` values:

```cypher
MATCH (u:User)
OPTIONAL MATCH (u)-[:Follows]->(f:User)
RETURN u.name, f.name;
-- Users with no outgoing Follows get NULL for f.name
```

### UNION / UNION ALL

Combines two result sets with the same column count and types. `UNION` deduplicates; `UNION ALL` preserves duplicates.

### WHERE

`WHERE` evaluates predicates and filters tuples. Expressions evaluating to `NULL` are treated as `FALSE`. Use `IS NULL` / `IS NOT NULL` for null checks. Subquery patterns are supported in `WHERE`:

```cypher
MATCH (a:User)
WHERE (a)-[:Follows]->(:User {name: 'Noura'})-[:LivesIn]->(:City {name: 'Guelph'})
RETURN a.name;
-- Note: nodes/rels in the WHERE subquery pattern are NOT in scope for RETURN
```

### CALL clause (schema functions)

`CALL` executes schema introspection functions. Must be followed by `RETURN *` or `YIELD`. This is different from the standalone `CALL` statement for configuration.

| Function | Returns |
|---|---|
| `SHOW_TABLES()` | id, name, type, database name, comment for all tables |
| `TABLE_INFO('tableName')` | property id, name, type, default, primary key flag |
| `SHOW_CONNECTION('relName')` | source/destination table names and primary keys |
| `SHOW_ATTACHED_DATABASES()` | name and type of attached databases |
| `SHOW_FUNCTIONS()` | All registered functions |
| `SHOW_WARNINGS()` / `CLEAR_WARNINGS()` | Import warning contents |
| `SHOW_INDEXES()` | table name, index name, type, properties, definition |
| `SHOW_OFFICIAL_EXTENSIONS()` | Available installable extensions |
| `SHOW_LOADED_EXTENSIONS()` | Currently loaded extensions |
| `SHOW_PROJECTED_GRAPHS()` | Existing projected graphs |
| `CURRENT_SETTING('option')` | Value of a configuration setting |
| `DB_VERSION()` | Database version |

### YIELD

Renames `CALL` output columns. **All** output columns must appear in `YIELD` (no `YIELD *`). Column names must match the original function output exactly.

```cypher
CALL TABLE_INFO('Note')
YIELD `property id` AS pid, name AS prop_name, type AS prop_type,
      `default expression` AS default_val, `primary key` AS is_pk
RETURN prop_name, prop_type;
```

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