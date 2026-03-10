"""Database utilities for Clotho's LadybugDB backend."""

from functools import lru_cache
from pathlib import Path

import real_ladybug as lb

QUERIES_DIR = Path(__file__).parent / "queries"

SCHEMA_QUERIES = [
    "create_source_table",
    "create_document_table",
    "create_exists_in_table",
]


@lru_cache(maxsize=None)
def load_query(name: str) -> str:
    """Load a Cypher query from a .cypher file in the queries directory.

    Args:
        name: Query filename without the .cypher extension.

    Returns:
        The query string with leading/trailing whitespace stripped.

    Raises:
        FileNotFoundError: If no .cypher file exists with that name.
    """
    path = QUERIES_DIR / f"{name}.cypher"
    return path.read_text(encoding="utf-8").strip()


def get_connection(db_name: str = "clotho.lbug") -> lb.Connection:
    """Get a LadybugDB connection, creating the database if needed.

    Args:
        db_name: The name of the database file.

    Returns:
        A LadybugDB connection object.
    """
    db = lb.Database(db_name)
    return lb.Connection(db)


def ensure_schema(conn: lb.Connection) -> None:
    """Create all node and relationship tables if they don't already exist.

    Safe to call multiple times — every DDL query uses IF NOT EXISTS.

    Args:
        conn: An active LadybugDB connection.
    """
    for query_name in SCHEMA_QUERIES:
        conn.execute(load_query(query_name))


def run_query(conn: lb.Connection, query: str, **kwargs) -> lb.QueryResult | list[lb.QueryResult]:
    """Run a Cypher query with optional parameters.

    Args:
        conn: LadybugDB connection object.
        query: The Cypher query to run.
        **kwargs: Parameters to pass to the query.

    Returns:
        The query result(s).

    Raises:
        ValueError: If the query is empty.
    """
    if query == "":
        raise ValueError("Query cannot be empty")
    return conn.execute(query, parameters=kwargs)