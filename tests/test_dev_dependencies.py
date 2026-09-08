"""Regression checks for separate runtime and development dependencies."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_and_development_dependencies_are_separate():
    runtime = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    development = (PROJECT_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "pytest==" not in runtime
    assert "ruff==" not in runtime
    assert "-r requirements.txt" in development
    assert "pytest==9.0.2" in development
    assert "pytest-cov==7.0.0" in development
    assert "ruff==0.16.6" in development


def test_ci_installs_development_dependencies():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert workflow.count("pip install -r requirements-dev.txt") == 2
