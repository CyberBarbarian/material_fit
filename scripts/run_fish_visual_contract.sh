#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
python -m material_fit.experiments.fish_visual_contract_experiment "$@"
