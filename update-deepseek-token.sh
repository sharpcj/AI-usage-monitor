#!/bin/bash
# Update the DeepSeek open-platform session token (used for daily spend).
#
# The public API key cannot read spend; only the console session token can.
#
# Easiest usage (clipboard):
#   1. Log in at https://platform.deepseek.com
#   2. DevTools -> Console, run:
#        JSON.parse(localStorage.getItem('userToken')).value
#      then copy the printed string.
#   3. In the terminal, run:
#        ./update-deepseek-token.sh
#      The script reads the token from your clipboard automatically.
#
# Alternative (piped):
#   echo '<token>' | ./update-deepseek-token.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Error: .venv not found at $PYTHON"
    echo "Run: python3 start.py   (creates the venv on first launch)"
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/update_deepseek_token.py"
