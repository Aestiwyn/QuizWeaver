"""Real SQL upgrades preserve old lesson records, including partial retries."""

import sqlite3
from pathlib import Path

import pytest

from src.database import LessonLog, get_session
from src.migrations import check_if_migration_needed, run_migrations


@pytest.mark.parametrize("already_added", [0, 1, 2])
def test_upgrade_legacy_lessons_and_retry(tmp_path, already_added):
    database = tmp_path / "legacy.db"
    # Build the previous schema from the actual migrations, with a real old record.
    with sqlite3.connect(database) as connection:
        for migration in sorted(Path("migrations").glob("*.sql")):
            if int(migration.name[:3]) >= 14:
                continue
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc) and "no such table" not in str(exc):
                    raise
        connection.execute("INSERT INTO lesson_logs (class_id, date, content, notes) VALUES (1, '2021-02-03', 'Legacy text', 'Old notes')")
        for column in ["original_filename", "stored_filename"][:already_added]:
            connection.execute(f"ALTER TABLE lesson_logs ADD COLUMN {column} TEXT")
    assert check_if_migration_needed(str(database))
    assert run_migrations(str(database), verbose=False)
    assert not check_if_migration_needed(str(database))
    assert not run_migrations(str(database), verbose=False)

    from src.web.app import create_app

    app = create_app({"paths": {"database_file": str(database)}, "llm": {"provider": "mock"}})
    app.config["TESTING"] = True
    try:
        with get_session(app.config["DB_ENGINE"]) as session:
            lesson = session.query(LessonLog).one()
            assert lesson.content == "Legacy text" and str(lesson.date) == "2021-02-03"
            assert lesson.original_filename is None and lesson.extracted_text is None and lesson.stored_filename is None
            lesson_id = lesson.id
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["logged_in"] = True
            page = client.get(f"/classes/1/lessons/{lesson_id}")
            assert page.status_code == 200
            assert b"Legacy text" in page.data and b"2021-02-03" in page.data and b"Old notes" in page.data
    finally:
        app.config["DB_ENGINE"].dispose()
