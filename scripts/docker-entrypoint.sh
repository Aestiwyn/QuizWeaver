#!/bin/sh
set -eu

if [ "${DEMO_MODE:-0}" = "1" ]; then
    echo "[INFO] DEMO_MODE=1; preparing a fresh disposable demo database"
    if ! python demo_data/bootstrap_render_demo.py; then
        echo "[ERROR] Demo database initialization failed; Gunicorn will not start" >&2
        exit 1
    fi
else
    echo "[INFO] DEMO_MODE is disabled; preserving the configured database"
fi

exec gunicorn -c gunicorn.conf.py 'src.web.app:create_app()'
