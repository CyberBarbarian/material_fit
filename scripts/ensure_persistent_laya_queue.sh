#!/usr/bin/env sh
set -eu

STATE_DIR="${1:-${MATERIAL_FIT_PERSISTENT_STATE_DIR:-}}"
PORT="${2:-${CAP_PORT:-8787}}"
if [ -z "$STATE_DIR" ]; then
  echo "STATE_DIR is required" >&2
  exit 2
fi

mkdir -p "$STATE_DIR/logs"
PID_FILE="$STATE_DIR/daemon.pid"
READY_FILE="$STATE_DIR/ready.json"
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null && [ -f "$READY_FILE" ]; then
    exit 0
  fi
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
(
  cd "$REPO_ROOT"
  nohup python -m material_fit.laya_capture.persistent_queue_daemon \
    --state-dir "$STATE_DIR" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --timeout-s 120 \
    > "$STATE_DIR/logs/persistent_queue_stdout.log" \
    2> "$STATE_DIR/logs/persistent_queue_stderr.log" &
  echo $! > "$PID_FILE"
)

i=0
while [ "$i" -lt 100 ]; do
  if [ -f "$READY_FILE" ]; then
    exit 0
  fi
  i=$((i + 1))
  sleep 0.1
done

echo "persistent queue daemon did not become ready" >&2
exit 1
