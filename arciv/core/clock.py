"""One shared spelling of "now" for every timestamp the archive writes."""

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the DB timestamp format)."""
    return datetime.now(UTC).isoformat()
