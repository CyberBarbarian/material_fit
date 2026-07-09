#!/usr/bin/env sh
set -eu

MODE=""
if [ "$#" -gt 0 ]; then
  MODE="$1"
  shift
fi
if [ -z "$MODE" ]; then
  echo "usage: scripts/run_fish_core_experiment.sh finetune|zero_searchable [runner args]" >&2
  exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -z "${MATERIAL_FIT_REMOTE_BASE:-}" ] \
  && [ -d "/vepfs-mlp2/c20250508/lizikang/material_fit_render_oracle" ]; then
  export MATERIAL_FIT_REMOTE_BASE="/vepfs-mlp2/c20250508/lizikang/material_fit_render_oracle"
fi

if [ -n "${MATERIAL_FIT_REMOTE_BASE:-}" ]; then
  if [ -x "$MATERIAL_FIT_REMOTE_BASE/tools/node-v20.19.3-linux-x64/bin/node" ]; then
    export PATH="$MATERIAL_FIT_REMOTE_BASE/tools/node-v20.19.3-linux-x64/bin:$PATH"
  fi
  if [ -z "${LAYA_ENGINE_LIBS:-}" ] \
    && [ -d "$MATERIAL_FIT_REMOTE_BASE/tools/layaair/3.4.0/Resources/engine/libs" ]; then
    export LAYA_ENGINE_LIBS="$MATERIAL_FIT_REMOTE_BASE/tools/layaair/3.4.0/Resources/engine/libs"
  fi
  if [ -z "${PLAYWRIGHT_CHROMIUM_EXECUTABLE:-}" ]; then
    chrome="$(find "$MATERIAL_FIT_REMOTE_BASE/cache/ms-playwright" -path '*/chrome-linux/chrome' -type f 2>/dev/null | head -n 1 || true)"
    if [ -n "$chrome" ]; then
      export PLAYWRIGHT_CHROMIUM_EXECUTABLE="$chrome"
    fi
  fi
  if [ ! -e "$REPO_ROOT/artifacts/real_laya_run/node_modules" ] \
    && [ -d "/vepfs-mlp2/c20250508/lizikang/material_fit_cross_platform/artifacts/real_laya_run/node_modules" ]; then
    mkdir -p "$REPO_ROOT/artifacts/real_laya_run"
    ln -s "/vepfs-mlp2/c20250508/lizikang/material_fit_cross_platform/artifacts/real_laya_run/node_modules" \
      "$REPO_ROOT/artifacts/real_laya_run/node_modules"
  fi
fi

if [ "$(uname -s)" = "Linux" ]; then
  if [ -z "${MATERIAL_FIT_CHROMIUM_ARGS:-}" ]; then
    export MATERIAL_FIT_CHROMIUM_ARGS="--ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox"
  fi
  if [ -z "${CUDA_VISIBLE_DEVICES:-}" ] && command -v nvidia-smi >/dev/null 2>&1; then
    export CUDA_VISIBLE_DEVICES=0
  fi
fi

if [ "${MATERIAL_FIT_RENDER_BACKEND:-auto}" = "oracle" ]; then
  if [ -z "${MATERIAL_FIT_REMOTE_BASE:-}" ] \
    || [ ! -x "$MATERIAL_FIT_REMOTE_BASE/bin/ensure_persistent_multiview_daemon.sh" ]; then
    echo "MATERIAL_FIT_RENDER_BACKEND=oracle requires MATERIAL_FIT_REMOTE_BASE with bin/ensure_persistent_multiview_daemon.sh" >&2
    exit 2
  fi
  set -- \
    --render-backend oracle \
    --oracle-base "$MATERIAL_FIT_REMOTE_BASE" \
    "$@"
fi

python -m material_fit.experiments.fish_core_experiment \
  --mode "$MODE" \
  --platform-name linux \
  --width "${MATERIAL_FIT_DEFAULT_WIDTH:-900}" \
  --height "${MATERIAL_FIT_DEFAULT_HEIGHT:-700}" \
  "$@"
