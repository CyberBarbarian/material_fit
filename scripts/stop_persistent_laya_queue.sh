#!/usr/bin/env sh
set -eu

STATE_DIR="${1:-${MATERIAL_FIT_PERSISTENT_STATE_DIR:-}}"
if [ -z "$STATE_DIR" ]; then
  exit 0
fi
PID_FILE="$STATE_DIR/daemon.pid"
READY_FILE="$STATE_DIR/ready.json"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi
rm -f "$READY_FILE"
exit 0
