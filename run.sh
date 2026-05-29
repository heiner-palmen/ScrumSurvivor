#!/usr/bin/env bash
# ScrumSurvivor — Start pipeline
# Usage:  ./run.sh
#         ./run.sh --preview        (force local preview window on)
#         ./run.sh --no-preview     (force local preview window off)

set -euo pipefail

cd "$(dirname "$0")"

# ──────────────────────────────────────────────
# Kill leftover ScrumSurvivor Python processes only
# ──────────────────────────────────────────────
stop_project_python_processes() {
    local module_name="$1"

    # Find Python processes that match the module pattern
    local pids
    pids=$(ps aux | grep -E 'python[0-9]* ' | grep -E "(-m\s+)?${module_name}" | grep -v grep | awk '{print $2}' || true)

    if [[ -n "$pids" ]]; then
        local count
        count=$(echo "$pids" | wc -l)
        echo "  Stopping $count leftover Python process(es) for $module_name..."
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 0.6
    fi
}

stop_project_python_processes "scrumsurvivor"

# ──────────────────────────────────────────────
# Activate virtual environment
# ──────────────────────────────────────────────
VENV_ACTIVATE=".venv/bin/activate"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "Virtual environment not found. Run ./setup_venv.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV_ACTIVATE"

# ──────────────────────────────────────────────
# Launch pipeline
# ──────────────────────────────────────────────
echo ""
echo "  ScrumSurvivor starting..."
echo "  Press Ctrl+C to stop."
echo ""

cd src
if [[ "${1:-}" == "--preview" ]]; then
    python -m scrumsurvivor run --preview --prompt-theme
elif [[ "${1:-}" == "--no-preview" ]]; then
    python -m scrumsurvivor run --no-preview --prompt-theme
else
    python -m scrumsurvivor run --prompt-theme
fi
