from pathlib import Path

from loguru import logger

from clotho.notes.obsidian_note import ObsidanNote
from config import NOTES_PATH

TEST_NOTE_PATH = "C:/Users/Michael/Documents/DevVault/Test note.md"


# Get all note files in directory
note_files: list[Path] = ObsidanNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Get test note
test_note: ObsidanNote = ObsidanNote(TEST_NOTE_PATH)
logger.info(f"Loaded: {test_note}")

logger.debug(test_note.text)


# Extract links from test note
extracted_links = test_note.extract_links()
logger.info(f"Extracted {len(extracted_links)} links from test note:")
for link in extracted_links:
    logger.info(f" - {link}")
