"""Web coverage for AI review details and teacher confirmation state."""

import json
import re

import pytest

from src.database import Class, Question, Quiz, get_session
from src.quiz_generator import generate_quiz


def _seed_quiz(session, ai_status="passed", ai_reason="approved", question_count=2):
    classroom = Class(
        name="Review Class",
        grade_level="7th Grade",
        subject="Science",
        standards=json.dumps(["SOL 7.1"]),
        config=json.dumps({}),
    )
    session.add(classroom)
    session.commit()
    quiz = Quiz(
        title="Review Quiz",
        class_id=classroom.id,
        status="generated",
        style_profile=json.dumps({"provider": "mock", "difficulty": 3}),
        generation_metadata=json.dumps(
            {"metrics": {"ai_review_status": ai_status, "ai_review_reason": ai_reason}}
        ),
    )
    session.add(quiz)
    session.commit()
    for index in range(question_count):
        session.add(
            Question(
                quiz_id=quiz.id,
                question_type="mc",
                text=f"Question {index + 1}",
                points=1,
                sort_order=index,
                data=json.dumps(
                    {"type": "mc", "options": ["A", "B", "C", "D"], "correct_index": 0}
                ),
            )
        )
    session.commit()


def _logged_client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["username"] = "review_teacher"
        session["display_name"] = "Review Teacher"
    return client


def _quiz_state(app):
    session = get_session(app.config["DB_ENGINE"])
    try:
        quiz = session.query(Quiz).filter_by(id=1).one()
        return quiz.teacher_review_status, quiz.teacher_confirmed_at, quiz.teacher_confirmed_by
    finally:
        session.close()


def test_new_generated_quiz_starts_pending_teacher_review(db_session, mock_config, sample_class):
    session, _ = db_session
    classroom = sample_class(session)
    quiz = generate_quiz(session, classroom.id, mock_config, topics="cells")
    assert quiz.teacher_review_status == "pending_teacher_review"
    assert quiz.teacher_confirmed_at is None
    assert quiz.teacher_confirmed_by is None


def test_confirm_requires_post_csrf_markup_and_records_teacher(make_flask_app):
    app = make_flask_app(seed_fn=lambda session: _seed_quiz(session))
    client = _logged_client(app)

    page = client.get("/quizzes/1")
    assert "待教师核对".encode() in page.data
    assert "确认测验可用".encode() in page.data
    assert b'name="csrf_token"' in page.data

    response = client.post("/quizzes/1/confirm", follow_redirects=False)
    assert response.status_code == 303
    status, confirmed_at, confirmed_by = _quiz_state(app)
    assert status == "teacher_confirmed"
    assert confirmed_at is not None
    assert confirmed_by == "Review Teacher"
    assert client.post("/quizzes/999/confirm").status_code == 404


def test_question_edits_and_deletion_require_reconfirmation_but_title_does_not(make_flask_app):
    app = make_flask_app(seed_fn=lambda session: _seed_quiz(session))
    client = _logged_client(app)
    assert client.post("/quizzes/1/confirm").status_code == 303

    edited = client.put(
        "/api/questions/1",
        data=json.dumps(
            {
                "text": "Edited question",
                "question_type": "mc",
                "points": 2,
                "options": ["New answer", "B", "C", "D"],
                "correct_index": 0,
                "correct_answer": "New answer",
            }
        ),
        content_type="application/json",
    )
    assert edited.status_code == 200
    assert _quiz_state(app) == ("changes_require_reconfirmation", None, None)

    assert client.post("/quizzes/1/confirm").status_code == 303
    titled = client.put(
        "/api/quizzes/1/title",
        data=json.dumps({"title": "Renamed Quiz"}),
        content_type="application/json",
    )
    assert titled.status_code == 200
    assert _quiz_state(app)[0] == "teacher_confirmed"

    deleted = client.delete("/api/questions/2")
    assert deleted.status_code == 200
    assert _quiz_state(app) == ("changes_require_reconfirmation", None, None)
    assert client.post("/quizzes/1/confirm").status_code == 303
    assert _quiz_state(app)[0] == "teacher_confirmed"


def test_detail_hides_legacy_ai_review_metadata(make_flask_app):
    app = make_flask_app(seed_fn=lambda session: _seed_quiz(session, "not_passed", "critic_rejected"))
    page = _logged_client(app).get("/quizzes/1")
    assert page.status_code == 200
    assert "AI 检查".encode() not in page.data
    assert "质量检查记录".encode() not in page.data


def test_legacy_metadata_is_honest_and_export_warning_does_not_block_download(make_flask_app):
    app = make_flask_app(seed_fn=lambda session: _seed_quiz(session, ai_status=None, ai_reason=None))
    client = _logged_client(app)
    page = client.get("/quizzes/1")
    assert "AI 检查".encode() not in page.data
    assert "该测验尚未经过教师确认".encode() in page.data
    assert len(re.findall(br"<a[^>]+data-export-link", page.data)) == 4
    assert "是否仍要继续？".encode() in page.data
    assert b"export/gift" not in page.data
    assert b"export/qti" not in page.data
    assert b"generate-audio" not in page.data
    assert client.get("/quizzes/1/export/csv").status_code == 200

    assert client.post("/quizzes/1/confirm").status_code == 303
    confirmed_page = client.get("/quizzes/1")
    assert "教师已确认".encode() in confirmed_page.data
    assert b'id="export-review-warning"' not in confirmed_page.data
    assert client.get("/quizzes/1/export/csv").status_code == 200
