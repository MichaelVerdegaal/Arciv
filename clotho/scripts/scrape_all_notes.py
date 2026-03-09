"""Scrape all URLs from Obsidian daily notes into the database."""

from loguru import logger

from clotho.notes import MarkdownNote
from clotho.scrape import process_url
from config import NOTES_PATH, configure_logger, DATA_DIR
import real_ladybug as lb


configure_logger()

# Get all note files in directory
note_files: list[MarkdownNote] = MarkdownNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Schema definition
db = lb.Database(str(DATA_DIR / "clotho.lbug"))
conn = lb.Connection(db)

# Create schema
conn.execute("""
CREATE NODE TABLE Source (
    name STRING PRIMARY KEY,
    uri STRING,
    created_at TIMESTAMP DEFAULT current_timestamp()
)
""")
conn.execute("""
CREATE NODE TABLE Note (
    name STRING PRIMARY KEY,
    content STRING,
    rel_path STRING,
    note_type STRING,
    fetched BOOLEAN DEFAULT false,
    explored BOOLEAN DEFAULT false,
    level INT16 DEFAULT 0,
    created_at TIMESTAMP DEFAULT current_timestamp()
)
""")
conn.execute("""CREATE REL TABLE FoundIn(FROM Note TO Note, since INT64)""")


# Create source
conn.execute("""
    CREATE (n:Source {name: "daily notes", uri: $uri})
""", parameters={
    "name": "daily notes",
    "uri": f"file:///{str(NOTES_PATH)}",
})

# Process some notes
for note in note_files:
    logger.info(f"Processing note: {note.filename}")

    conn.execute("""
        CREATE (n:Note {name: $name, content: $content, rel_path: $rel_path, fetched: true, explored: false})

    """, parameters={
        "name": note.filename,
        "content": note.text,
        "rel_path": f"{note.note_path.relative_to(NOTES_PATH)}",
        "note_type": "obsidian",
    })

    # for url in note.extract_urls():
    #     processed, _ = process_url(url)
    #     if processed is None:
    #         continue
