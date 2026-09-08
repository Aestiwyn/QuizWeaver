"""Time helpers that preserve TeachFlow's naive-UTC database convention."""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Return the current UTC time without timezone metadata for existing columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
