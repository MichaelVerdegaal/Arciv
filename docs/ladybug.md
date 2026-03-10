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