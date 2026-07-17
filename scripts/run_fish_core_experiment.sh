#!/usr/bin/env sh
set -eu

MODE="${1:-}"
if [ -z "$MODE" ]; then
  echo "usage: scripts/run_fish_core_experiment.sh finetune|zero_searchable [runner args]" >&2
  exit 2
fi
shift

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Missing .venv. Run scripts/bootstrap.sh first." >&2
  exit 2
fi
if [ -x "$REPO_ROOT/.runtime/node/bin/node" ]; then
  PATH="$REPO_ROOT/.runtime/node/bin:$PATH"
  export PATH
fi

if [ "$(uname -s)" = "Linux" ] && [ -z "${MATERIAL_FIT_CHROMIUM_ARGS:-}" ]; then
  export MATERIAL_FIT_CHROMIUM_ARGS="--ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox"
fi

cd "$REPO_ROOT"
exec "$PYTHON" -m material_fit.experiments.fish_core_experiment \
  --mode "$MODE" \
  --platform-name linux \
  --engine-root "$REPO_ROOT/vendor/layaair-3.4.0/libs" \
  --width "${MATERIAL_FIT_DEFAULT_WIDTH:-900}" \
  --height "${MATERIAL_FIT_DEFAULT_HEIGHT:-700}" \
  "$@"
