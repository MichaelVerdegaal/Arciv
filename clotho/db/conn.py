"""LadybugDB connection and schema management."""

import real_ladybug as lb

from .query import load_query

SCHEMA_QUERIES = [
    "schema/create_source_table",
    "schema/create_document_table",
    "schema/create_contains_table",
]


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
