"""Regression checks for the local launch and isolated demo reset scripts."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_windows_launcher_uses_project_venv_for_install_and_startup():
    launcher = (PROJECT_ROOT / "run.bat").read_text(encoding="utf-8")

    assert 'set "VENV_PYTHON=.venv\\Scripts\\python.exe"' in launcher
    assert '"%VENV_PYTHON%" -m pip install -r requirements.txt' in launcher
    assert '"%VENV_PYTHON%" -c "import os;' in launcher
    assert "Path('config.yaml').read_text(encoding='utf-8')" in launcher
    assert "hashlib.sha256(requirements.read_bytes()).hexdigest()" in launcher
    assert "marker.read_text(encoding='utf-8').strip() == digest" in launcher


def test_demo_reset_prefers_venv_and_validates_isolated_mock_configuration():
    reset_script = (PROJECT_ROOT / "scripts" / "reset_demo.sh").read_text(encoding="utf-8")

    assert reset_script.index(".venv/Scripts/python.exe") < reset_script.index("command -v python3")
    assert reset_script.index(".venv/bin/python") < reset_script.index("command -v python3")
    assert '"$PYTHON" -m pip check' in reset_script
    assert 'basename "$DB_FILE"' in reset_script
    assert "quiz_warehouse.db" in reset_script
    assert "config.yaml points to" in reset_script
    assert 'provider != "mock"' in reset_script
    assert 'TEACHFLOW_DEMO_DB="$DB_FILE" "$PYTHON" demo_data/setup_demo.py' in reset_script
