#!/bin/bash
# Update Ark (火山方舟) credentials from a cURL command.
#
# Easiest usage (clipboard):
#   1. In the browser: open the Coding Plan page, F12 -> Network,
#      find the GetCodingPlanUsage request, right-click -> Copy as cURL
#   2. In the terminal, just run:
#        ./update-ark.sh
#      The script reads the cURL from your clipboard automatically.
#      No pasting, no Enter, no Ctrl+D.
#
# Alternative (piped):
#   ./update-ark.sh <<'EOF'
#   curl --url '...' ...
#   EOF

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Error: .venv not found at $PYTHON"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install rumps requests 'urllib3<2'"
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/update_ark_creds.py"
