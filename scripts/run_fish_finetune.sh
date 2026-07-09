#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec sh "$SCRIPT_DIR/run_fish_core_experiment.sh" finetune "$@"
