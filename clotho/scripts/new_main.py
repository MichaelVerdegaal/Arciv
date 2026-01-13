from clotho.notes.note import Note
from clotho.notes.obsidian_note import ObsidanNote

from config import NOTES_PATH
from pathlib import Path
from loguru import logger

TEST_NOTE_PATH = "C:/Users/Michael.Verdegaal/Documents/DevVault/Test note.md"


# Get all note files in directory
note_files: list[Path] = ObsidanNote.get_note_files(NOTES_PATH)
logger.info(f"Found {len(note_files)} notes in NOTES_PATH")

# Get test note
test_note: Note = Note(TEST_NOTE_PATH)
logger.info(f"Loaded: {test_note}")




