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

echo ""
echo "=========================================="
echo "TeachFlow Demo Database Reset"
echo "=========================================="
echo ""

# Configuration
DB_FILE="${TEACHFLOW_DEMO_DB:-demo_data/teachflow_demo.db}"
case "$DB_FILE" in
  quiz_warehouse.db|./quiz_warehouse.db)
    echo "[FAIL] Refusing to reset the working database. Set TEACHFLOW_DEMO_DB to an isolated demo path."
    exit 1
    ;;
esac
BACKUP_DIR="$(dirname "$DB_FILE")/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/quiz_warehouse_${TIMESTAMP}.db"

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
python -c "from src.migrations import init_database_with_migrations; init_database_with_migrations('${DB_FILE}')"
echo "      [OK] Database schema created"

# Step 4: Load demo data
echo "[4/4] Loading demo data..."
TEACHFLOW_DEMO_DB="$DB_FILE" python demo_data/setup_demo.py
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
