"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import process_url
from config import NOTES_PATH, configure_logger
import real_ladybug as lb


configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Schema definition
db = lb.Database("test.lbug")
conn = lb.Connection(db)

# Create schema
conn.execute("""
CREATE NODE TABLE Note (
    title STRING PRIMARY KEY,
    content STRING,
    uri STRING,
    note_type STRING,
    fetched BOOLEAN DEFAULTfalse,
    level INT16 0,
    created_at TIMESTAMP DEFAULT current_timestamp()

)
""")
conn.execute("""CREATE REL TABLE FoundIn(FROM Note TO Note, since INT64)""")


# Process some notes
for note in note_files[:3]:
    logger.info(f"Processing note: {note.filename}")

    conn.execute("""
        CREATE (n:Note {title: $title, content: $content, uri: $uri, fetched: true, note_type: $note_type})

    """, parameters={
        "title": note.filename,
        "content": note.text,
        "uri": f"file:///{note.filename}{note.extension}",
        "note_type": "obsidian",
    })

    # for url in note.extract_urls():
    #     processed, _ = process_url(url)
    #     if processed is None:
    #         continue
