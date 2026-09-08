"""Regression checks for the TeachFlow brand and purple-gray UI theme."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_TEXT_GLOBS = (
    "templates/**/*.html",
    "static/**/*.css",
    "static/**/*.js",
    "static/**/*.json",
    "static/**/*.svg",
    "src/**/*.py",
)


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _ui_text() -> str:
    paths = {path for pattern in UI_TEXT_GLOBS for path in PROJECT_ROOT.glob(pattern) if path.is_file()}
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(paths))


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_global_brand_is_teachflow_without_bird_logo():
    base = _read("templates/base.html")
    ui_text = _ui_text()

    assert '<a href="/dashboard">TeachFlow</a>' in base
    assert "QuizWeaver" not in ui_text
    assert ".nav-brand a::before" not in _read("static/css/style.css")
    assert "robin.png" not in ui_text
    assert "robin_19x22.png" not in ui_text


def test_light_and_dark_theme_variables_match_brand_palette():
    css = _read("static/css/style.css")
    required_values = {
        "--primary: #74677f",
        "--primary-dark: #5b5067",
        "--primary-light: #f1edf3",
        "--accent: #9c90a5",
        "--accent-light: #f6f3f7",
        "--warning: #826f8d",
        "--warning-light: #f2edf4",
        "--bg: #f8f6f8",
        "--border: #ded8e2",
        "--border-light: #eeeaf0",
        "--primary: #b9aec3",
        "--primary-dark: #d2c8da",
        "--primary-light: #2d2831",
        "--accent: #a99db2",
        "--accent-light: #302a34",
        "--warning: #b5a4bd",
        "--warning-light: #312a35",
    }

    for declaration in required_values:
        assert declaration in css


def test_ui_has_no_legacy_orange_palette():
    ui_text = _ui_text().lower()
    legacy_tokens = {
        "#e76f51",
        "#c95a3e",
        "#fef0ec",
        "#e9c46a",
        "#fdf6e3",
        "#f4a261",
        "#fef5ec",
        "#f4845f",
        "#fff0eb",
        "#fff8e1",
        "#b37320",
        "#f59e0b",
        "#fff3cd",
        "#ffc107",
        "#856404",
        "#b45309",
        "#e69f00",
        "rgba(231, 111, 81",
        "rgba(244, 132, 95",
    }

    for token in legacy_tokens:
        assert token not in ui_text


def test_pwa_uses_teachflow_brand_color_and_letter_icon():
    base = _read("templates/base.html")
    manifest = _read("static/manifest.json")
    service_worker = _read("static/sw.js")

    assert '<meta name="theme-color" content="#74677f">' in base
    assert '"theme_color": "#74677f"' in manifest
    assert "icons/teachflow.svg" in base
    assert "icons/teachflow-192.png" in manifest
    assert "icons/teachflow-512.png" in manifest
    assert "icons/teachflow.svg" in service_worker


def test_primary_button_colors_meet_wcag_aa():
    assert _contrast_ratio("#ffffff", "#74677f") >= 4.5
    assert _contrast_ratio("#ffffff", "#5b5067") >= 4.5


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard?skip_onboarding=1",
        "/classes",
        "/classes/select?target=generate-quiz",
        "/classes/select?target=log-lesson",
        "/generate",
        "/settings",
        "/help",
    ],
)
def test_representative_pages_render_teachflow_brand(flask_client, path):
    response = flask_client.get(path, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert '<html lang="zh-CN"' in html
    assert "TeachFlow" in html
    assert "QuizWeaver" not in html


def test_login_template_uses_teachflow_brand():
    html = _read("templates/login.html")

    assert "TeachFlow" in html
    assert "QuizWeaver" not in html
