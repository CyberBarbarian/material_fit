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

asset="${1:-fish}"
case "$asset" in
  fish|turtle|crocodile) ;;
  *) echo "asset must be fish, turtle, or crocodile" >&2; exit 2 ;;
esac

if [[ "$(uname -s)" == "Linux" ]]; then
  export MATERIAL_FIT_CHROMIUM_ARGS="${MATERIAL_FIT_CHROMIUM_ARGS:---ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox}"
fi

args=(
  -m material_fit.experiments.material_human_reference_stage1
  --asset "$asset"
  --optimizer material_discrete_joint
  --joint-profile v86_budget1500_initial_score_routed_unified
  --iterations "${ITERATIONS:-1499}"
  --target-score "${TARGET_SCORE:-0.995}"
  --success-score "${SUCCESS_SCORE:-0.98}"
  --max-runtime-sec "${MAX_RUNTIME_SEC:-1200}"
  --speed-gate-ms "${SPEED_GATE_MS:-500}"
  --node-modules "$REPO_ROOT/node_modules"
  --engine-libs "$REPO_ROOT/vendor/layaair-3.4.0/libs"
)
if [[ -n "${OUTPUT_ROOT:-}" ]]; then
  args+=(--output-root "$OUTPUT_ROOT")
fi

.venv/bin/python "${args[@]}"
