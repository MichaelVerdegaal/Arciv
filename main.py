from clotho.config import NOTE_PATH, logger
from clotho.documents import get_note_info, get_note_files, NoteInfo
from clotho.scripts.insert_notes import insert_notes
from helix import Client


CATEGORY = "DAILY"


if __name__ == "__main__":
    # Connect to Helix DB instance
    try:
        db = Client(local=True, verbose=True)
    except Exception as e:
        logger.exception(f"Error connecting to HelixDB instance: {e}")

    # Load notes
    notes = get_note_files(NOTE_PATH)
    logger.info(f"Retrieved {len(notes)} notes...")

    # Get metadata for each note
    notes_processed: list[NoteInfo] = [get_note_info(note) for note in notes]
    logger.info(f"Retrieved metadata for {len(notes_processed)} notes...")

    # Insert notes into HelixDB
    insert_notes(db, CATEGORY, notes_processed)