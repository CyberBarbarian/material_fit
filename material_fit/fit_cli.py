"""Command-line argument parsing for ``fit_material``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


_OPTIMIZER_PRESETS = {"manual", "cma_mature_default", "subspace_cma_mature_default"}


def parse_fit_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Laya material auto-fit framework")
    parser.add_argument("--config", required=True, help="Path to fit_config.json")
    parser.add_argument("--dry-run", action="store_true", help="Do not invoke external renderer")
    parser.add_argument("--max-candidates", type=int, default=3, help="Probe candidates to emit for smoke test")
    parser.add_argument("--capture", action="store_true", help="Use capture_candidate contract instead of legacy render_candidate")
    parser.add_argument("--analyze-images", action="store_true", help="Analyze configured reference/candidate image pairs")
    parser.add_argument("--auto-adjust", action="store_true", help="Run the stage-aware analysis/adjustment loop")
    parser.add_argument("--iterations", type=int, default=50, help="Maximum auto-adjust loop iterations to run now")
    parser.add_argument("--target-score", type=float, default=None, help="Stop when the higher-is-better fit score reaches this value")
    parser.add_argument(
        "--optimizer-preset",
        choices=tuple(sorted(_OPTIMIZER_PRESETS)),
        default=None,
        help=(
            "Apply a named optimizer preset before individual CLI overrides. "
            "'cma_mature_default' enables the robust long-run CMA stack; "
            "'subspace_cma_mature_default' enables semantic low-dimensional CMA."
        ),
    )
    parser.add_argument("--write-candidate-lmat", action="store_true", help="Write adjusted candidate .lmat files under the output directory")
    parser.add_argument("--apply-lmat", action="store_true", help="Overwrite the configured Laya .lmat with the latest adjusted params, after creating a .bak")
    parser.add_argument("--capture-screen-after-apply", action="store_true", help="After --apply-lmat, wait for Laya to re-render and capture the desktop Laya region for the next analysis")
    parser.add_argument("--rerender-wait-ms", type=int, default=None, help="Milliseconds to wait after writing .lmat before screen capture")
    parser.add_argument("--screen-capture-region", default="", help="Optional desktop capture rectangle x,y,width,height; otherwise reuse the last saved region")
    parser.add_argument(
        "--screen-capture-max-keep",
        type=int,
        default=None,
        help=(
            "Cap the rolling laya_candidate_NN.png pool to this many "
            "most-recent files (oldest are pruned after each capture). "
            "Defaults to fit_config['screen_capture']['max_keep'] (30). "
            "Pass 0 to disable pruning (legacy behavior)."
        ),
    )
    parser.add_argument(
        "--fit-score-mode",
        choices=("linear", "perceptual", "human_accept", "research"),
        default=None,
        help=(
            "How to pick the 0..1 fit score. 'research' uses research_score/100; "
            "'human_accept' uses the tolerant "
            "material similarity score; 'perceptual' uses the stricter "
            "channel-weighted MAE + SSIM score; 'linear' keeps legacy MAE."
        ),
    )
    parser.add_argument(
        "--optimizer",
        choices=(
            "heuristic",
            "cma_cold",
            "cma_warm",
            "semantic_group",
            "adaptive_response_search",
            "pattern16",
            "semantic_group_legacy_081",
            "subspace_cma_es",
            "cold_start_hybrid",
        ),
        default=None,
        help=(
            "Which optimizer drives parameter proposals. 'heuristic' is the "
            "stage-aware channel-bias path; 'cma_cold' is vanilla CMA-ES; "
            "'cma_warm' is Warm-Started CMA-ES seeded from prior auto_adjust "
            "iterations; 'semantic_group' is the current response scheduler; "
            "'adaptive_response_search' is a global-best response evidence scheduler; "
            "'pattern16' is the validated 16D coordinate pattern-search mainline; "
            "'semantic_group_legacy_081' preserves the old pattern-search baseline; "
            "'subspace_cma_es' runs expensive CMA-ES in a small active subspace; "
            "'cold_start_hybrid' runs semantic anchors plus local search from zero. "
            "Defaults to config['optimizer'] or 'heuristic'."
        ),
    )
    parser.add_argument(
        "--cma-warm-start-iters",
        type=int,
        default=None,
        help="Cap how many prior iterations are fed into WS-CMA-ES (default 12).",
    )
    parser.add_argument(
        "--cma-warm-start-source",
        choices=("elite_archive_first", "elite_archive_only", "iteration_history", "none"),
        default=None,
        help=(
            "Choose which prior data source cma_warm uses: elite archive first "
            "(default), elite archive only, raw iteration history only, or none."
        ),
    )
    parser.add_argument(
        "--cma-population-size",
        type=int,
        default=None,
        help="Override CMA-ES population size; default uses 4 + 3*ln(dim).",
    )
    parser.add_argument(
        "--cma-sigma",
        type=float,
        default=None,
        help="Override initial CMA-ES sigma in normalized [0,1] space.",
    )
    parser.add_argument(
        "--cma-seed",
        type=int,
        default=None,
        help="Seed for CMA-ES sampling. Default uses non-deterministic seeding.",
    )
    parser.add_argument(
        "--cma-hint-bias-mix-ratio",
        type=float,
        default=None,
        help=(
            "[E-010] Mix-ratio in [0, 1] for blending the channel-level "
            "adjustment_hints into each CMA-ES proposal. 0.0 disables the "
            "bias (legacy behaviour), 0.30 is the recommended starting "
            "point. Default uses config['cma_es']['hint_bias_mix_ratio'] "
            "or 0.30."
        ),
    )
    parser.add_argument(
        "--cma-stagnation-patience",
        type=int,
        default=None,
        help=(
            "Stop CMA-ES when the best fit score has not improved by "
            "cma_stagnation_min_delta over this many evaluations. "
            "0 disables the check."
        ),
    )
    parser.add_argument(
        "--cma-stagnation-min-delta",
        type=float,
        default=None,
        help="Minimum fit-score improvement counted as progress for CMA-ES stagnation detection.",
    )
    parser.add_argument(
        "--cma-stagnation-min-evaluations",
        type=int,
        default=None,
        help="Minimum CMA-ES evaluations before stagnation detection may stop a run.",
    )
    parser.add_argument(
        "--cma-stagnation-max-restarts",
        type=int,
        default=None,
        help="Maximum CMA-ES restarts to perform on stagnation before stopping. 0 disables restarts.",
    )
    parser.add_argument(
        "--cma-continue-after-stagnation-restarts",
        action="store_true",
        help=(
            "Keep CMA-ES running after the configured stagnation restart budget is exhausted. "
            "Use this for long-budget runs that should stop only on target score or max iterations."
        ),
    )
    parser.add_argument(
        "--cma-restart-population-multiplier",
        type=float,
        default=None,
        help="Multiply CMA-ES population size by this factor after each stagnation restart. 1.0 keeps it fixed.",
    )
    parser.add_argument(
        "--cma-restart-population-schedule",
        choices=("ipop", "bipop"),
        default=None,
        help=(
            "Population schedule for stagnation restarts. "
            "'ipop' grows monotonically; 'bipop' alternates large IPOP restarts with small restarts."
        ),
    )
    parser.add_argument(
        "--cma-restart-center-mode",
        choices=("best", "random", "alternate"),
        default=None,
        help=(
            "Where stagnation restarts should place the new CMA-ES mean. "
            "'best' keeps local refinement; 'random' performs a multi-start restart inside bounds; "
            "'alternate' alternates best/random restart centers."
        ),
    )
    parser.add_argument(
        "--cma-restart-max-population-size",
        type=int,
        default=None,
        help="Optional cap for restart-grown CMA-ES population size.",
    )
    parser.add_argument(
        "--cma-initial-design-samples",
        type=int,
        default=None,
        help=(
            "Evaluate this many space-filling candidates before CMA-ES, "
            "then warm-start CMA-ES from their scored results. 0 disables the phase."
        ),
    )
    parser.add_argument(
        "--cma-initial-design-method",
        choices=("latin_hypercube", "local_coordinate_probe"),
        default=None,
        help="Initial design method used before CMA-ES.",
    )
    parser.add_argument(
        "--cma-initial-design-local-step-ratio",
        type=float,
        default=None,
        help=(
            "For local_coordinate_probe, perturb one normalized axis by this "
            "fraction of its encoded bounds. Default comes from config."
        ),
    )
    parser.add_argument(
        "--cma-initial-design-no-current",
        action="store_true",
        help="Do not include the current material parameters as the first initial-design sample.",
    )
    parser.add_argument(
        "--laya-refresh-check",
        action="store_true",
        help=(
            "Before running auto-adjust, write a magenta probe color to the "
            "target .lmat, capture, restore, capture again. If Laya did not "
            "visibly refresh, abort the whole run with a clear preflight "
            "report at output_dir/auto_adjust/preflight.json. Strongly "
            "recommended whenever you turn on --apply-lmat."
        ),
    )
    parser.add_argument(
        "--laya-refresh-check-param",
        default="u_BaseColor",
        help="Which Color uniform to write the probe value into (default u_BaseColor).",
    )
    parser.add_argument(
        "--laya-window-process",
        default=None,
        help=(
            "Process name (or regex) of the Laya editor window to bring "
            "to the foreground before each .lmat write and each capture. "
            "Default 'LayaAirIDE'. Required because Laya pauses rendering "
            "when its window is in the background. Set to '' to disable."
        ),
    )
    parser.add_argument(
        "--laya-window-title",
        default=None,
        help=(
            "Optional title pattern (regex/substring) to disambiguate "
            "between multiple Laya projects open at once. E.g., 'fish' "
            "to focus the 'fish' project window. Empty = match any."
        ),
    )
    return parser.parse_args(argv)
