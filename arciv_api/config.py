"""Runtime paths for the API, sourced from the arciv library settings.

Re-exported here (rather than imported straight into each router) so a test
can point the whole API at a temporary archive by monkeypatching this one
module, mirroring how the CLI tests redirect ``arciv.scripts.cli``.
"""

from arciv.settings import DB_PATH, SAVED_DIR

__all__ = ["DB_PATH", "SAVED_DIR"]
