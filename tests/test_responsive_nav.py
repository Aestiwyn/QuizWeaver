"""
Tests for BL-027: Responsive Navigation.
Verifies direct navigation, mobile controls, and Demo entry visibility.
"""

import json
import os
import tempfile

import pytest

from src.database import Base, Class, get_engine, get_session


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    session = get_session(engine)
    cls = Class(
        name="Test Class",
        grade_level="7th Grade",
        subject="Math",
        standards=json.dumps([]),
        config=json.dumps({}),
    )
    session.add(cls)
    session.commit()
    session.close()
    engine.dispose()
    from src.web.app import create_app

    test_config = {
        "paths": {"database_file": db_path},
        "llm": {"provider": "mock"},
        "generation": {"default_grade_level": "7th Grade"},
    }
    flask_app = create_app(test_config)
    flask_app.config["TESTING"] = True

    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app
    flask_app.config["DB_ENGINE"].dispose()
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except PermissionError:
        pass


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "teacher"
    return c


class TestNavStructure:
    """Core workflows use direct links and preserve mobile navigation."""

    def test_direct_navigation(self, client):
        html = client.get("/dashboard?skip_onboarding=1").data.decode()
        nav = html.split('<ul class="nav-links"', 1)[1].split('</ul>', 1)[0]
        assert 'href="/generate"' in nav
        assert 'nav-dropdown' not in nav
        assert 'nav-toggle' in html
        assert 'navBackdrop' in html


class TestNavLinksPresent:
    """Core links remain while secondary tools leave the main navigation."""

    def test_dashboard_link(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/dashboard"' in html

    def test_classes_link(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/classes"' in html

    def test_quizzes_link(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/quizzes"' in html

    def test_question_bank_link_hidden(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/question-bank"' not in html

    def test_study_link_hidden(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/study"' not in html

    def test_costs_link_hidden(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/costs"' not in html

    def test_settings_link(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/settings"' in html

    def test_help_link(self, client):
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/help"' in html

    def test_generate_quiz_link(self, client):
        """Quiz generation is directly accessible."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/generate"' in html

    def test_study_generate_link_hidden(self, client):
        """This entry is hidden from the Demo navigation."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/study/generate"' not in html

    def test_topics_generation_link_hidden(self, client):
        """This entry is hidden from the Demo navigation."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/generate/topics"' not in html

    def test_standards_link_hidden(self, client):
        """This entry is hidden from the Demo navigation."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/standards"' not in html

    def test_analytics_link_hidden(self, client):
        """This entry is hidden from the Demo navigation."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'href="/analytics"' not in html


class TestNavUserSection:
    """User info is in a separate section from main nav."""

    def test_user_section_exists(self, client):
        """Nav has a separate user section."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert "nav-user-section" in html

    def test_logout_button_present(self, client):
        """Logout button is present (POST form, not link)."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        assert 'action="/logout"' in html

    def test_logout_outside_nav_links(self, client):
        """Logout is in the user section, not in the main nav-links."""
        resp = client.get("/dashboard?skip_onboarding=1")
        html = resp.data.decode()
        # The logout form should appear after nav-user-section
        user_section_idx = html.find("nav-user-section")
        logout_idx = html.find('action="/logout"')
        assert user_section_idx != -1
        assert logout_idx != -1
        assert logout_idx > user_section_idx
