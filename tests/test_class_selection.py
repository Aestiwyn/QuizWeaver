"""Tests for explicit class selection in the two core Demo workflows."""

from unittest.mock import MagicMock, patch

from src.classroom import LEGACY_CLASS_NAME
from src.database import Class, LessonLog, Quiz
from src.web.blueprints.helpers import _get_session


def _rename_second_class(flask_app):
    with flask_app.app_context():
        session = _get_session()
        cls = session.query(Class).filter_by(id=2).one()
        cls.name = "Seventh Grade Math"
        cls.grade_level = "7th Grade"
        cls.subject = "Math"
        session.commit()


class TestDashboardClassSelection:
    def test_home_core_entries_do_not_embed_first_class(self, flask_client):
        html = flask_client.get("/dashboard").data.decode()
        assert 'href="/generate"' in html
        assert 'href="/classes/select?target=log-lesson"' in html
        assert "/classes/1/generate" not in html
        assert "/classes/1/lessons/new" not in html

    def test_generate_entry_opens_generate_selection(self, flask_client):
        response = flask_client.get("/generate")
        assert response.status_code == 302
        assert "/classes/select" in response.headers["Location"]
        assert "target=generate-quiz" in response.headers["Location"]
        page = flask_client.get(response.headers["Location"])
        assert page.status_code == 200
        assert b"Choose a Class for Quiz Generation" in page.data

    def test_lesson_entry_opens_lesson_selection(self, flask_client):
        page = flask_client.get("/classes/select?target=log-lesson")
        assert page.status_code == 200
        assert b"Choose a Class for Lesson Logging" in page.data


class TestClassSelectionPage:
    def test_lists_all_classes_with_grade_subject_and_actions(self, flask_client, flask_app):
        _rename_second_class(flask_app)
        html = flask_client.get("/classes/select?target=generate-quiz").data.decode()
        assert "Test Class" in html
        assert "Seventh Grade Math" in html
        assert "7th Grade" in html
        assert "Math" in html
        assert 'href="/classes/2/generate"' in html

        lesson_html = flask_client.get("/classes/select?target=log-lesson").data.decode()
        assert 'href="/classes/2/lessons/new"' in lesson_html

    def test_non_default_class_opens_locked_forms(self, flask_client, flask_app):
        _rename_second_class(flask_app)
        for url in ("/classes/2/generate", "/classes/2/lessons/new"):
            html = flask_client.get(url).data.decode()
            assert "Seventh Grade Math" in html
            assert "7th Grade" in html
            assert "Math" in html
            assert 'name="class_id"' not in html
            assert 'id="class_id"' not in html

    def test_class_detail_keeps_direct_class_specific_actions(self, flask_client, flask_app):
        _rename_second_class(flask_app)
        html = flask_client.get("/classes/2").data.decode()
        assert 'href="/classes/2/generate"' in html
        assert 'href="/classes/2/lessons/new"' in html
        assert "Seventh Grade Math" in html
        assert "7th Grade" in html
        assert "Math" in html

    def test_invalid_target_is_rejected_without_redirect(self, flask_client):
        for target in ("", "https://example.com", "/settings", "generate-quiz/../../settings"):
            response = flask_client.get("/classes/select", query_string={"target": target})
            assert response.status_code == 400
            assert "Location" not in response.headers

    def test_requires_login(self, anon_flask_client):
        response = anon_flask_client.get("/classes/select?target=generate-quiz")
        assert response.status_code == 303

    def test_empty_selector_offers_new_class(self, make_flask_app):
        app = make_flask_app()
        with app.app_context():
            session = _get_session()
            session.query(Class).delete()
            session.commit()
        with app.test_client() as client:
            with client.session_transaction() as login_session:
                login_session["logged_in"] = True
                login_session["username"] = "teacher"
            for target in ("generate-quiz", "log-lesson"):
                html = client.get("/classes/select", query_string={"target": target}).data.decode()
                assert "No classes yet" in html
                assert 'href="/classes/new"' in html
                assert "Create Your First Class" in html


class TestClassAssociation:
    def test_new_class_can_log_lesson_and_generate_quiz(self, flask_client, flask_app):
        create_response = flask_client.post(
            "/classes/new",
            data={"name": "New Math Class", "grade_level": "7th Grade", "subject": "Math"},
        )
        assert create_response.status_code == 303
        with flask_app.app_context():
            session = _get_session()
            new_class = session.query(Class).filter_by(name="New Math Class").one()
            new_class_id = new_class.id

        lesson_response = flask_client.post(
            f"/classes/{new_class_id}/lessons/new",
            data={"class_id": "1", "content": "Integer operations", "topics": "integers"},
        )
        assert lesson_response.status_code == 303
        with flask_app.app_context():
            session = _get_session()
            lesson = session.query(LessonLog).filter_by(content="Integer operations").one()
            assert lesson.class_id == new_class_id

        generated_quiz = MagicMock(id=77)
        with patch("src.web.blueprints.quizzes.generate_quiz", return_value=generated_quiz) as generate:
            quiz_response = flask_client.post(
                f"/classes/{new_class_id}/generate",
                data={
                    "class_id": "1",
                    "source_mode": "current_input",
                    "topics": "integers",
                    "num_questions": "3",
                    "provider": "mock",
                    "question_types": ["mc"],
                },
            )
        assert quiz_response.status_code == 303
        assert generate.call_args.kwargs["class_id"] == new_class_id

    def test_invalid_class_ids_return_404(self, flask_client):
        assert flask_client.get("/classes/9999/generate").status_code == 404
        assert flask_client.post("/classes/9999/generate", data={}).status_code == 404
        assert flask_client.get("/classes/9999/lessons/new").status_code == 404
        assert flask_client.post("/classes/9999/lessons/new", data={"content": "x"}).status_code == 404


class TestLegacyClassDisplay:
    def test_legacy_name_changes_only_in_display_layer(self, flask_client, flask_app):
        with flask_app.app_context():
            session = _get_session()
            legacy = session.query(Class).filter_by(id=1).one()
            legacy.name = LEGACY_CLASS_NAME
            original_quiz = session.query(Quiz).filter_by(class_id=legacy.id).one()
            original_quiz_id = original_quiz.id
            session.commit()

        for url in (
            "/dashboard",
            "/classes",
            "/classes/1",
            "/classes/1/edit",
            "/classes/select?target=generate-quiz",
            f"/quizzes/{original_quiz_id}",
        ):
            html = flask_client.get(url).data.decode()
            assert "Default Class (Legacy Data)" in html
            assert LEGACY_CLASS_NAME not in html

        edit_response = flask_client.post(
            "/classes/1/edit",
            data={"name": "Default Class (Legacy Data)", "grade_level": "7th Grade", "subject": "Science"},
        )
        assert edit_response.status_code == 303

        with flask_app.app_context():
            session = _get_session()
            legacy = session.query(Class).filter_by(id=1).one()
            quiz = session.query(Quiz).filter_by(id=original_quiz_id).one()
            assert legacy.name == LEGACY_CLASS_NAME
            assert quiz.class_id == legacy.id
