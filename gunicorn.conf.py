"""Gunicorn configuration for TeachFlow."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 2  # Keep low for SQLite (avoids write contention)
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"
