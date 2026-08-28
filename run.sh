#!/bin/bash
set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$HOME/.config/ai-usage-monitor"
PID_FILE="$STATE_DIR/app.pid"

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(tr -cd '0-9' < "$PID_FILE")"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "AI Usage Monitor is already running (PID: $OLD_PID)"
    exit 0
  fi
fi

cd "$PROJECT_DIR" || exit 1
nohup .venv/bin/python app.py </dev/null >/dev/null 2>&1 &
APP_PID=$!
printf '%s\n' "$APP_PID" > "$PID_FILE"
chmod 600 "$PID_FILE"

sleep 1
if kill -0 "$APP_PID" 2>/dev/null; then
  echo "AI Usage Monitor started (PID: $APP_PID)"
else
  rm -f "$PID_FILE"
  echo "AI Usage Monitor failed to start" >&2
  exit 1
fi
