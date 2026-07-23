#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

[[ -x .venv/bin/python ]] || {
  echo "Missing .venv. Run scripts/bootstrap.sh first." >&2
  exit 1
}

run_dir="${RUN_DIR:-}"
material="${MATERIAL:-}"
if [[ -z "$run_dir" && -z "$material" ]]; then
  material="$REPO_ROOT/material_fit/assets/material_starts/1613/experimental_best_20260723.lmat"
fi
output="${OUTPUT:-$REPO_ROOT/artifacts/deliverables/1613_result_$(date +%Y%m%d_%H%M%S).zip}"

args=(
  -m material_fit.experiments.material_delivery_package
  --asset 1613
  --output "$output"
)
[[ -n "$run_dir" ]] && args+=(--run-dir "$run_dir")
[[ -n "$material" ]] && args+=(--material "$material")
.venv/bin/python "${args[@]}"
