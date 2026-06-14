"""Runtime paths for the web app, sourced from the arciv library settings.

DB_PATH and SAVED_DIR are re-exported (not imported straight into each module)
so a test can point the whole app at a temporary archive by monkeypatching
this one module. The template and static dirs ship with the package.
"""

from pathlib import Path

from arciv.settings import DB_PATH, SAVED_DIR

_PKG_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _PKG_DIR / "templates"
STATIC_DIR = _PKG_DIR / "static"

__all__ = ["DB_PATH", "SAVED_DIR", "TEMPLATES_DIR", "STATIC_DIR"]
