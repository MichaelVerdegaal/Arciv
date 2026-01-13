"""Insert notes into HelixDB as Document nodes with Category relationships."""

from collections.abc import Sequence

from helix import Client
from loguru import logger

from clotho.notes import Note


def insert_notes(
    db: Client,
    category_name: str,
    notes: Sequence[Note],
) -> None:
    """Insert notes into HelixDB and link them to a category.

    Creates a category node (if it doesn't exist) and inserts each note
    as a Document node, linking it to the category via HasCategory edge.

    Args:
        db: Connected HelixDB client instance
        category_name: Name of the category to create/link documents to
        notes: Sequence of NoteInfo dataclasses to insert

    Raises:
        Exception: If database operations fail
    """
    # Create category node
    category_node = db.query("createCategory", {"name": category_name})
    category_id = category_node[0]["category"]["id"]
    logger.info(f"Created/retrieved category: {category_name}")

    for note in notes:
        logger.info(f"Adding note: {note.filename}")

        # Create document node
        document_node = db.query(
            "createDocument",
            {
                "filename": note.filename,
                "file_created_at": note.creation_date,
                "file_modified_at": note.modification_date,
                "content": note.content,
            },
        )
        document_id = document_node[0]["document"]["id"]

        # Link document to category
        db.query(
            "linkDocumentToCategory",
            {
                "document_id": document_id,
                "category_id": category_id,
            },
        )
        logger.info(f"Linked document {note.filename} to category {category_name}")

    logger.info(f"Inserted {len(notes)} notes into category {category_name}")
