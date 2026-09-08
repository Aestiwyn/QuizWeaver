"""Focused checks for the disposable public Render demo."""

import runpy

import pytest

from src.database import Class, LessonLog, Quiz, User, get_engine, get_session
from src.web.auth import authenticate_user


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    """Create the same reset-on-start SQLite app used by Render."""
    from demo_data.bootstrap_render_demo import prepare_demo_database
    from src.web.app import create_app

    target = tmp_path / "teachflow_demo.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_USERNAME", "teacher")
    monkeypatch.setenv("DEMO_PASSWORD", "teacher123")
    monkeypatch.setenv("DATABASE_PATH", str(target))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("SECRET_KEY", "render-demo-test-secret")

    prepare_demo_database(target)
    app = create_app(
        {
            "paths": {"database_file": str(target)},
            "llm": {"provider": "mock"},
            "generation": {"default_grade_level": "七年级"},
        }
    )
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield app, target
    app.config["DB_ENGINE"].dispose()


@pytest.fixture
def logged_in_demo_client(demo_app):
    app, _ = demo_app
    client = app.test_client()
    response = client.post(
        "/login",
        data={"username": "teacher", "password": "teacher123"},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/dashboard")
    return client


def test_gunicorn_uses_render_port(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    config = runpy.run_path("gunicorn.conf.py")
    assert config["bind"] == "0.0.0.0:10000"


def test_gunicorn_defaults_to_port_8000(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    config = runpy.run_path("gunicorn.conf.py")
    assert config["bind"] == "0.0.0.0:8000"


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "on"])
def test_demo_mode_requires_exact_value_one(monkeypatch, value):
    from demo_data.bootstrap_render_demo import demo_mode_enabled

    if value is None:
        monkeypatch.delenv("DEMO_MODE", raising=False)
    else:
        monkeypatch.setenv("DEMO_MODE", value)
    assert demo_mode_enabled() is False


def test_disabled_demo_bootstrap_preserves_database(tmp_path, monkeypatch):
    from demo_data.bootstrap_render_demo import main

    target = tmp_path / "existing.db"
    original = b"existing database bytes must remain untouched"
    target.write_bytes(original)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(target))

    assert main() == 0
    assert target.read_bytes() == original


def test_prepare_refuses_to_replace_database_outside_demo_mode(tmp_path, monkeypatch):
    from demo_data.bootstrap_render_demo import prepare_demo_database

    target = tmp_path / "existing.db"
    original = b"do not replace"
    target.write_bytes(original)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    with pytest.raises(RuntimeError, match="DEMO_MODE=1"):
        prepare_demo_database(target)
    assert target.read_bytes() == original


def test_demo_bootstrap_creates_hashed_resettable_data(tmp_path, monkeypatch):
    from demo_data.bootstrap_render_demo import prepare_demo_database

    target = tmp_path / "teachflow_demo.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_USERNAME", "teacher")
    monkeypatch.setenv("DEMO_PASSWORD", "teacher123")

    prepare_demo_database(target)
    engine = get_engine(url=f"sqlite:///{target.as_posix()}")
    session = get_session(engine)
    try:
        user = session.query(User).filter_by(username="teacher").one()
        assert user.password_hash != "teacher123"
        assert "teacher123" not in user.password_hash
        assert authenticate_user(session, "teacher", "teacher123") is not None
        assert session.query(Class).count() == 2
        assert session.query(LessonLog).count() >= 2
        assert session.query(Quiz).count() == 2
        session.add(Class(name="访客临时修改", standards="[]", config="{}"))
        session.query(Quiz).filter_by(title="光合作用知识检查").one().title = "访客编辑的测验"
        session.commit()
    finally:
        session.close()
        engine.dispose()

    prepare_demo_database(target)
    engine = get_engine(url=f"sqlite:///{target.as_posix()}")
    session = get_session(engine)
    try:
        assert session.query(Class).filter_by(name="访客临时修改").count() == 0
        assert session.query(Class).count() == 2
        assert session.query(Quiz).count() == 2
        assert session.query(Quiz).filter_by(title="访客编辑的测验").count() == 0
        assert session.query(Quiz).filter_by(title="光合作用知识检查").count() == 1
    finally:
        session.close()
        engine.dispose()


def test_demo_login_dashboard_health_and_content_operations(demo_app, logged_in_demo_client):
    app, _ = demo_app
    anonymous = app.test_client()
    login_response = anonymous.get("/login")
    login_html = login_response.data.decode("utf-8")

    assert login_response.status_code == 200
    assert "公开演示账号" in login_html
    assert 'value="teacher"' in login_html
    assert 'value="teacher123"' in login_html
    assert anonymous.get("/health").status_code == 200

    dashboard = logged_in_demo_client.get("/dashboard")
    dashboard_html = dashboard.data.decode("utf-8")
    assert dashboard.status_code == 200
    assert "七年级科学 A 班" in dashboard_html
    assert "八年级地球科学" in dashboard_html
    assert "光合作用知识检查" in dashboard_html
    assert "水循环形成性测验" in dashboard_html

    created = logged_in_demo_client.post(
        "/classes/new",
        data={"name": "访客创建的班级", "grade_level": "九年级", "subject": "科学"},
    )
    assert created.status_code == 303

    edited = logged_in_demo_client.put("/api/quizzes/1/title", json={"title": "访客编辑的测验"})
    assert edited.status_code == 200
    assert edited.get_json() == {"ok": True, "title": "访客编辑的测验"}


def test_public_credentials_are_hidden_outside_demo_mode(demo_app, monkeypatch):
    app, _ = demo_app
    monkeypatch.delenv("DEMO_MODE", raising=False)
    response = app.test_client().get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "公开演示账号" not in html
    assert 'value="teacher123"' not in html


@pytest.mark.parametrize("method", ["get", "post"])
def test_demo_mode_blocks_password_changes(demo_app, logged_in_demo_client, method):
    app, _ = demo_app
    request_method = getattr(logged_in_demo_client, method)
    response = request_method(
        "/settings/password",
        data={
            "current_password": "teacher123",
            "new_password": "changed-password",
            "confirm_password": "changed-password",
        },
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/settings")

    session = get_session(app.config["DB_ENGINE"])
    try:
        assert authenticate_user(session, "teacher", "teacher123") is not None
        assert authenticate_user(session, "teacher", "changed-password") is None
    finally:
        session.close()


def test_demo_initialization_failure_is_explicit(monkeypatch, capsys):
    import demo_data.bootstrap_render_demo as bootstrap

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/demo.db")

    def fail(_target):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(bootstrap, "prepare_demo_database", fail)
    assert bootstrap.main() == 1
    assert "[ERROR] Demo database initialization failed: seed failed" in capsys.readouterr().err


def test_container_checks_demo_mode_before_starting_gunicorn():
    dockerfile = open("Dockerfile", encoding="utf-8").read()
    entrypoint = open("scripts/docker-entrypoint.sh", encoding="utf-8").read()

    assert 'CMD ["sh", "scripts/docker-entrypoint.sh"]' in dockerfile
    assert 'if [ "${DEMO_MODE:-0}" = "1" ]' in entrypoint
    assert "python demo_data/bootstrap_render_demo.py" in entrypoint
    assert "Demo database initialization failed; Gunicorn will not start" in entrypoint
    assert "exec gunicorn -c gunicorn.conf.py" in entrypoint
