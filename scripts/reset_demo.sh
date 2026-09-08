#!/bin/bash
# reset_demo.sh - TeachFlow Demo Database Reset Script
#
# Purpose:
#   Resets the TeachFlow database to a clean state with demo data.
#   Safe to run multiple times - always backs up before destroying data.
#
# Usage:
#   bash scripts/reset_demo.sh
#   (On Windows, run from Git Bash or WSL)
#
# What it does:
#   1. Backs up the isolated demo database with timestamp
#   2. Removes old database
#   3. Runs migrations to create fresh schema
#   4. Loads demo data (classes, lessons, quizzes)
#
# Safety:
#   - Never targets quiz_warehouse.db (the teacher's normal database)
#   - Checks for file existence before operations
#   - Exits on any error (set -e)

set -e  # Exit immediately if a command exits with a non-zero status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Prefer the project environment so the reset matches the launcher.
if [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "[FAIL] Python 3.9 or newer is required. Create .venv or install Python first."
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    echo "[FAIL] $PYTHON is not Python 3.9 or newer. Recreate .venv with a supported Python version."
    exit 1
fi

if ! "$PYTHON" -m pip check >/dev/null 2>&1 || ! "$PYTHON" -c 'import yaml; from src.migrations import init_database_with_migrations' >/dev/null 2>&1; then
    echo "[FAIL] Required dependencies are missing or inconsistent."
    echo "       Run: $PYTHON -m pip install -r requirements.txt"
    exit 1
fi

echo ""
echo "=========================================="
echo "TeachFlow Demo Database Reset"
echo "=========================================="
echo ""

# Configuration
DB_FILE="${TEACHFLOW_DEMO_DB:-demo_data/teachflow_demo.db}"
case "$(basename "$DB_FILE")" in
  quiz_warehouse.db)
    echo "[FAIL] Refusing to reset the working database. Set TEACHFLOW_DEMO_DB to an isolated demo path."
    exit 1
    ;;
esac

if [ ! -f "config.yaml" ]; then
    echo "[FAIL] config.yaml is required so the application opens the reset demo database."
    echo "       Copy config.yaml.example, set paths.database_file to $DB_FILE, and set llm.provider to mock."
    exit 1
fi

if ! "$PYTHON" - "$DB_FILE" <<'PY'
from pathlib import Path
import sys

import yaml

expected = Path(sys.argv[1]).resolve()
config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
configured = config.get("paths", {}).get("database_file")
provider = config.get("llm", {}).get("provider")

if not configured:
    raise SystemExit("config.yaml is missing paths.database_file")
if Path(configured).resolve() != expected:
    raise SystemExit(f"config.yaml points to {configured}, not {sys.argv[1]}")
if provider != "mock":
    raise SystemExit("config.yaml must set llm.provider to mock for the isolated demo")
PY
then
    echo "[FAIL] Demo configuration does not match the isolated database."
    echo "       Set paths.database_file to $DB_FILE and llm.provider to mock in config.yaml, then retry."
    exit 1
fi

BACKUP_DIR="$(dirname "$DB_FILE")/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/teachflow_demo_${TIMESTAMP}.db"
mkdir -p "$(dirname "$DB_FILE")"

# Step 1: Backup existing database (if it exists)
if [ -f "$DB_FILE" ]; then
    echo "[1/4] Backing up existing database..."

    # Create backups directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"

    # Copy database to backup location
    cp "$DB_FILE" "$BACKUP_FILE"
    echo "      [OK] Backup created: $BACKUP_FILE"
else
    echo "[1/4] No existing database found (first run)"
    echo "      [OK] Skipping backup"
fi

# Step 2: Remove old database
if [ -f "$DB_FILE" ]; then
    echo "[2/4] Removing old database..."
    rm "$DB_FILE"
    echo "      [OK] Old database removed"
else
    echo "[2/4] No database to remove"
    echo "      [OK] Skipping removal"
fi

# Step 3: Run migrations to create fresh database
echo "[3/4] Creating fresh database schema..."
"$PYTHON" -c "from src.migrations import init_database_with_migrations; init_database_with_migrations('${DB_FILE}')"
echo "      [OK] Database schema created"

# Step 4: Load demo data
echo "[4/4] Loading demo data..."
TEACHFLOW_DEMO_DB="$DB_FILE" "$PYTHON" demo_data/setup_demo.py
echo "      [OK] Demo data loaded"

# Success message
echo ""
mkdir -p "$(dirname "$DB_FILE")"
echo "=========================================="
echo "[OK] Demo database reset complete!"
echo "=========================================="
echo ""
echo "Database ready at: $DB_FILE"
if [ -f "$BACKUP_FILE" ]; then
    echo "Backup saved at:   $BACKUP_FILE"
fi
echo ""
echo "Next steps:"
echo "  1. Start the web app:  run.bat  (Windows)"
echo "                         or follow docs/DEMO.md"
echo "  2. Or follow:          docs/DEMO_SCRIPT.md"
echo ""
