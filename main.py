from clotho.config import NOTE_PATH
from loguru import logger
from clotho.documents import get_note_info, get_note_files
from helix import Client


CATEGORY = "DAILY"


if __name__ == "__main__":
    # Connect to Helix DB instance
    try:
        db = Client(local=True, verbose=True)
    except Exception as e:
        logger.exception(f"Error connecting to HelixDB instance: {e}")

    # create category if it doesn't exist
    db.query("createCategory", {"name": CATEGORY})

    # Load notes
    notes = get_note_files(NOTE_PATH)
    logger.info(f"Retrieved {len(notes)} notes...")

    # Get metadata for each note
    notes_processed = [get_note_info(note) for note in notes]
    logger.info(f"Retrieved metadata for {len(notes_processed)} notes...")

    for note in notes_processed:  # Add notes to Helix
        logger.info(f"Adding note: {note['filename']}")
        document_node = db.query(
            "createDocument",
            {
                "category": CATEGORY,
                "filename": note['filename'],
                "file_created_at": note['creation_date'],
                "file_modified_at": note['modification_date'],
                "content": note['content']
            }
        )