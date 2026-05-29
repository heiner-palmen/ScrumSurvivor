#!/usr/bin/env bash
# ScrumSurvivor — launch the interactive setup wizard
# Usage:  ./run_config.sh
#         ./run_config.sh custom-config.yaml

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_PATH="${1:-config.yaml}"

# ── Activate virtual environment ──────────────────────────────────────────────
VENV_ACTIVATE=".venv/bin/activate"
if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "Virtual environment not found. Run ./run_setup.sh first." >&2
    exit 1
fi
source "$VENV_ACTIVATE"

# ── Launch setup wizard ──────────────────────────────────────────────────────
echo ""
echo "  ScrumSurvivor setup starting..."
echo "  Follow the prompts to select microphone, virtual audio, and speech threshold."
echo ""

cd src
python -m scrumsurvivor setup --config "$CONFIG_PATH"
