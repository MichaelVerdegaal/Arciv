"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.db import ensure_schema, get_connection, load_query
from clotho.notes import MarkdownNote
from clotho.scrape import process_url
from config import NOTES_PATH, configure_logger


configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

conn = get_connection()
ensure_schema(conn)

# Create Source node
conn.execute(
    load_query("queries/create_source"),
    parameters={
        "name": "daily notes",
        "uri": f"file:///{str(NOTES_PATH)}",
    },
)

# Process some notes
for note in note_files:
    logger.info(f"Processing note: {note.filename}")

    # Create Document node
    document_name: str = note.filename
    conn.execute(
        load_query("queries/create_document"),
        parameters={
            "name": document_name,
            "content": note.text,
            "rel_path": f"{note.note_path.relative_to(NOTES_PATH)}",
            "type": "obsidian",
        },
    )

    # Create relation from Source to Document
    conn.execute(
        load_query("queries/create_contains"),
        parameters={
            "source_name": "daily notes",
            "doc_name": document_name,
        },
    )

    # for url in note.extract_urls():
    #     processed, _ = process_url(url)
    #     if processed is None:
    #         continue
