"""PyTorch-like HQL query classes for Clotho."""

from helix.client import Query
from helix.types import Payload


class CreateNote(Query):
    """Create a new Note node in the graph.

    Args:
        filename: Name of the note file
        created_at: RFC3339 formatted creation date
        updated_at: RFC3339 formatted modification date

    Example:
        >>> db.query(CreateNote(
        ...     filename="2024-03-15.md",
        ...     created_at="2024-03-15T10:30:00+00:00",
        ...     updated_at="2024-03-15T15:45:00+00:00"
        ... ))
    """

    def __init__(self, filename: str, created_at: str, updated_at: str):
        super().__init__()
        self.filename = filename
        self.created_at = created_at
        self.updated_at = updated_at

    def query(self) -> Payload:
        """Return query parameters as a list of objects."""
        return [
            {
                "filename": self.filename,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        ]

    def response(self, response):
        """Process and return the query response."""
        return response
