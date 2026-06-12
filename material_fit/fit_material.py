from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .auto_adjust.scoring import extract_perceptual_signals as _extract_perceptual_signals
from .auto_adjust.history import load_warm_start_history as _load_warm_start_history
from .auto_adjust.image_pairs import ImagePairCollectionError, collect_image_pairs as _collect_image_pairs
from .laya import lmat_io
from .laya.refresh_probe import ProbeConfig, resolve_probe_param, run_refresh_probe
from .laya.render_driver import RenderDriver
from .laya_capture.editor_bridge import LayaEditorCaptureError, trigger_editor_multiview_capture, trigger_editor_single_view_capture
from .laya.shader_parser import parse_laya_shader, shader_info_to_dict
from .laya.window_focus import FocusTarget, focus_laya_window
from .optimizer.adjustment_algorithm import (
    AdjustmentState,
    build_adjustment_policies,
    policies_to_fit_stages,
    save_adjustment_state,
    should_abort_global,
)
from .optimizer.parameter_search import build_initial_params, build_stage_plan, generate_probe_candidates
from .optimizer.semantic_graph import build_shader_effect_graph, graph_to_dict
from .optimizer.strategy import (
    CmaesStrategyConfig,
    OptimizerUnavailableError,
    StrategyContext,
    build_strategy,
    cmaes_strategy_config_from_dict,
    cmaes_strategy_config_to_dict,
)
from .shared.report import write_summary_report
from .unity.shader_parser import parse_unity_shaderlab
from .vision.diff_analysis import ImageDiffConfig, analyze_image_diff, analyze_multiview_pairs
from .vision.screen_capture import (
    DEFAULT_CAPTURE_DIR,
    DEFAULT_PREFIX,
    CaptureAnchor,
    capture_laya_region,
    parse_region,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Laya material auto-fit framework")
    parser.add_argument("--config", required=True, help="Path to fit_config.json")
    parser.add_argument("--dry-run", action="store_true", help="Do not invoke external renderer")
    parser.add_argument("--max-candidates", type=int, default=3, help="Probe candidates to emit for smoke test")
    parser.add_argument("--capture", action="store_true", help="Use capture_candidate contract instead of legacy render_candidate")
    parser.add_argument("--analyze-images", action="store_true", help="Analyze configured reference/candidate image pairs")
    parser.add_argument("--auto-adjust", action="store_true", help="Run the stage-aware analysis/adjustment loop")
    parser.add_argument("--iterations", type=int, default=50, help="Maximum auto-adjust loop iterations to run now")
    parser.add_argument("--target-score", type=float, default=None, help="Stop when the higher-is-better fit score reaches this value")
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
            "semantic_group_legacy_081",
            "subspace_cma_es",
        ),
        default=None,
        help=(
            "Which optimizer drives parameter proposals. 'heuristic' is the "
            "stage-aware channel-bias path; 'cma_cold' is vanilla CMA-ES; "
            "'cma_warm' is Warm-Started CMA-ES seeded from prior auto_adjust "
            "iterations; 'semantic_group' is the current response scheduler; "
            "'adaptive_response_search' is a global-best response evidence scheduler; "
            "'semantic_group_legacy_081' preserves the old pattern-search baseline; "
            "'subspace_cma_es' runs expensive CMA-ES in a small active subspace. Defaults to "
            "config['optimizer'] or 'heuristic'."
        ),
    )
    parser.add_argument(
        "--cma-warm-start-iters",
        type=int,
        default=None,
        help="Cap how many prior iterations are fed into WS-CMA-ES (default 12).",
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
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    project_root = config_path.resolve().parents[2]
    config = _load_external_config_fragments(config, project_root)
    output_dir = _resolve_path(project_root, config.get("output_dir", "tools/material_fit/output/default"))
    output_dir.mkdir(parents=True, exist_ok=True)

    laya_shader = parse_laya_shader(_resolve_path(project_root, config["laya_shader_path"]))
    unity_shader = None
    unity_shader_path = config.get("unity_shader_path")
    if unity_shader_path:
        unity_shader = parse_unity_shaderlab(_resolve_path(project_root, unity_shader_path))

    laya_material = lmat_io.load_lmat(_resolve_path(project_root, config["laya_material_path"]))
    laya_material_path = _resolve_path(project_root, config["laya_material_path"])
    laya_material_params = lmat_io.extract_params(laya_material)
    initial_params = build_initial_params(laya_material_params, laya_shader.params)
    configured_optimizer = (args.optimizer or str(config.get("optimizer", "heuristic"))).strip().lower()
    if configured_optimizer not in (
        "heuristic",
        "cma_cold",
        "cma_warm",
        "semantic_group",
        "adaptive_response_search",
        "semantic_group_legacy_081",
        "subspace_cma_es",
    ):
        configured_optimizer = "heuristic"
    adjustment_policies = build_adjustment_policies(laya_shader.params)
    adjustment_policies = _filter_policies_by_effect_graph(
        adjustment_policies,
        config.get("effect_graph"),
    )
    stages = policies_to_fit_stages(adjustment_policies) or build_stage_plan(laya_shader.params)
    stage_plan_payload: list[dict[str, Any]] = [stage.__dict__ for stage in stages]
    if configured_optimizer in (
        "semantic_group",
        "adaptive_response_search",
        "semantic_group_legacy_081",
        "subspace_cma_es",
    ):
        stage_plan_payload = _semantic_stage_plan_from_effect_graph(config.get("effect_graph")) or stage_plan_payload
    unity_material_params = _load_unity_material_params(config, project_root)

    _write_json(
        output_dir / "run_manifest.json",
        _build_run_manifest(
            config=config,
            optimizer=configured_optimizer,
            laya_shader=laya_shader,
            unity_shader=unity_shader,
            initial_params=initial_params,
            unity_material_params=unity_material_params,
            auto_adjust=args.auto_adjust,
            probe_candidates=bool(stages and not args.auto_adjust and max(args.max_candidates, 0) > 0),
        ),
    )
    _write_json(output_dir / "laya_shader_params.json", shader_info_to_dict(laya_shader))
    if unity_shader:
        _write_json(output_dir / "unity_shader_params.json", shader_info_to_dict(unity_shader))
    if unity_material_params:
        _write_json(output_dir / "unity_material_params.json", unity_material_params)
    _write_json(output_dir / "initial_params.json", initial_params)
    if _optimizer_needs_stage_artifacts(configured_optimizer):
        optimizer_dir = output_dir / "optimizer_artifacts" / configured_optimizer
        _write_json(optimizer_dir / "stage_plan.json", stage_plan_payload)
        _write_json(optimizer_dir / "adjustment_policies.json", [policy.__dict__ for policy in adjustment_policies])

    driver = RenderDriver(
        output_dir=output_dir,
        command=config.get("render_command"),
        dry_run=args.dry_run or bool(config.get("dry_run", True)),
        capture_config=config.get("laya_capture", {}),
    )
    emitted: list[dict[str, Any]] = []
    if stages and not args.auto_adjust:
        candidates = generate_probe_candidates(initial_params, stages[0], laya_shader.params)
        for index, candidate in enumerate(candidates[:max(args.max_candidates, 0)]):
            emitted.append(driver.capture_candidate(index, candidate) if args.capture else driver.render_candidate(index, candidate))

    image_analysis = []
    if args.analyze_images:
        image_pairs = _collect_image_pairs(config, project_root, output_dir)
        fit_score_mode = args.fit_score_mode or str(config.get("fit_score_mode", "research")).lower()
        if len(image_pairs) > 1:
            image_analysis = analyze_multiview_pairs(
                image_pairs,
                output_dir / "image_analysis",
                fit_score_mode=fit_score_mode,
                aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            )
        else:
            for index, pair in enumerate(image_pairs):
                image_analysis.append(
                    analyze_image_diff(
                        ImageDiffConfig(
                            reference_path=pair["reference"],
                            candidate_path=pair["candidate"],
                            mask_path=pair.get("mask"),
                            output_dir=output_dir / "image_analysis" / f"pair_{index:02d}",
                        )
                    )
                )
        _write_json(output_dir / "image_analysis.json", image_analysis)

    adjustment_result: dict[str, Any] | None = None
    if args.auto_adjust:
        fit_score_mode = args.fit_score_mode or str(config.get("fit_score_mode", "research")).lower()
        if fit_score_mode not in ("linear", "perceptual", "human_accept", "research"):
            fit_score_mode = "research"
        optimizer = configured_optimizer
        cma_es_config = cmaes_strategy_config_from_dict(config.get("cma_es"))
        cma_es_config = _override_cmaes_from_cli(args, cma_es_config)
        rerender_wait_ms_value = int(args.rerender_wait_ms if args.rerender_wait_ms is not None else config.get("rerender_wait_ms", 1200))
        editor_capture_enabled = bool(
            isinstance(config.get("laya_editor_capture"), dict)
            and config["laya_editor_capture"].get("enabled")
        )
        capture_screen_after_apply_value = (
            False
            if editor_capture_enabled
            else args.capture_screen_after_apply or bool(config.get("capture_screen_after_apply", False))
        )

        # Build a focus callback that brings the Laya window forward
        # before each .lmat write and each capture. Without this, Laya
        # silently pauses rendering when its window loses focus
        # (validated in E-007 of ExperimentLog.md), so probe / capture
        # both freeze on a stale frame.
        focus_callback = None if editor_capture_enabled else _build_focus_callback(args, config)

        # The refresh probe is a manual diagnostic / project preflight tool.
        # Formal auto-adjust runs should not read a config default and write an
        # extra probe value before the first iteration, because that can disturb
        # the user's intended initial material state.
        if args.laya_refresh_check and args.apply_lmat:
            preflight = _run_laya_refresh_preflight(
                config=config,
                project_root=project_root,
                output_dir=output_dir,
                laya_material_path=laya_material_path,
                laya_shader_params=laya_shader.params,
                rerender_wait_ms=rerender_wait_ms_value,
                screen_capture_region=args.screen_capture_region,
                probe_param=args.laya_refresh_check_param,
                focus_callback=focus_callback,
            )
            if not preflight.get("success"):
                print(
                    "[preflight] Laya refresh probe FAILED — aborting before any "
                    "real auto-adjust write.",
                    flush=True,
                )
                print(f"[preflight] {preflight.get('reason')}", flush=True)
                # Persist the verdict in a stable place so the UI can
                # surface it without scraping stdout.
                _write_json(output_dir / "auto_adjust" / "preflight.json", preflight)
                return 0  # CLI exit 0 — preflight is informational, not a crash

        adjustment_result = _run_auto_adjustment(
            config=config,
            project_root=project_root,
            output_dir=output_dir,
            laya_material_path=laya_material_path,
            laya_shader_params=laya_shader.params,
            initial_params=initial_params,
            policies=adjustment_policies,
            unity_material_params=unity_material_params,
            driver=driver,
            iterations=max(args.iterations, 1),
            target_score=float(args.target_score if args.target_score is not None else config.get("auto_adjust_target_score", 0.5)),
            use_capture=args.capture,
            write_candidate_lmat=args.write_candidate_lmat,
            apply_lmat=args.apply_lmat,
            capture_screen_after_apply=capture_screen_after_apply_value,
            rerender_wait_ms=rerender_wait_ms_value,
            screen_capture_region=args.screen_capture_region,
            screen_capture_max_keep=args.screen_capture_max_keep,
            fit_score_mode=fit_score_mode,
            optimizer=optimizer,
            cma_es_config=cma_es_config,
            focus_callback=focus_callback,
        )

    write_summary_report(
        output_dir / "report.md",
        laya_shader=laya_shader,
        unity_shader=unity_shader,
        laya_material_params=laya_material_params,
        stages=stages if _optimizer_needs_stage_artifacts(configured_optimizer) else [],
        extra={"emitted_candidates": emitted, "image_analysis": image_analysis, "adjustment_result": adjustment_result},
    )
    print(f"Material fit framework prepared: {output_dir}")
    print(f"Laya shader params: {len(laya_shader.params)}")
    print(f"Stages: {len(stages)}")
    print(f"Probe candidates: {len(emitted)}")
    if adjustment_result:
        print(f"Auto-adjust iterations: {len(adjustment_result.get('iterations', []))}")
        print(f"Auto-adjust best score: {adjustment_result.get('best_score')}")
        print(f"Auto-adjust best fit score: {adjustment_result.get('best_fit_score')}")
    return 0


def _resolve_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _load_external_config_fragments(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Load bulky run context files referenced by the lean fit_config."""

    payload = dict(config)
    semantic_context_path = payload.get("semantic_context_path")
    if semantic_context_path:
        path = _resolve_path(project_root, str(semantic_context_path))
        try:
            semantic_context = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"failed to load semantic_context_path: {path}") from exc
        if isinstance(semantic_context, dict):
            for key, value in semantic_context.items():
                payload.setdefault(key, value)
    return payload


def _optimizer_needs_stage_artifacts(optimizer: str) -> bool:
    return optimizer in {"heuristic", "semantic_group", "semantic_group_legacy_081"}


def _build_run_manifest(
    *,
    config: dict[str, Any],
    optimizer: str,
    laya_shader: Any,
    unity_shader: Any,
    initial_params: dict[str, Any],
    unity_material_params: dict[str, Any],
    auto_adjust: bool,
    probe_candidates: bool,
) -> dict[str, Any]:
    semantic_context_path = config.get("semantic_context_path")
    return {
        "schema_version": 1,
        "case_name": config.get("case_name"),
        "optimizer": optimizer,
        "fit_score_mode": config.get("fit_score_mode", "research"),
        "auto_adjust_mode": config.get("auto_adjust_mode", "fresh_fit"),
        "target_score": config.get("auto_adjust_target_score"),
        "laya_shader": {
            "path": str(getattr(laya_shader, "path", "") or ""),
            "name": getattr(laya_shader, "name", ""),
            "param_count": len(getattr(laya_shader, "params", []) or []),
            "define_count": len(getattr(laya_shader, "defines", []) or []),
        },
        "unity_shader": (
            {
                "path": str(getattr(unity_shader, "path", "") or ""),
                "name": getattr(unity_shader, "name", ""),
                "param_count": len(getattr(unity_shader, "params", []) or []),
                "define_count": len(getattr(unity_shader, "defines", []) or []),
            }
            if unity_shader is not None
            else None
        ),
        "initial_param_count": len(initial_params),
        "unity_material_param_count": len(unity_material_params),
        "semantic_context_path": semantic_context_path,
        "artifact_policy": {
            "stage_artifacts": _optimizer_needs_stage_artifacts(optimizer),
            "probe_candidates": bool(probe_candidates),
            "auto_adjust": bool(auto_adjust),
        },
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_unity_material_params(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    value = config.get("unity_material_params_path")
    if not value:
        return {}
    path = _resolve_path(project_root, value)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and isinstance(data.get("params"), dict):
        return data["params"]
    if isinstance(data, dict) and isinstance(data.get("properties"), dict):
        return data["properties"]
    return data if isinstance(data, dict) else {}


def _filter_policies_by_effect_graph(
    policies: list[Any],
    effect_graph: Any,
) -> list[Any]:
    """Apply human semantic-group disables to the legacy heuristic stages too."""

    if not isinstance(effect_graph, dict):
        return policies
    params = effect_graph.get("params")
    if not isinstance(params, dict):
        return policies
    blocked = {
        str(name)
        for name, sem in params.items()
        if isinstance(sem, dict) and sem.get("searchable") is False
    }
    if not blocked:
        return policies
    out: list[Any] = []
    for policy in policies:
        kept = [name for name in policy.params if name not in blocked]
        if not kept:
            continue
        out.append(
            type(policy)(
                name=policy.name,
                description=policy.description,
                channels=policy.channels,
                params=kept,
                max_iterations=policy.max_iterations,
                target_score=policy.target_score,
            )
        )
    return out


def _semantic_stage_plan_from_effect_graph(effect_graph: Any) -> list[dict[str, Any]]:
    if not isinstance(effect_graph, dict):
        return []
    groups = effect_graph.get("groups")
    params = effect_graph.get("params")
    if not isinstance(groups, dict) or not isinstance(params, dict):
        return []
    plan: list[dict[str, Any]] = []
    for name, raw in groups.items():
        if not isinstance(raw, dict):
            continue
        search_params = [
            str(param)
            for param in raw.get("search_params", [])
            if isinstance(param, str)
            and isinstance(params.get(param), dict)
            and params[param].get("searchable") is not False
        ]
        if not search_params:
            continue
        order = int(raw.get("order", 0) or 0)
        plan.append(
            {
                "name": str(raw.get("name") or name),
                "params": search_params,
                "description": str(raw.get("reason") or "semantic group search"),
                "order": order,
                "channels": [str(item) for item in raw.get("channels", []) if isinstance(item, str)],
                "scheduler": "semantic_group_round_robin",
                "visit_budget_hint": max(6, min(18, len(search_params) * 3)),
            }
        )
    plan.sort(
        key=lambda item: (
            int(item.get("order", 0) or 0) if int(item.get("order", 0) or 0) > 0 else 10_000,
            str(item.get("name", "")),
        )
    )
    return plan


def _run_auto_adjustment(
    *,
    config: dict[str, Any],
    project_root: Path,
    output_dir: Path,
    laya_material_path: Path,
    laya_shader_params: list[Any],
    initial_params: dict[str, Any],
    policies: list[Any],
    unity_material_params: dict[str, Any],
    driver: RenderDriver,
    iterations: int,
    target_score: float,
    use_capture: bool,
    write_candidate_lmat: bool,
    apply_lmat: bool,
    capture_screen_after_apply: bool,
    rerender_wait_ms: int,
    screen_capture_region: str,
    screen_capture_max_keep: int | None = None,
    fit_score_mode: str = "linear",
    optimizer: str = "heuristic",
    cma_es_config: CmaesStrategyConfig | None = None,
    focus_callback: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the fourth part: analysis-driven adjustment orchestration."""

    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)
    external_backup_dir = _resolve_external_backup_dir(config, project_root, output_dir)
    state = AdjustmentState(best_params=dict(initial_params), best_fit_params=dict(initial_params))
    current_params = dict(initial_params)
    result_iterations: list[dict[str, Any]] = []
    iteration_series: list[dict[str, Any]] = []
    snapshot_iterations: set[int] = set()
    full_payloads: dict[int, dict[str, Any]] = {}
    best_fit_score = -math.inf
    candidate_override: str | dict[str, str] | None = None
    require_real_closed_loop = apply_lmat and capture_screen_after_apply
    terminal_reason: str | None = None

    warm_history: list[tuple[dict[str, Any], float]] = []
    if optimizer == "cma_warm":
        warm_history = _load_warm_start_history(
            auto_dir,
            limit=(cma_es_config.warm_start_iters if cma_es_config else 12),
        )
    semantic_graph = config.get("effect_graph") if isinstance(config.get("effect_graph"), dict) else None
    if semantic_graph is None:
        try:
            material_defines = lmat_io.extract_defines(lmat_io.load_lmat(laya_material_path))
        except Exception:  # noqa: BLE001
            material_defines = []
        semantic_graph = graph_to_dict(
            build_shader_effect_graph(
                laya_shader_params,
                material_params=initial_params,
                material_defines=material_defines,
            )
        )

    try:
        strategy = build_strategy(
            optimizer=optimizer,
            initial_params=initial_params,
            shader_params=laya_shader_params,
            policies=policies,
            unity_material_params=unity_material_params,
            cma_es_config=cma_es_config,
            warm_start_history=warm_history,
            semantic_graph=semantic_graph,
            auto_adjust_mode=str(config.get("auto_adjust_mode", "fresh_fit")),
        )
    except (OptimizerUnavailableError, ValueError) as exc:
        payload = {
            "status": "configuration_error",
            "reason": str(exc),
            "optimizer": optimizer,
            "target_score": target_score,
            "iterations": [],
        }
        _write_json(auto_dir / "auto_adjust_result.json", payload)
        return payload

    analysis_performance = _resolve_analysis_performance(config)
    snapshot_interval = int(analysis_performance["snapshot_interval"])
    keep_last_n_artifacts = int(analysis_performance["keep_last_n_artifacts"])
    multiview_workers = analysis_performance["multiview_workers"]
    for local_index in range(iterations):
        iteration_started = time.perf_counter()
        iteration = state.iteration
        timing: dict[str, Any] = {
            "snapshot_interval": snapshot_interval,
            "is_snapshot": _is_snapshot_iteration(iteration, snapshot_interval),
            "perceptual_optional_enabled": _is_snapshot_iteration(iteration, snapshot_interval),
            "diff_visual_enabled": _is_snapshot_iteration(iteration, snapshot_interval),
            "keep_last_n_artifacts": keep_last_n_artifacts,
            "multiview_workers": multiview_workers,
        }
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        initial_editor_capture_result: dict[str, Any] | None = None
        if candidate_override is None:
            timing_step = time.perf_counter()
            try:
                initial_editor_capture_result = trigger_editor_multiview_capture(
                    config=config,
                    project_root=project_root,
                    iteration_dir=iteration_dir / "current",
                    iteration=iteration,
                    laya_material_path=laya_material_path,
                )
            except LayaEditorCaptureError as exc:
                initial_editor_capture_result = {
                    "status": "failed",
                    "error": str(exc),
                    "screenshots": [],
                }
            timing["initial_editor_capture_ms"] = _elapsed_ms(timing_step)
            if initial_editor_capture_result is not None:
                candidate_overrides = initial_editor_capture_result.get("candidate_overrides")
                if isinstance(candidate_overrides, dict) and candidate_overrides:
                    candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}

        try:
            timing_step = time.perf_counter()
            image_pairs = _collect_image_pairs(config, project_root, output_dir, candidate_override=candidate_override)
            timing["collect_image_pairs_ms"] = _elapsed_ms(timing_step)
        except ImagePairCollectionError as exc:
            payload = {
                "status": "failed",
                "reason": str(exc),
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload
        if not image_pairs:
            payload = {
                "status": "pending",
                "reason": "No image_pairs/reference_images configured and no auto reference/candidate pair found.",
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

        pair = image_pairs[0]
        timing_step = time.perf_counter()
        multiview_result = analyze_multiview_pairs(
            image_pairs,
            iteration_dir / "image_analysis",
            fit_score_mode=fit_score_mode,
            aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            compute_perceptual_optional=bool(timing["perceptual_optional_enabled"]),
            generate_diff_image=bool(timing["diff_visual_enabled"]),
            workers=multiview_workers,
        )
        timing["analyze_multiview_ms"] = _elapsed_ms(timing_step)
        multiview_analysis = (
            multiview_result.get("multiview_analysis")
            if isinstance(multiview_result.get("multiview_analysis"), dict)
            else {}
        )
        multiview_summary = multiview_analysis.get("summary") if isinstance(multiview_analysis.get("summary"), dict) else {}
        analysis = dict(multiview_result.get("strategy_analysis") if isinstance(multiview_result.get("strategy_analysis"), dict) else {})
        diff_score = _number_or_default(multiview_summary.get("mean_diff_score"), math.inf)
        fit_score = _number_or_default(
            multiview_summary.get("optimization_fit_score"),
            _number_or_default(multiview_summary.get("mean_fit_score"), -math.inf),
        )
        if not analysis:
            analysis = {"status": "pending", "score": diff_score, "multiview": multiview_analysis}
        analysis["score"] = diff_score
        analysis["fit_score"] = fit_score
        analysis["optimization_fit_score"] = fit_score
        analysis["optimization_fit_score_source"] = multiview_summary.get("optimization_fit_score_source")
        analysis["multiview"] = multiview_analysis
        is_new_best = fit_score > best_fit_score
        if is_new_best:
            best_fit_score = fit_score
        if fit_score > state.best_fit_score:
            state.best_fit_score = fit_score
            state.best_fit_params = dict(current_params)
        if diff_score < state.best_score:
            state.best_score = diff_score
            state.best_params = dict(current_params)

        if fit_score >= target_score and not (require_real_closed_loop and not result_iterations):
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "target_score": target_score,
                "selected_stage": "target_reached",
                "decision": {"stop_reason": "target_score_reached"},
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = "target_reached"
            break

        # E-010: stochastic strategies (CMA-ES) opt out of this check
        # because individual proposals are *expected* to be worse than
        # the running best in the early generations of a 49-dim run.
        # See ``ExperimentLog.md`` E-010 for the diagnostic that led
        # here. ``HeuristicStrategy.wants_global_no_improve_check()``
        # still returns True so legacy behaviour is preserved.
        if strategy.wants_global_no_improve_check() and should_abort_global(state):
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "target_score": target_score,
                "selected_stage": "global_no_improvement",
                "decision": {
                    "stop_reason": "global_no_improvement",
                    "global_no_improve": state.global_no_improve,
                },
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = "global_no_improvement"
            break

        if optimizer == "heuristic" and not policies:
            payload = {"status": "pending", "reason": "No adjustable shader parameters available.", "target_score": target_score, "best_fit_score": best_fit_score, "iterations": result_iterations}
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

        timing_step = time.perf_counter()
        next_params, decision = strategy.propose(
            StrategyContext(
                iteration=iteration,
                current_params=current_params,
                analysis=analysis,
                diff_score=diff_score,
                fit_score=fit_score,
                state=state,
            )
        )
        timing["strategy_propose_ms"] = _elapsed_ms(timing_step)
        if decision.get("stop_reason") == "no_policies":
            payload = {"status": "pending", "reason": "No adjustable shader parameters available.", "target_score": target_score, "best_fit_score": best_fit_score, "iterations": result_iterations}
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload
        # Phase-summary 2026-05-08 follow-up: if SemanticGroupStrategy
        # has marked every group exhausted there is *nothing* worth
        # writing — re-applying the unchanged base params would just
        # waste a full Laya re-render + screenshot cycle and produce a
        # phantom iteration with stage=None that historically crashed
        # the iteration_payload builder. Bail out here with the
        # current best params intact and let the outer "completed"
        # block summarise normally.
        early_stop_reasons = {
            "all_semantic_groups_exhausted",
            "no_semantic_groups",
            "semantic_groups_exhausted",
        }
        if decision.get("stop_reason") in early_stop_reasons:
            print(
                f"[strategy] {decision.get('stop_reason')} at iter {iteration} — "
                f"breaking out of auto_adjust loop early.",
                flush=True,
            )
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "target_score": target_score,
                "selected_stage": None,
                "decision": decision,
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = str(decision.get("stop_reason") or "strategy_stopped")
            break
        if diff_score < state.best_score - 1e-6:
            state.global_no_improve = 0
        else:
            state.global_no_improve += 1
        decision["global_no_improve"] = state.global_no_improve

        candidate_dir = iteration_dir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        params_path = candidate_dir / "params.json"
        timing_step = time.perf_counter()
        _write_json(params_path, next_params)
        candidate_lmat_path = ""
        if write_candidate_lmat or apply_lmat:
            candidate_lmat_path = str(candidate_dir / laya_material_path.name)
            lmat_io.write_candidate_lmat(
                laya_material_path,
                candidate_lmat_path,
                next_params,
                allow_missing_keys=True,
            )
        timing["write_candidate_ms"] = _elapsed_ms(timing_step)
        focus_log: list[dict[str, Any]] = []
        if apply_lmat:
            # Focus Laya BEFORE the .lmat write so its file watcher
            # actually fires and re-renders. Background Laya silently
            # queues file events but does not redraw — see E-007.
            if focus_callback is not None:
                focus_log.append(focus_callback(f"iter_{iteration:04d}_before_lmat_write"))
            backup_path = lmat_io.backup_lmat(
                laya_material_path,
                suffix=f".auto_adjust_{iteration:04d}.bak",
                target_dir=external_backup_dir,
            )
            lmat_io.write_candidate_lmat(
                laya_material_path,
                laya_material_path,
                next_params,
                allow_missing_keys=True,
            )
            decision["applied_lmat"] = str(laya_material_path)
            decision["backup_lmat"] = str(backup_path)

        timing_step = time.perf_counter()
        try:
            editor_capture_result = trigger_editor_multiview_capture(
                config=config,
                project_root=project_root,
                iteration_dir=iteration_dir / "candidate",
                iteration=iteration,
                laya_material_path=laya_material_path,
            )
        except LayaEditorCaptureError as exc:
            editor_capture_result = {
                "status": "failed",
                "error": str(exc),
                "screenshots": [],
            }
        timing["candidate_capture_ms"] = _elapsed_ms(timing_step)
        if editor_capture_result is not None:
            render_result = editor_capture_result
        else:
            render_result = driver.capture_candidate(iteration, next_params) if use_capture else driver.render_candidate(iteration, next_params)
        screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
        candidate_overrides = render_result.get("candidate_overrides") if isinstance(render_result, dict) else None
        if isinstance(candidate_overrides, dict) and candidate_overrides:
            candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}
        elif screenshots:
            candidate_override = str(screenshots[0])

        screen_capture_result: dict[str, Any] | None = None
        if capture_screen_after_apply:
            timing_step = time.perf_counter()
            if not apply_lmat:
                decision["screen_capture_after_apply_skipped"] = "requires --apply-lmat because this mode verifies the real .lmat write path"
            else:
                screen_capture_cfg = config.get("screen_capture", {}) if isinstance(config.get("screen_capture"), dict) else {}
                capture_dir = _resolve_path(project_root, screen_capture_cfg.get("capture_dir", str(DEFAULT_CAPTURE_DIR)))
                state_file_value = screen_capture_cfg.get("state_file")
                state_file = _resolve_path(project_root, state_file_value) if state_file_value else capture_dir / ".capture_region.json"
                region_text = screen_capture_region or str(screen_capture_cfg.get("region", ""))
                explicit_region = parse_region(region_text) if region_text else None
                wait_cfg = config.get("dynamic_rerender_wait", {}) if isinstance(config.get("dynamic_rerender_wait"), dict) else {}
                dynamic_wait_enabled = bool(wait_cfg.get("enabled", True))
                if dynamic_wait_enabled and rerender_wait_ms > 0:
                    wait_payload = _wait_for_visual_refresh(
                        previous_candidate_path=pair.get("candidate"),
                        max_wait_ms=rerender_wait_ms,
                        interval_ms=int(wait_cfg.get("interval_ms", 200)),
                        min_wait_ms=int(wait_cfg.get("min_wait_ms", 250)),
                        diff_threshold=float(wait_cfg.get("diff_threshold", 0.25)),
                        capture_dir=capture_dir,
                        region=explicit_region,
                        reuse_last=explicit_region is None,
                        state_file=state_file,
                        anchor=_build_capture_anchor(config),
                        focus_callback=focus_callback,
                    )
                    decision["dynamic_rerender_wait"] = wait_payload
                    if not wait_payload.get("changed"):
                        time.sleep(max(rerender_wait_ms - int(wait_payload.get("elapsed_ms", 0)), 0) / 1000.0)
                elif rerender_wait_ms > 0:
                    time.sleep(rerender_wait_ms / 1000.0)
                # Focus Laya again right before the screenshot. The
                # rerender_wait_ms sleep above can give other windows
                # time to steal focus (e.g., notifications), so we
                # re-assert focus to guarantee a fresh frame is on
                # screen when GDI grabs the pixels.
                if focus_callback is not None:
                    focus_log.append(focus_callback(f"iter_{iteration:04d}_before_capture"))
                # E-012: cap the rolling ``prefix_NN.png`` pool. CLI
                # override > config > default 30. Set <= 0 to disable
                # pruning entirely (matches legacy behavior).
                max_keep_raw = (
                    screen_capture_max_keep
                    if screen_capture_max_keep is not None
                    else screen_capture_cfg.get("max_keep")
                )
                try:
                    max_keep_int = int(max_keep_raw) if max_keep_raw is not None else 30
                except (TypeError, ValueError):
                    max_keep_int = 30
                effective_max_keep: int | None = max_keep_int if max_keep_int > 0 else None
                screen_capture_result = capture_laya_region(
                    region=explicit_region,
                    reuse_last=explicit_region is None,
                    capture_dir=capture_dir,
                    state_file=state_file,
                    prefix=str(screen_capture_cfg.get("prefix", DEFAULT_PREFIX)),
                    dry_run=False,
                    anchor=_build_capture_anchor(config),
                    max_keep=effective_max_keep,
                )
                candidate_override = str(screen_capture_result["output_path"])
            timing["screen_capture_after_apply_ms"] = _elapsed_ms(timing_step)
        if focus_log:
            decision["focus_log"] = focus_log
        # P0 phase-summary 2026-05-08 follow-up: SemanticGroupStrategy
        # legitimately returns ``decision = {"stage": None,
        # "stop_reason": "all_semantic_groups_exhausted"}`` when every
        # group has either probed-out or run out of axes. The previous
        # ``decision.get("stage", {}).get("name")`` call assumed the
        # ``stage`` slot was always at least an empty dict; with the new
        # strategies that's no longer true and the run died at iter_30
        # with ``AttributeError: 'NoneType' object has no attribute
        # 'get'``. Treat any falsy stage payload as "no stage selected"
        # rather than crashing — and let the strategy_stop_reason path
        # below break out of the loop cleanly.
        decision_stage = decision.get("stage")
        if isinstance(decision_stage, dict):
            selected_stage_name = decision_stage.get("name")
        else:
            selected_stage_name = None
        iteration_payload = {
            "iteration": iteration,
            "input_pair": pair,
            "input_pairs": image_pairs,
            "diff_score_before": diff_score,
            "fit_score_before": fit_score,
            "target_score": target_score,
            "selected_stage": selected_stage_name,
            "decision": decision,
            "params_path": str(params_path),
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "initial_editor_capture_result": initial_editor_capture_result,
            "screen_capture_after_apply": screen_capture_result,
            # Keep both strict and tolerant signals next to the headline
            # fit_score so post-mortems can tell whether a regression came
            # from MAE drift, SSIM drift, auto-mask coverage, or human-score
            # component drift.
            "perceptual_signals": _extract_perceptual_signals(analysis),
            "multiview_analysis": multiview_analysis,
            "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
        }
        strategy_stop = strategy.stop_reason()
        if strategy_stop:
            iteration_payload["decision"]["strategy_stop_reason"] = strategy_stop
        is_best_iteration = is_new_best
        _record_iteration_outputs(
            auto_dir=auto_dir,
            iteration_payload=iteration_payload,
            result_iterations=result_iterations,
            iteration_series=iteration_series,
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            is_snapshot=bool(timing["is_snapshot"]),
            is_best=is_best_iteration,
        )
        _prune_iteration_artifacts(
            auto_dir,
            iteration_series,
            current_iteration=iteration,
            snapshot_interval=snapshot_interval,
            keep_last_n=keep_last_n_artifacts,
            always_keep_best=bool(analysis_performance["always_keep_best_artifact"]),
            always_keep_first=bool(analysis_performance["always_keep_first_artifact"]),
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
        )
        current_params = next_params
        state.iteration += 1
        if strategy_stop:
            terminal_reason = strategy_stop
            break

    best_fit_params = dict(state.best_fit_params or state.best_params or current_params)
    best_dir = auto_dir / "best"
    _write_json(best_dir / "params.json", best_fit_params)
    best_lmat_path = ""
    if write_candidate_lmat or apply_lmat:
        best_lmat_path = str(best_dir / laya_material_path.name)
        lmat_io.write_candidate_lmat(
            laya_material_path,
            best_lmat_path,
            best_fit_params,
            allow_missing_keys=True,
        )
    if apply_lmat and best_fit_params:
        backup_path = lmat_io.backup_lmat(
            laya_material_path,
            suffix=".auto_adjust_best_guard.bak",
            target_dir=external_backup_dir,
        )
        lmat_io.write_candidate_lmat(
            laya_material_path,
            laya_material_path,
            best_fit_params,
            allow_missing_keys=True,
        )
        final_best_restore = {
            "applied_lmat": str(laya_material_path),
            "backup_lmat": str(backup_path),
        }
    else:
        final_best_restore = None

    # The historical full state duplicated every iteration payload and made
    # long runs huge. Persist only the resumable/high-level state plus a compact
    # series file for UI timelines.
    state.history = list(iteration_series)
    save_adjustment_state(auto_dir / "state.json", state)
    if iteration_series:
        final_iteration = int(iteration_series[-1].get("iteration", len(iteration_series) - 1))
        snapshot_iterations.add(final_iteration)
        if keep_last_n_artifacts > 0:
            for item in iteration_series[-keep_last_n_artifacts:]:
                value = item.get("iteration")
                if isinstance(value, int):
                    snapshot_iterations.add(value)
        best_iteration = _best_recorded_iteration(iteration_series)
        if best_iteration is not None:
            snapshot_iterations.add(best_iteration)
            best_payload = full_payloads.get(best_iteration)
            if isinstance(best_payload, dict):
                _write_json(auto_dir / f"iter_{best_iteration:04d}" / "decision.json", best_payload)
        for snapshot_iteration in snapshot_iterations:
            snapshot_payload = full_payloads.get(snapshot_iteration)
            if isinstance(snapshot_payload, dict):
                _write_json(auto_dir / f"iter_{snapshot_iteration:04d}" / "decision.json", snapshot_payload)
        _mark_series_snapshots(iteration_series, snapshot_iterations)
        _write_json(auto_dir / "iteration_series.json", iteration_series)
        _write_snapshot_index(auto_dir, iteration_series, snapshot_iterations)
        _prune_iteration_artifacts(
            auto_dir,
            iteration_series,
            current_iteration=final_iteration,
            snapshot_interval=snapshot_interval,
            keep_last_n=keep_last_n_artifacts,
            always_keep_best=bool(analysis_performance["always_keep_best_artifact"]),
            always_keep_first=bool(analysis_performance["always_keep_first_artifact"]),
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            final_cleanup=True,
        )
    optimizer_research_summary = strategy.research_summary()
    if isinstance(optimizer_research_summary, dict) and optimizer_research_summary:
        _write_json(
            output_dir / "optimizer_artifacts" / optimizer / "research_summary.json",
            optimizer_research_summary,
        )
    final_status = _resolve_auto_adjust_status(
        best_fit_score=best_fit_score,
        target_score=target_score,
        terminal_reason=terminal_reason,
        completed_iterations=len(result_iterations),
        requested_iterations=iterations,
        optimizer_research_summary=optimizer_research_summary,
    )
    payload = {
        "status": final_status,
        "terminal_reason": terminal_reason,
        "target_score": target_score,
        "best_score": state.best_score,
        "best_fit_score": best_fit_score,
        "best_params": best_fit_params,
        "best_fit_params": best_fit_params,
        "best_lmat_path": best_lmat_path,
        "final_best_restore": final_best_restore,
        "best_guard": {
            "enabled": True,
            "selection_metric": "fit_score",
            "note": "Final output is restored to best-fit params instead of the last explored candidate.",
        },
        "iterations": iteration_series,
        "iteration_series_path": str(auto_dir / "iteration_series.json"),
        "snapshot_index_path": str(auto_dir / "snapshot_index.json"),
        "state_path": str(auto_dir / "state.json"),
        "fit_score_mode": fit_score_mode,
        "optimizer": optimizer,
        "cma_es_config": (
            cmaes_strategy_config_to_dict(cma_es_config)
            if cma_es_config and optimizer in ("cma_cold", "cma_warm")
            else None
        ),
        "warm_start_history_size": len(warm_history) if optimizer == "cma_warm" else 0,
        "effect_graph": semantic_graph,
        "optimizer_research_summary": optimizer_research_summary,
    }
    _write_json(auto_dir / "auto_adjust_result.json", payload)
    return payload


def _resolve_auto_adjust_status(
    *,
    best_fit_score: float,
    target_score: float,
    terminal_reason: str | None,
    completed_iterations: int,
    requested_iterations: int,
    optimizer_research_summary: dict[str, Any],
) -> str:
    if best_fit_score >= target_score:
        return "target_reached"
    if terminal_reason in {"all_semantic_groups_exhausted", "semantic_groups_exhausted"}:
        phase = str(optimizer_research_summary.get("phase") or "")
        return "breakthrough_exhausted" if phase == "breakthrough" else terminal_reason
    if terminal_reason:
        return terminal_reason
    if completed_iterations >= requested_iterations:
        return "max_iterations_reached"
    return "stopped"


def _resolve_analysis_performance(config: dict[str, Any]) -> dict[str, Any]:
    perf = config.get("analysis_performance")
    perf = perf if isinstance(perf, dict) else {}
    snapshot_interval = _coerce_interval(
        perf.get("snapshot_interval"),
        50,
    )
    keep_last_n = _coerce_interval(perf.get("keep_last_n_artifacts"), 5)
    workers = perf.get("multiview_workers", config.get("multiview_analysis_workers", 1))
    if isinstance(workers, str):
        workers_value: int | str = workers.strip().lower() or "auto"
    else:
        try:
            workers_value = int(workers)
        except (TypeError, ValueError):
            workers_value = 1
    return {
        "multiview_workers": workers_value,
        "snapshot_interval": snapshot_interval,
        "keep_last_n_artifacts": keep_last_n,
        "always_keep_best_artifact": bool(perf.get("always_keep_best_artifact", True)),
        "always_keep_first_artifact": bool(perf.get("always_keep_first_artifact", True)),
    }


def _coerce_interval(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(fallback))


def _is_snapshot_iteration(iteration: int, interval: int) -> bool:
    if iteration == 0:
        return True
    return interval > 0 and iteration % interval == 0


def _record_iteration_outputs(
    *,
    auto_dir: Path,
    iteration_payload: dict[str, Any],
    result_iterations: list[dict[str, Any]],
    iteration_series: list[dict[str, Any]],
    snapshot_iterations: set[int],
    full_payloads: dict[int, dict[str, Any]],
    is_snapshot: bool,
    is_best: bool,
) -> None:
    iteration = int(iteration_payload.get("iteration", len(iteration_series)))
    summary = _iteration_series_entry(iteration_payload, is_snapshot=is_snapshot, is_best=is_best)
    iteration_series.append(summary)
    result_iterations.append(summary)
    full_payloads[iteration] = iteration_payload
    if is_snapshot:
        snapshot_iterations.add(iteration)
        _write_json(auto_dir / f"iter_{iteration:04d}" / "decision.json", iteration_payload)
    _write_json(auto_dir / "iteration_series.json", iteration_series)
    _write_snapshot_index(auto_dir, iteration_series, snapshot_iterations)


def _iteration_series_entry(
    iteration_payload: dict[str, Any],
    *,
    is_snapshot: bool,
    is_best: bool,
) -> dict[str, Any]:
    decision = iteration_payload.get("decision") if isinstance(iteration_payload.get("decision"), dict) else {}
    perceptual = (
        iteration_payload.get("perceptual_signals")
        if isinstance(iteration_payload.get("perceptual_signals"), dict)
        else {}
    )
    human = perceptual.get("human_accept") if isinstance(perceptual.get("human_accept"), dict) else {}
    research = perceptual.get("research_metrics") if isinstance(perceptual.get("research_metrics"), dict) else {}
    timing = iteration_payload.get("timing") if isinstance(iteration_payload.get("timing"), dict) else {}
    iteration = int(iteration_payload.get("iteration", 0))
    return {
        "iter_id": f"iter_{iteration:04d}",
        "iteration": iteration,
        "kind": "auto_adjust",
        "selected_stage": iteration_payload.get("selected_stage"),
        "diff_score_before": iteration_payload.get("diff_score_before"),
        "fit_score_before": iteration_payload.get("fit_score_before"),
        "target_score": iteration_payload.get("target_score"),
        "stop_reason": decision.get("stop_reason"),
        "iteration_gain": decision.get("iteration_gain"),
        "changes_count": len(decision.get("changes") or []) if isinstance(decision.get("changes"), list) else 0,
        "applied_lmat": decision.get("applied_lmat"),
        "research_score": research.get("score"),
        "research_loss": research.get("loss"),
        "human_accept_score": human.get("score"),
        "perceptual_fit_score": perceptual.get("fit_score"),
        "weighted_mae": perceptual.get("weighted_mae"),
        "optimizer": decision.get("optimizer"),
        "semantic_action": decision.get("semantic_action"),
        "timing": {
            key: timing.get(key)
            for key in (
                "iteration_total_ms",
                "candidate_capture_ms",
                "analyze_multiview_ms",
                "strategy_propose_ms",
                "multiview_workers",
            )
            if key in timing
        },
        "is_snapshot": bool(is_snapshot),
        "can_open_detail": bool(is_snapshot),
        "is_best": bool(is_best),
    }


def _write_snapshot_index(auto_dir: Path, series: list[dict[str, Any]], snapshot_iterations: set[int]) -> None:
    by_iter = {
        int(item.get("iteration")): item
        for item in series
        if isinstance(item.get("iteration"), int)
    }
    snapshots = [
        {
            **by_iter.get(iteration, {"iteration": iteration, "iter_id": f"iter_{iteration:04d}"}),
            "is_snapshot": True,
            "can_open_detail": True,
        }
        for iteration in sorted(snapshot_iterations)
    ]
    _write_json(
        auto_dir / "snapshot_index.json",
        {
            "snapshots": snapshots,
            "snapshot_iterations": sorted(snapshot_iterations),
        },
    )


def _mark_series_snapshots(series: list[dict[str, Any]], snapshot_iterations: set[int]) -> None:
    for item in series:
        iteration = item.get("iteration")
        if isinstance(iteration, int) and iteration in snapshot_iterations:
            item["is_snapshot"] = True
            item["can_open_detail"] = True


def _prune_iteration_artifacts(
    auto_dir: Path,
    iterations: list[dict[str, Any]],
    *,
    current_iteration: int,
    snapshot_interval: int,
    keep_last_n: int,
    always_keep_best: bool,
    always_keep_first: bool,
    snapshot_iterations: set[int] | None = None,
    full_payloads: dict[int, dict[str, Any]] | None = None,
    final_cleanup: bool = False,
) -> None:
    if keep_last_n < 0:
        keep_last_n = 0
    protected: set[int] = set(range(max(0, current_iteration - keep_last_n + 1), current_iteration + 1))
    if always_keep_first:
        protected.add(0)
    if snapshot_interval > 0:
        protected.update(
            iteration
            for iteration in range(0, current_iteration + 1)
            if iteration % snapshot_interval == 0
        )
    if always_keep_best:
        best_iteration = _best_recorded_iteration(iterations)
        if best_iteration is not None:
            protected.add(best_iteration)
    if snapshot_iterations:
        protected.update(snapshot_iterations)
    if full_payloads:
        for iteration in list(protected):
            payload = full_payloads.get(iteration)
            if isinstance(payload, dict):
                protected.update(_referenced_iteration_numbers(payload))
    if not auto_dir.exists():
        return
    for entry in auto_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("iter_"):
            continue
        try:
            iteration = int(entry.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        if iteration in protected or iteration > current_iteration:
            continue
        if final_cleanup:
            shutil.rmtree(entry, ignore_errors=True)
            continue
        _delete_heavy_iteration_artifacts(entry)
        decision_path = entry / "decision.json"
        if decision_path.exists():
            decision_path.unlink()
        candidate_dir = entry / "candidate"
        if candidate_dir.exists():
            for name in ("params.json",):
                target = candidate_dir / name
                if target.exists():
                    target.unlink()
            for lmat in candidate_dir.glob("*.lmat"):
                lmat.unlink(missing_ok=True)


def _referenced_iteration_numbers(iteration_payload: dict[str, Any]) -> set[int]:
    refs: set[int] = set()
    stack: list[Any] = [iteration_payload.get("input_pair"), iteration_payload.get("input_pairs")]
    pattern = re.compile(r"iter_(\d{4,})")
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str):
            for match in pattern.finditer(value.replace("\\", "/")):
                try:
                    refs.add(int(match.group(1)))
                except ValueError:
                    continue
    return refs


def _best_recorded_iteration(iterations: list[dict[str, Any]]) -> int | None:
    best_iteration: int | None = None
    best_score = -math.inf
    for item in iterations:
        score = _number_or_default(item.get("fit_score_before"), -math.inf)
        iteration_value = item.get("iteration")
        if score > best_score and isinstance(iteration_value, int):
            best_score = score
            best_iteration = iteration_value
    return best_iteration


def _delete_heavy_iteration_artifacts(iteration_dir: Path) -> None:
    targets = [
        iteration_dir / "image_analysis",
        iteration_dir / "candidate" / "laya_multiview",
    ]
    for target in targets:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def _resolve_external_backup_dir(config: dict[str, Any], project_root: Path, output_dir: Path) -> Path:
    backup_dir_value = config.get("external_backup_dir")
    if backup_dir_value:
        return _resolve_path(project_root, str(backup_dir_value))
    return output_dir / "external_backups"


def _mean_finite(values: list[float], *, default: float) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return default
    return sum(finite) / len(finite)


def _number_or_default(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _run_laya_refresh_preflight(
    *,
    config: dict[str, Any],
    project_root: Path,
    output_dir: Path,
    laya_material_path: Path,
    laya_shader_params: list[Any],
    rerender_wait_ms: int,
    screen_capture_region: str,
    probe_param: str,
    focus_callback: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the magenta-probe refresh preflight before auto-adjust.

    When ``laya_editor_capture.enabled`` is on, probe with the same
    editor command/reimport path as the real loop, but only capture the
    front-facing 0-degree view. The full eight-view capture is reserved
    for actual scoring iterations.
    """

    screen_capture_cfg = config.get("screen_capture", {}) if isinstance(config.get("screen_capture"), dict) else {}
    editor_capture_cfg = config.get("laya_editor_capture") if isinstance(config.get("laya_editor_capture"), dict) else {}
    if not isinstance(config.get("laya_editor_capture"), dict):
        config["laya_editor_capture"] = editor_capture_cfg
    # Refresh preflight must use the Laya Editor script path. Do not fall
    # back to desktop-region screenshots, otherwise the probe validates a
    # different capture path than the automated material-fit loop.
    editor_capture_cfg["enabled"] = True
    # The certified refresh path is material reimport only. Reloading the
    # whole scene is slower and can disturb model transforms before capture.
    editor_capture_cfg["reload_scene_after_reimport"] = False
    capture_dir = _resolve_path(project_root, screen_capture_cfg.get("capture_dir", str(DEFAULT_CAPTURE_DIR)))
    state_file_value = screen_capture_cfg.get("state_file")
    state_file = _resolve_path(project_root, state_file_value) if state_file_value else capture_dir / ".capture_region.json"
    region_text = screen_capture_region or str(screen_capture_cfg.get("region", ""))
    explicit_region = parse_region(region_text) if region_text else None

    preflight_dir_value = config.get("project_preflight_dir")
    preflight_capture_dir = (
        _resolve_path(project_root, str(preflight_dir_value))
        if preflight_dir_value
        else output_dir / "auto_adjust" / "preflight_captures"
    )
    preflight_capture_dir.mkdir(parents=True, exist_ok=True)

    anchor = _build_capture_anchor(config)
    probe_cfg = config.get("laya_refresh_probe") if isinstance(config.get("laya_refresh_probe"), dict) else {}
    change_threshold = _coerce_probe_threshold(
        probe_cfg.get("mean_diff_change_threshold"),
        0.5,
    )
    restore_threshold = _coerce_probe_threshold(
        probe_cfg.get("mean_diff_restore_threshold"),
        2.5,
    )
    resolved_probe_param = resolve_probe_param(
        requested=probe_param,
        laya_material_path=laya_material_path,
        laya_shader_params=laya_shader_params,
    )

    def _capture(step: str) -> Path:
        try:
            result = trigger_editor_single_view_capture(
                config=config,
                project_root=project_root,
                output_dir=preflight_capture_dir,
                nonce_prefix=f"preflight-{step}",
                laya_material_path=laya_material_path,
                file_name=f"{step}.png",
            )
        except LayaEditorCaptureError as exc:
            raise RuntimeError(str(exc)) from exc
        screenshots = result.get("screenshots", []) if isinstance(result, dict) else []
        if not screenshots:
            raise RuntimeError(f"Laya editor selected-camera preflight produced no screenshot for {step}")
        return Path(str(screenshots[0]))

    probe_result = run_refresh_probe(
        laya_material_path=laya_material_path,
        laya_shader_params=laya_shader_params,
        capture=_capture,
        config=ProbeConfig(
            probe_param=resolved_probe_param,
            rerender_wait_ms=rerender_wait_ms,
            mean_diff_change_threshold=change_threshold,
            mean_diff_restore_threshold=restore_threshold,
        ),
        output_dir=preflight_capture_dir,
        focus=None,
    )
    payload = probe_result.to_dict()
    payload["capture_method"] = "laya_editor_selected_camera"
    payload["requested_probe_param"] = probe_param
    if payload.get("success"):
        cert = _build_refresh_session_cert(
            config=config,
            laya_material_path=laya_material_path,
            probe_payload=payload,
            preflight_dir=preflight_capture_dir,
        )
        _write_json(preflight_capture_dir / "refresh_session_cert.json", cert)
        payload["refresh_session_cert"] = str((preflight_capture_dir / "refresh_session_cert.json").resolve())
    return payload


def _build_refresh_session_cert(
    *,
    config: dict[str, Any],
    laya_material_path: Path,
    probe_payload: dict[str, Any],
    preflight_dir: Path,
) -> dict[str, Any]:
    import datetime as _dt

    editor_capture = config.get("laya_editor_capture") if isinstance(config.get("laya_editor_capture"), dict) else {}
    report_path = preflight_dir / "laya_editor_selected_camera_report.json"
    script_version = ""
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8-sig"))
            diagnostics = report.get("render_diagnostics") if isinstance(report, dict) else {}
            if isinstance(diagnostics, dict):
                script_version = str(diagnostics.get("script_version") or "")
        except (OSError, json.JSONDecodeError):
            script_version = ""
    refresh_assets = editor_capture.get("refresh_assets") if isinstance(editor_capture.get("refresh_assets"), list) else []
    return {
        "success": True,
        "cert_type": "laya_lmat_reimport_session",
        "verified_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "laya_project": str(editor_capture.get("laya_project") or ""),
        "command_path": str(editor_capture.get("command_path") or ""),
        "lmat_path": str(laya_material_path.resolve()),
        "refresh_assets": [str(item) for item in refresh_assets],
        "reload_scene_after_reimport": False,
        "reimport_only": True,
        "capture_method": probe_payload.get("capture_method"),
        "probe_param": probe_payload.get("probe_param"),
        "probe_value": probe_payload.get("probe_value"),
        "mean_diff_baseline_probe": probe_payload.get("mean_diff_baseline_probe"),
        "mean_diff_baseline_restored": probe_payload.get("mean_diff_baseline_restored"),
        "script_version": script_version,
    }


def _build_capture_anchor(config: dict[str, Any]) -> CaptureAnchor | None:
    """Construct a :class:`CaptureAnchor` from fit_config's
    ``laya_capture_anchor`` block. Returns ``None`` when the anchor is
    disabled or its width/height isn't populated yet (legacy projects).
    """
    raw = config.get("laya_capture_anchor")
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    width = int(raw.get("width", 0) or 0)
    height = int(raw.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return None
    return CaptureAnchor(
        enabled=True,
        offset_x=int(raw.get("offset_x", 0) or 0),
        offset_y=int(raw.get("offset_y", 0) or 0),
        width=width,
        height=height,
        process_pattern=str(raw.get("process_pattern", "LayaAirIDE")),
        title_pattern=str(raw.get("title_pattern", "")),
    )


def _coerce_probe_threshold(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


def _build_focus_callback(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> Callable[[str], dict[str, Any]] | None:
    """Construct a focus-Laya callback from CLI args and config.

    Layering order (CLI overrides config; both can override defaults):

    1. ``--laya-window-process`` / ``--laya-window-title`` CLI flags.
    2. ``laya_window`` block in the JSON config:
       ``{"process_pattern": "...", "title_pattern": "...", "settle_ms": 250}``.
    3. Default: ``process_pattern="LayaAirIDE"``, no title filter.

    Set process pattern to empty string ('') to disable focus
    entirely (returns ``None``).
    """
    cfg_block = config.get("laya_window", {}) if isinstance(config.get("laya_window"), dict) else {}
    process_pattern = (
        args.laya_window_process
        if args.laya_window_process is not None
        else str(cfg_block.get("process_pattern", "LayaAirIDE"))
    )
    title_pattern = (
        args.laya_window_title
        if args.laya_window_title is not None
        else str(cfg_block.get("title_pattern", ""))
    )
    settle_ms = int(cfg_block.get("settle_ms", 250))

    if not (process_pattern or title_pattern):
        return None

    target = FocusTarget(process_pattern=process_pattern, title_pattern=title_pattern)

    def _focus(step: str) -> dict[str, Any]:
        result = focus_laya_window(target, settle_ms=settle_ms).to_dict()
        result["step"] = step
        return result

    return _focus


def _override_cmaes_from_cli(args: argparse.Namespace, base: CmaesStrategyConfig) -> CmaesStrategyConfig:
    """Layer CLI flags on top of the config-file-derived CMA-ES config."""
    raw_mix = getattr(args, "cma_hint_bias_mix_ratio", None)
    if raw_mix is None:
        mix_ratio = base.hint_bias_mix_ratio
    else:
        try:
            mix_ratio = float(raw_mix)
        except (TypeError, ValueError):
            mix_ratio = base.hint_bias_mix_ratio
        if not math.isfinite(mix_ratio) or mix_ratio < 0.0:
            mix_ratio = 0.0
        if mix_ratio > 1.0:
            mix_ratio = 1.0
    return CmaesStrategyConfig(
        mode=base.mode,
        warm_start_iters=int(args.cma_warm_start_iters) if args.cma_warm_start_iters is not None else base.warm_start_iters,
        population_size=int(args.cma_population_size) if args.cma_population_size is not None else base.population_size,
        sigma=float(args.cma_sigma) if args.cma_sigma is not None else base.sigma,
        seed=int(args.cma_seed) if args.cma_seed is not None else base.seed,
        hint_bias_mix_ratio=mix_ratio,
    )


def _wait_for_visual_refresh(
    *,
    previous_candidate_path: str | None,
    max_wait_ms: int,
    interval_ms: int,
    min_wait_ms: int,
    diff_threshold: float,
    capture_dir: Path,
    region: Any,
    reuse_last: bool,
    state_file: Path,
    anchor: CaptureAnchor | None,
    focus_callback: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Poll the Laya viewport until it visibly changes or timeout.

    This is a conservative speed-up over the old fixed sleep. It does
    **not** assume the first changed frame is perfect; it simply avoids
    burning the full 1.5s when the viewport has already refreshed. If
    no change is detected, the caller sleeps out the remaining budget
    and uses the normal final capture path.
    """

    started = time.perf_counter()
    max_wait = max(0, int(max_wait_ms)) / 1000.0
    interval = max(50, int(interval_ms)) / 1000.0
    min_wait = max(0, int(min_wait_ms)) / 1000.0
    payload: dict[str, Any] = {
        "enabled": True,
        "changed": False,
        "elapsed_ms": 0,
        "samples": [],
        "reason": "",
    }
    previous = Path(previous_candidate_path) if previous_candidate_path else None
    if previous is None or not previous.exists():
        time.sleep(max_wait)
        payload.update({"elapsed_ms": int(max_wait * 1000), "reason": "missing previous candidate; fixed wait used"})
        return payload

    probe_path = capture_dir / "_dynamic_wait_probe.png"
    sample_idx = 0
    while True:
        elapsed = time.perf_counter() - started
        if elapsed < min_wait:
            time.sleep(min(interval, min_wait - elapsed))
            continue
        if elapsed >= max_wait:
            payload["reason"] = "timeout_without_visible_change"
            break
        if focus_callback is not None:
            focus_callback(f"dynamic_wait_probe_{sample_idx:02d}")
        result = capture_laya_region(
            region=region,
            reuse_last=reuse_last,
            capture_dir=capture_dir,
            state_file=state_file,
            prefix=DEFAULT_PREFIX,
            dry_run=False,
            anchor=anchor,
            output_path=probe_path,
        )
        diff = _mean_image_diff(previous, Path(result["output_path"]))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        payload["samples"].append({"elapsed_ms": elapsed_ms, "diff": diff})
        if diff >= diff_threshold:
            payload.update(
                {
                    "changed": True,
                    "elapsed_ms": elapsed_ms,
                    "reason": "visible_change_detected",
                    "diff_threshold": diff_threshold,
                }
            )
            return payload
        sample_idx += 1
        time.sleep(interval)
    payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    payload["diff_threshold"] = diff_threshold
    return payload


def _mean_image_diff(a_path: Path, b_path: Path) -> float:
    try:
        from PIL import Image
    except ImportError:
        return 0.0
    try:
        with Image.open(a_path).convert("RGB") as a_img, Image.open(b_path).convert("RGB") as b_img:
            if a_img.size != b_img.size:
                b_img = b_img.resize(a_img.size)
            # Downsample aggressively; we only need a refresh detector,
            # not a material score. Return mean channel difference in
            # 0..255 units so thresholds are easy to reason about.
            a_small = a_img.resize((64, 64))
            b_small = b_img.resize((64, 64))
            a_px = list(a_small.getdata())
            b_px = list(b_small.getdata())
            total = 0.0
            for a, b in zip(a_px, b_px):
                total += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
            return total / max(1, len(a_px) * 3)
    except Exception:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
