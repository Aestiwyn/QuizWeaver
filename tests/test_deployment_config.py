"""Regression checks for secure container deployment configuration."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_container_deployment_requires_an_explicit_secret_key():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "ENV SECRET_KEY=" not in dockerfile
    assert "${SECRET_KEY:?Set SECRET_KEY in .env before starting TeachFlow}" in compose
    assert "change-me-in-production" not in dockerfile
    assert "change-me-in-production" not in compose


def test_env_example_explains_secret_key_generation():
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "secrets.token_hex(32)" in env_example
    assert "SECRET_KEY=paste-a-unique-random-value-here" in env_example
