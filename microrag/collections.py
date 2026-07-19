"""Collection bookkeeping: name validation and per-collection root pinning.

Sources are stored root-relative, so each collection is pinned to the first
root it was built from; the mapping lives in a roots.json marker inside the
DB directory.
"""

import json
import re
from pathlib import Path

from loguru import logger

from .constants import DEFAULT_COLLECTION, EX_DATAERR

_ROOTS_MARKER = "roots.json"
_LEGACY_ROOT_MARKER = "root.txt"

# Chroma's own naming rule (3-512 chars, alphanumeric ends), checked up front
# so a bad --collection is a clean usage error instead of a traceback.
COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$")


def read_roots(db_dir: Path) -> dict[str, str]:
    """Return the collection -> root mapping recorded for this index.

    A corrupted marker exits cleanly rather than crashing: proceeding without
    the recorded roots could silently mix roots inside a collection.
    """
    marker = db_dir / _ROOTS_MARKER
    if marker.exists():
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error(
                f"Corrupted roots marker at {marker}: {exc}. Fix or delete the "
                "file, then re-run 'microrag index <path>' once per collection "
                "to re-record its root."
            )
            raise SystemExit(EX_DATAERR) from None
    # Single-collection indexes from before named collections recorded one
    # bare root path; treat it as the default collection's root.
    legacy = db_dir / _LEGACY_ROOT_MARKER
    if legacy.exists():
        root = legacy.read_text(encoding="utf-8").strip()
        if root:
            return {DEFAULT_COLLECTION: root}
    return {}


def write_root(db_dir: Path, collection: str, root: str) -> None:
    """Record the root a collection was built from, atomically.

    Written via a temp file and rename so a crash mid-write can never leave
    a half-written (unparseable) marker behind.
    """
    roots = read_roots(db_dir)
    roots[collection] = root
    marker = db_dir / _ROOTS_MARKER
    scratch = marker.with_name(_ROOTS_MARKER + ".tmp")
    scratch.write_text(json.dumps(roots, indent=2) + "\n", encoding="utf-8")
    scratch.replace(marker)


def source_path(source: str, root: str | None) -> Path:
    """Join a root-relative source with its collection's recorded root."""
    return Path(root) / source if root else Path(source)
