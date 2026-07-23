#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-60}"
export PIP_RETRIES="${PIP_RETRIES:-10}"

command -v python3 >/dev/null || { echo "python3 3.10+ is required" >&2; exit 1; }
echo "[1/5] Preparing Python and Node.js runtimes."
bash "$SCRIPT_DIR/ensure_node.sh"
if [[ -x "$REPO_ROOT/.runtime/node/bin/node" ]]; then
  export PATH="$REPO_ROOT/.runtime/node/bin:$PATH"
fi
command -v node >/dev/null || { echo "Node.js 18+ is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  if ! python3 -m venv --clear .venv; then
    echo "Unable to create .venv." >&2
    echo "On Debian/Ubuntu, run: sudo apt-get install -y python3-venv" >&2
    exit 1
  fi
fi
echo "[2/5] Installing the Python package and test dependencies."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test,perceptual]'
echo "[3/5] Installing the locked Node.js dependencies."
npm ci
if [[ "${1:-}" != "--skip-browser" ]]; then
  echo "[4/5] Installing and checking Playwright Chromium."
  if [[ "$(uname -s)" == "Linux" && "$(id -u)" -eq 0 ]]; then
    npm run browser:install-linux
  else
    npm run browser:install
  fi
  if ! npm run browser:check; then
    echo "Chromium health check failed; reinstalling the locked browser build." >&2
    npm run browser:reinstall
    npm run browser:check
  fi
else
  echo "[4/5] Skipping Playwright Chromium installation."
fi
echo "[5/5] Validating the checkout."
.venv/bin/python -m material_fit.doctor --repo-root "$REPO_ROOT"
echo "Bootstrap completed."
