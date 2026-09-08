"""Tests for Progressive Web App (PWA) support.

Covers manifest.json, service worker, offline route, icon files,
and base.html integration tags.
"""

import json
import os
import struct

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _read_template(name):
    """Return the raw text of a template file."""
    path = os.path.join(TEMPLATES_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# manifest.json tests
# ---------------------------------------------------------------------------


class TestManifest:
    """Tests for static/manifest.json validity and required fields."""

    def test_manifest_is_valid_json(self):
        path = os.path.join(STATIC_DIR, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data, dict)

    def test_manifest_required_fields(self):
        path = os.path.join(STATIC_DIR, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["name"] == "TeachFlow"
        assert data["short_name"] == "TeachFlow"
        assert data["start_url"] == "/dashboard"
        assert data["display"] == "standalone"
        assert data["background_color"] == "#f8f6f8"
        assert data["theme_color"] == "#74677f"
        assert "description" in data

    def test_manifest_icons_array(self):
        path = os.path.join(STATIC_DIR, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        icons = data.get("icons", [])
        assert icons == [
            {
                "src": "/static/icons/teachflow-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/teachflow-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ]

    def test_manifest_categories(self):
        path = os.path.join(STATIC_DIR, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        categories = data.get("categories", [])
        assert "education" in categories
        assert "productivity" in categories

    def test_manifest_served_at_correct_url(self, flask_client):
        resp = flask_client.get("/static/manifest.json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["name"] == "TeachFlow"


# ---------------------------------------------------------------------------
# Icon file tests
# ---------------------------------------------------------------------------


class TestIcons:
    """Tests that the TeachFlow letter icon exists and is valid SVG."""

    def test_icon_file_exists(self):
        path = os.path.join(STATIC_DIR, "icons", "teachflow.svg")
        assert os.path.isfile(path), "teachflow.svg should exist"

        for size in (192, 512):
            png_path = os.path.join(STATIC_DIR, "icons", f"teachflow-{size}.png")
            assert os.path.isfile(png_path), f"teachflow-{size}.png should exist"

        ico_path = os.path.join(STATIC_DIR, "icons", "teachflow.ico")
        assert os.path.isfile(ico_path), "teachflow.ico should exist"

    def test_icon_is_purple_t_svg_without_bird_art(self):
        path = os.path.join(STATIC_DIR, "icons", "teachflow.svg")
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        assert svg.lstrip().startswith("<svg")
        assert 'viewBox="0 0 512 512"' in svg
        assert 'fill="#74677f"' in svg
        assert "TeachFlow" in svg
        assert "robin" not in svg.lower()

    def test_icon_is_served_in_web_and_pwa_formats(self, flask_client):
        response = flask_client.get("/static/icons/teachflow.svg")
        assert response.status_code == 200
        assert response.mimetype == "image/svg+xml"

        response = flask_client.get("/static/icons/teachflow-192.png")
        assert response.status_code == 200
        assert response.mimetype == "image/png"

    def test_pwa_icon_dimensions(self):
        for size in (192, 512):
            path = os.path.join(STATIC_DIR, "icons", f"teachflow-{size}.png")
            with open(path, "rb") as fh:
                assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
                fh.read(4)
                assert fh.read(4) == b"IHDR"
                width = struct.unpack(">I", fh.read(4))[0]
                height = struct.unpack(">I", fh.read(4))[0]
            assert (width, height) == (size, size)


# ---------------------------------------------------------------------------
# base.html integration tests
# ---------------------------------------------------------------------------


class TestBaseTemplate:
    """Tests that base.html includes all required PWA tags."""

    def test_manifest_link_tag(self):
        html = _read_template("base.html")
        assert 'rel="manifest"' in html
        assert "manifest.json" in html

    def test_theme_color_meta(self):
        html = _read_template("base.html")
        assert 'name="theme-color"' in html
        assert "#74677f" in html

    def test_apple_mobile_web_app_capable(self):
        html = _read_template("base.html")
        assert 'name="apple-mobile-web-app-capable"' in html

    def test_apple_mobile_web_app_status_bar_style(self):
        html = _read_template("base.html")
        assert 'name="apple-mobile-web-app-status-bar-style"' in html

    def test_apple_touch_icon(self):
        html = _read_template("base.html")
        assert 'rel="apple-touch-icon"' in html
        assert "teachflow-192.png" in html

    def test_service_worker_registration(self):
        html = _read_template("base.html")
        assert "serviceWorker" in html
        assert "sw.js" in html


# ---------------------------------------------------------------------------
# Service worker tests
# ---------------------------------------------------------------------------


class TestServiceWorker:
    """Tests for static/sw.js content and availability."""

    def test_sw_js_served(self, flask_client):
        resp = flask_client.get("/static/sw.js")
        assert resp.status_code == 200

    def test_sw_js_has_cache_version(self):
        path = os.path.join(STATIC_DIR, "sw.js")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "CACHE_VERSION" in content

    def test_sw_js_has_cache_logic(self):
        path = os.path.join(STATIC_DIR, "sw.js")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "caches.open" in content
        assert "install" in content
        assert "activate" in content
        assert "fetch" in content


# ---------------------------------------------------------------------------
# Offline route tests
# ---------------------------------------------------------------------------


class TestOfflineRoute:
    """Tests for the /offline fallback page."""

    def test_offline_returns_200(self, flask_client):
        resp = flask_client.get("/offline")
        assert resp.status_code == 200

    def test_offline_no_auth_required(self, anon_flask_client):
        resp = anon_flask_client.get("/offline")
        assert resp.status_code == 200

    def test_offline_contains_message(self, flask_client):
        resp = flask_client.get("/offline")
        html = resp.data.decode("utf-8")
        assert "当前处于离线状态" in html
        assert "请恢复网络连接" in html
