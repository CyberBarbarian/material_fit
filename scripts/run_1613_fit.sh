#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -x "$REPO_ROOT/.runtime/node/bin/node" ]]; then
  export PATH="$REPO_ROOT/.runtime/node/bin:$PATH"
fi
[[ -x .venv/bin/python ]] || {
  echo "Missing .venv. Run scripts/bootstrap.sh first." >&2
  exit 1
}
if [[ "$(uname -s)" == "Linux" ]]; then
  export MATERIAL_FIT_CHROMIUM_ARGS="${MATERIAL_FIT_CHROMIUM_ARGS:---ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox}"
fi

args=(
  -m material_fit.experiments.material_cross_engine_stage2_multiview_v86
  --iterations "${ITERATIONS:-1500}"
  --target-score "${TARGET_SCORE:-0.995}"
  --max-runtime-sec "${MAX_RUNTIME_SEC:-1800}"
  --node-modules "$REPO_ROOT/node_modules"
)
[[ -n "${VIEW_IDS:-}" ]] && args+=(--view-ids "$VIEW_IDS")
[[ -n "${OBSERVATION_MANIFEST:-}" ]] && args+=(--observation-manifest "$OBSERVATION_MANIFEST")
[[ -n "${START_MATERIAL:-}" ]] && args+=(--start-material "$START_MATERIAL")
[[ -n "${OUTPUT_ROOT:-}" ]] && args+=(--output-root "$OUTPUT_ROOT")
[[ -n "${RUN_NAME:-}" ]] && args+=(--run-name "$RUN_NAME")

.venv/bin/python "${args[@]}"
