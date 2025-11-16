from clotho.config import NOTE_PATH
from clotho.queries import CreateNote
from pathlib import Path
from datetime import datetime, timezone
from helix.instance import Instance
from helix.client import Client


def get_note_files() -> list[Path]:
    """Reads all markdown files in the NOTE_PATH directory and returns a list of their paths."""
    return [p for p in NOTE_PATH.glob("**/*.md")]


# get file information for each note. I.e. filename, creation date, modification date
def _rfc3339_from_timestamp(ts: float) -> str:
    """Convert a POSIX timestamp to an RFC3339 (ISO-8601) string with UTC offset.

    Args:
        ts: POSIX timestamp (seconds since epoch)

    Returns:
        RFC3339 formatted string, e.g. '2025-11-14T12:34:56+00:00'
    """
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def get_note_info(note: Path) -> dict[str, str]:
    """Returns a dictionary with file information for the given note.

    The creation and modification dates are returned as RFC3339 strings.
    """
    filename = note.name
    creation_date = _rfc3339_from_timestamp(note.stat().st_ctime)
    modification_date = _rfc3339_from_timestamp(note.stat().st_mtime)

    info: dict[str, str] = {
        "filename": filename,
        "creation_date": creation_date,
        "modification_date": modification_date,
    }
    return info


if __name__ == "__main__":
    # Create and configure temporary HelixDB instance
    helix_instance = Instance("helixdb-cfg", 6969, verbose=True)
    
    try:
        print(f"Instance status: {helix_instance.status()}")
        
        # Connect to instance
        db = Client(local=True, verbose=True)
        
    except Exception as e:
        print(f"Error connecting to HelixDB instance: {e}")

    # Process notes
    notes = get_note_files()
    print(f"\nProcessing {len(notes)} notes...")
    
    for note in notes:
        info = get_note_info(note)
        
        # Use the CreateNote query class to insert the note
        result = db.query(CreateNote(
            filename=info["filename"],
            created_at=info["creation_date"],
            updated_at=info["modification_date"]
        ))
        
        print(f"Created note: {info['filename']}")
        print(f"  Result: {result}")
    