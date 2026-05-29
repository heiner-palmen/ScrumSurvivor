#!/usr/bin/env bash
# ScrumSurvivor — launch the interactive asset creation wizard
# Usage:  ./run_create_assets.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Activate virtual environment ───────────────────────────────────────────
if [[ ! -f ".venv/bin/activate" ]]; then
    echo -e "\033[0;31m✗ Virtual environment not found. Run ./run_setup.sh first.\033[0m"
    exit 1
fi
. .venv/bin/activate

# ── Launch asset creator ──────────────────────────────────────────────────────
echo ""
echo -e "\033[0;36m  ScrumSurvivor asset creator starting...\033[0m"
echo -e "\033[0;90m  Follow the on-screen instructions to capture base photo + idle clips.\033[0m"
echo ""

cd src
python -m scrumsurvivor.create_assets
