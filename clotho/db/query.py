"""Cypher query loading and execution."""

from functools import lru_cache

import real_ladybug as lb

from config import CYPHER_DIR


@lru_cache(maxsize=None)
def load_query(name: str) -> str:
    """Load a Cypher query from a .cypher file in the cypher directory.

    Args:
        name: Path relative to the cypher directory, without the .cypher
            extension (e.g. "schema/create_source_table").

    Returns:
        The query string with leading/trailing whitespace stripped.

    Raises:
        FileNotFoundError: If no .cypher file exists at that path.
    """
    path = CYPHER_DIR / f"{name}.cypher"
    return path.read_text(encoding="utf-8").strip()


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
