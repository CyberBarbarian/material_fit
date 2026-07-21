#!/usr/bin/env sh
set -eu

STATE_DIR="${1:-${MATERIAL_FIT_PERSISTENT_STATE_DIR:-}}"
if [ -z "$STATE_DIR" ]; then
  echo "STATE_DIR is required" >&2
  exit 2
fi

PID_FILE="$STATE_DIR/daemon.pid"
READY_FILE="$STATE_DIR/ready.json"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    i=0
    while [ "$i" -lt 50 ] && kill -0 "$PID" 2>/dev/null; do
      i=$((i + 1))
      sleep 0.1
    done
    if kill -0 "$PID" 2>/dev/null; then
      kill -KILL "$PID" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
fi
rm -f "$READY_FILE"
