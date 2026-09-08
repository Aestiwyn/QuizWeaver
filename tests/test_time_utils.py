"""Regression checks for the naive-UTC timestamp compatibility helper."""

from datetime import datetime, timezone

from src.time_utils import utc_now_naive


def test_utc_now_naive_preserves_existing_database_timestamp_shape():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    timestamp = utc_now_naive()
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    assert timestamp.tzinfo is None
    assert before <= timestamp <= after
