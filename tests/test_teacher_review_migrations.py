"""Teacher-review migrations preserve old quizzes and default them to unconfirmed."""

import sqlite3
from pathlib import Path

from src.migrations import check_if_migration_needed, run_migrations


def test_upgrade_legacy_quiz_gets_pending_teacher_review(tmp_path):
    database = tmp_path / "legacy-quiz.db"
    with sqlite3.connect(database) as connection:
        for migration in sorted(Path("migrations").glob("*.sql")):
            if int(migration.name[:3]) >= 17:
                continue
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc) and "no such table" not in str(exc):
                    raise
        connection.execute("CREATE TABLE quizzes (id INTEGER PRIMARY KEY, title TEXT, status TEXT)")
        connection.execute("INSERT INTO quizzes (title, status) VALUES ('Legacy Quiz', 'generated')")

    assert check_if_migration_needed(str(database))
    assert run_migrations(str(database), verbose=False)
    assert not check_if_migration_needed(str(database))

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT teacher_review_status, teacher_confirmed_at, teacher_confirmed_by FROM quizzes"
        ).fetchone()
    assert row == ("pending_teacher_review", None, None)
