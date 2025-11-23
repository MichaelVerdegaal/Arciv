from clotho.config import NOTE_PATH
from loguru import logger
from clotho.documents import get_note_info, get_note_files


if __name__ == "__main__":
    # Create and configure temporary HelixDB instance
    # helix_instance = Instance("dev", 6969, verbose=True)

    # try:
    #     logger.info(f"Instance status: {helix_instance.status()}")

    #     # Connect to instance
    #     db = Client(local=True, verbose=True)

    # except Exception as e:
    #     logger.exception(f"Error connecting to HelixDB instance: {e}")

    # Load notes
    notes = get_note_files(NOTE_PATH)
    logger.info(f"Retrieved {len(notes)} notes...")

    # Get metadata for each note
    notes_processed = [get_note_info(note) for note in notes]
    logger.info(f"Retrieved metadata for {len(notes_processed)} notes...")

    for metadata in notes_processed[:5]:  # Inspect first 5 notes
        logger.info(
            f"note: {metadata['filename']}, created_at={metadata['creation_date']}, updated_at={metadata['modification_date']}",
        )

        new_content_test = f"---\nfilename: {metadata['filename']}\ncreated_at: {metadata['creation_date']}\nupdated_at: {metadata['modification_date']}\n---\n\n{metadata['content']}\n\n\n"
        # dump this into a text file for inspection (first 5 files only), append mode
        with open("test.txt", "a", encoding="utf-8") as f:
            f.write(new_content_test)
