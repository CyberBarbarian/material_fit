from __future__ import annotations

import argparse
import copy
import json
import math
import pickle
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .auto_adjust.scoring import extract_perceptual_signals as _extract_perceptual_signals
from .auto_adjust.stability import (
    normalize_stability_score_policy as _normalize_stability_score_policy,
    select_stability_policy_value as _select_stability_policy_value,
    summarize_fresh_oracle_records as _summarize_fresh_oracle_records,
    summarize_stability_samples as _summarize_stability_samples,
)
from .auto_adjust.history import (
    load_elite_archive_warm_start_history as _load_elite_archive_warm_start_history,
    load_warm_start_history as _load_warm_start_history,
)
from .auto_adjust.image_pairs import ImagePairCollectionError, collect_image_pairs as _collect_image_pairs
from .fit_artifacts import (
    _build_batch_execution_summary,
    _build_candidate_archive_evidence_summary,
    _build_initial_design_evidence_summary,
    _best_recorded_iteration,
    _build_optimizer_candidate_archive,
    _build_optimizer_evidence_summary,
    _iteration_series_entry,
    _mark_series_snapshots,
    _optional_int_like,
    _prune_iteration_artifacts,
    _record_iteration_outputs,
    _write_snapshot_index,
)
from .fit_cli import parse_fit_args
from .laya import lmat_io
from .laya.refresh_probe import ProbeConfig, resolve_probe_param, run_refresh_probe
from .laya.render_driver import RenderDriver
from .laya_capture.editor_bridge import LayaEditorCaptureError, trigger_editor_multiview_capture, trigger_editor_single_view_capture
from .laya.shader_parser import parse_laya_shader, shader_info_to_dict
from .laya.window_focus import FocusTarget, focus_laya_window
from .optimizer.adjustment_algorithm import (
    AdjustmentState,
    build_adjustment_policies,
    load_adjustment_state,
    policies_to_fit_stages,
    save_adjustment_state,
    should_abort_global,
)
from .optimizer.parameter_search import (
    build_initial_params,
    build_param_policy_audit,
    build_stage_plan,
    build_zero_searchable_initial_params,
    generate_probe_candidates,
)
from .optimizer.material_discrete_space import attach_discrete_candidate
from .optimizer.pattern16_strategy import pattern16_search_param_names
from .optimizer.structured_fish_space import (
    FishSearchCoordinate,
    structured_fish_coordinates,
    structured_fish_search_param_names,
)
from .optimizer.semantic_graph import build_shader_effect_graph, graph_from_dict, graph_to_dict
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


_OPTIMIZER_PRESETS = {"manual", "cma_mature_default", "subspace_cma_mature_default"}
_CMA_MATURE_DEFAULT_PRESET: dict[str, Any] = {
    "optimizer": "cma_warm",
    "cma_es": {
        "warm_start_iters": 12,
        "warm_start_source": "elite_archive_first",
        "hint_bias_mix_ratio": 0.30,
        "stagnation_patience": 64,
        "stagnation_min_delta": 0.001,
        "stagnation_min_evaluations": 64,
        "stagnation_max_restarts": 8,
        "stagnation_stop_after_restarts": False,
        "restart_center_mode": "alternate",
        "restart_population_multiplier": 2.0,
        "restart_population_schedule": "bipop",
        "restart_max_population_size": None,
        "initial_design_samples": 33,
        "initial_design_method": "local_coordinate_probe",
        "initial_design_include_current": True,
        "initial_design_local_step_ratio": 0.03,
    },
    "analysis_performance": {
        "evaluation_batch_size": 8,
        "evaluation_workers": 4,
        "evaluation_parallel_safe": False,
        "full_rerank_top_k": 1,
        "best_full_validation": True,
        "target_full_validation": True,
        "stability_validation_repeats": 2,
        "stability_validation_restart_renderer": True,
        "stability_score_drift_threshold": 0.005,
        "stability_foreground_abs_threshold": 128.0,
        "stability_foreground_ratio_threshold": 0.005,
        "research_metrics_profile": "tiered",
        "fast_score_only": True,
    },
}
_SUBSPACE_CMA_MATURE_DEFAULT_PRESET: dict[str, Any] = {
    "optimizer": "subspace_cma_es",
    "cma_es": {
        "sigma": 0.22,
    },
    "analysis_performance": {
        "evaluation_batch_size": 1,
        "evaluation_workers": 1,
        "evaluation_parallel_safe": False,
        "full_rerank_top_k": 0,
        "best_full_validation": True,
        "target_full_validation": True,
        "stability_validation_repeats": 2,
        "stability_validation_restart_renderer": True,
        "stability_score_drift_threshold": 0.005,
        "stability_foreground_abs_threshold": 128.0,
        "stability_foreground_ratio_threshold": 0.005,
        "research_metrics_profile": "tiered",
        "fast_score_only": True,
    },
}


def main() -> int:
    args = parse_fit_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    project_root = config_path.resolve().parents[2]
    config = _load_external_config_fragments(config, project_root)
    config = _apply_optimizer_preset_override(config, args.optimizer_preset)
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
    initial_params_override_path = _initial_params_override_path(config, project_root)
    initial_params_override: Any = None
    if initial_params_override_path is not None:
        initial_params_override = json.loads(initial_params_override_path.read_text(encoding="utf-8"))
    material_defines = lmat_io.extract_defines(laya_material)
    policy_graph = _semantic_graph_for_initial_policy(
        config,
        laya_shader.params,
        initial_params,
        material_defines,
    )
    if not isinstance(config.get("effect_graph"), dict):
        config["effect_graph"] = policy_graph
    configured_optimizer = _configured_optimizer_name(args.optimizer or config.get("optimizer", "heuristic"))
    search_param_names = _configured_search_param_names(
        config,
        configured_optimizer,
        initial_params,
        laya_shader.params,
        policy_graph,
    )
    initial_params_mode = _initial_params_mode(config)
    if initial_params_mode == "zero_searchable":
        initial_params = build_zero_searchable_initial_params(
            initial_params,
            laya_shader.params,
            search_param_names=search_param_names,
        )
    if initial_params_override_path is not None:
        initial_params = _apply_initial_params_override(
            initial_params,
            initial_params_override,
            source=str(initial_params_override_path),
        )
    param_policy_audit = build_param_policy_audit(
        initial_params,
        laya_shader.params,
        search_param_names=search_param_names,
        allow_scene_lighting_search=configured_optimizer in {
            "structured_fish",
            "material_stage1_hybrid",
            "material_discrete_joint",
        },
    )
    param_policy_audit["initial_params_mode"] = initial_params_mode
    if initial_params_override_path is not None:
        param_policy_audit["initial_params_override_path"] = str(initial_params_override_path)
    if configured_optimizer == "material_discrete_joint":
        discrete_cfg = config.get("material_discrete_joint")
        start_candidate = (
            discrete_cfg.get("start_candidate")
            if isinstance(discrete_cfg, dict)
            else None
        )
        if not isinstance(start_candidate, dict):
            raise ValueError("material_discrete_joint config is missing start_candidate")
        initial_params = attach_discrete_candidate(initial_params, start_candidate)
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
    _write_json(output_dir / "optimizer_param_policy.json", param_policy_audit)
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
        # so probe and capture can otherwise freeze on a stale frame.
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

    driver.close()
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
    print(
        "Param policy: "
        f"{param_policy_audit['searchable_param_count']} searchable, "
        f"{param_policy_audit['locked_param_count']} locked "
        f"(initial_params_mode={initial_params_mode})"
    )
    print(f"Probe candidates: {len(emitted)}")
    if adjustment_result:
        print(f"Auto-adjust iterations: {len(adjustment_result.get('iterations', []))}")
        print(f"Auto-adjust best score: {adjustment_result.get('best_score')}")
        print(f"Auto-adjust best fit score: {adjustment_result.get('best_fit_score')}")
    return 0


def _initial_params_mode(config: dict[str, Any]) -> str:
    raw = None
    nested = config.get("initial_params")
    if isinstance(nested, dict):
        raw = nested.get("mode")
    if raw is None:
        raw = config.get("initial_params_mode")
    mode = str(raw or "material").strip().lower()
    aliases = {
        "baseline": "material",
        "current": "material",
        "source": "material",
        "zero": "zero_searchable",
        "zero_search": "zero_searchable",
        "zero_searchable_params": "zero_searchable",
    }
    return aliases.get(mode, mode) if aliases.get(mode, mode) in {"material", "zero_searchable"} else "material"


def _initial_params_override_path(config: dict[str, Any], project_root: Path) -> Path | None:
    raw = None
    nested = config.get("initial_params")
    if isinstance(nested, dict):
        raw = nested.get("override_path")
    if raw is None:
        raw = config.get("initial_params_override_path")
    if raw in (None, ""):
        return None
    path = _resolve_path(project_root, str(raw))
    if not path.exists():
        raise FileNotFoundError(f"initial_params_override_path does not exist: {path}")
    return path


def _apply_initial_params_override(
    initial_params: dict[str, Any],
    override_params: Any,
    *,
    source: str,
) -> dict[str, Any]:
    if not isinstance(override_params, dict):
        raise ValueError(f"initial params override must be a JSON object: {source}")

    unknown = sorted(str(name) for name in override_params if name not in initial_params)
    if unknown:
        preview = ", ".join(unknown[:8])
        raise ValueError(f"initial params override contains unknown keys from {source}: {preview}")

    merged = dict(initial_params)
    for name, value in override_params.items():
        base_value = initial_params[name]
        if not _initial_param_override_shape_matches(base_value, value):
            raise ValueError(
                f"initial params override shape mismatch for {name!r} from {source}: "
                f"{type(base_value).__name__} vs {type(value).__name__}"
            )
        merged[str(name)] = value
    return merged


def _initial_param_override_shape_matches(base_value: Any, override_value: Any) -> bool:
    if isinstance(base_value, bool):
        return isinstance(override_value, bool)
    if isinstance(base_value, (int, float)) and not isinstance(base_value, bool):
        return isinstance(override_value, (int, float)) and not isinstance(override_value, bool)
    if isinstance(base_value, str):
        return isinstance(override_value, str)
    if isinstance(base_value, list):
        return isinstance(override_value, list) and len(base_value) == len(override_value)
    return type(base_value) is type(override_value)


def _configured_optimizer_name(value: Any) -> str:
    name = str(value or "heuristic").strip().lower()
    return name or "heuristic"


def _configured_search_param_names(
    config: dict[str, Any],
    optimizer: str,
    initial_params: dict[str, Any],
    shader_params: list[Any],
    policy_graph: dict[str, Any],
) -> list[str]:
    raw_names = config.get("search_param_names")
    if isinstance(raw_names, list):
        names = [str(name) for name in raw_names if isinstance(name, str) and name in initial_params]
        if names:
            return names
    raw_space = str(config.get("search_param_space") or "").strip().lower()
    if optimizer in {"pattern16", "cross_engine_hybrid"} or raw_space in {"pattern16", "fish_pattern16", "fish16"}:
        return pattern16_search_param_names(initial_params, shader_params)
    if optimizer == "structured_fish" or raw_space in {"structured_fish", "structured_fish_v1"}:
        return structured_fish_search_param_names(initial_params, shader_params)
    return _active_search_param_names(policy_graph, initial_params)


def _proposal_quantization_coordinates(
    config: dict[str, Any],
    *,
    optimizer: str,
    initial_params: dict[str, Any],
    shader_params: list[Any],
    policy_graph: dict[str, Any],
) -> tuple[float, list[FishSearchCoordinate]]:
    raw_step = config.get("proposal_quantization_normalized_step", 0.0)
    if isinstance(raw_step, bool):
        raise ValueError("proposal_quantization_normalized_step must be numeric")
    step = float(raw_step)
    if not math.isfinite(step) or step < 0.0 or step > 0.01:
        raise ValueError(
            "proposal_quantization_normalized_step must be finite and in [0, 0.01]"
        )
    if step == 0.0:
        return 0.0, []
    search_param_names = _configured_search_param_names(
        config,
        optimizer,
        initial_params,
        shader_params,
        policy_graph,
    )
    coordinates = structured_fish_coordinates(
        initial_params,
        shader_params=shader_params,
        search_param_names=search_param_names,
    )
    if not coordinates:
        raise ValueError("proposal quantization has no searchable continuous coordinates")
    return step, coordinates


def _quantize_searchable_proposal(
    params: dict[str, Any],
    *,
    coordinates: list[FishSearchCoordinate],
    normalized_step: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project searchable coordinates onto a deterministic normalized grid."""

    if normalized_step <= 0.0 or not coordinates:
        return copy.deepcopy(params), {
            "enabled": False,
            "normalized_step": 0.0,
            "coordinate_count": 0,
            "changed_coordinate_count": 0,
            "maximum_absolute_delta": 0.0,
        }
    result = copy.deepcopy(params)
    changed_count = 0
    maximum_delta = 0.0
    for coordinate in coordinates:
        span = float(coordinate.high - coordinate.low)
        if span <= 0.0:
            continue
        value = coordinate.read(result)
        normalized = min(max((value - coordinate.low) / span, 0.0), 1.0)
        snapped_normalized = min(
            max(round(normalized / normalized_step) * normalized_step, 0.0),
            1.0,
        )
        snapped = coordinate.low + snapped_normalized * span
        delta = abs(snapped - value)
        if delta > 0.0:
            changed_count += 1
            maximum_delta = max(maximum_delta, delta)
        if coordinate.component is None:
            result[coordinate.param_name] = snapped
        else:
            vector = list(result[coordinate.param_name])
            vector[coordinate.component] = snapped
            result[coordinate.param_name] = vector
    return result, {
        "enabled": True,
        "normalized_step": normalized_step,
        "coordinate_count": len(coordinates),
        "changed_coordinate_count": changed_count,
        "maximum_absolute_delta": maximum_delta,
    }


def _proposal_quantization_step_for_decision(
    decision: dict[str, Any],
    default_step: float,
) -> float:
    raw_step = decision.get("proposal_quantization_normalized_step", default_step)
    if isinstance(raw_step, bool):
        raise ValueError("decision proposal quantization step must be numeric")
    step = float(raw_step)
    if not math.isfinite(step) or step < 0.0 or step > 0.01:
        raise ValueError(
            "decision proposal quantization step must be finite and in [0, 0.01]"
        )
    return step


def _semantic_graph_for_initial_policy(
    config: dict[str, Any],
    shader_params: list[Any],
    initial_params: dict[str, Any],
    material_defines: list[str],
) -> dict[str, Any]:
    configured = config.get("effect_graph")
    if isinstance(configured, dict):
        return configured
    return graph_to_dict(
        build_shader_effect_graph(
            shader_params,
            material_params=initial_params,
            material_defines=material_defines,
        )
    )


def _active_search_param_names(
    semantic_graph: dict[str, Any],
    params: dict[str, Any],
) -> list[str]:
    graph = graph_from_dict(semantic_graph)
    if graph is None:
        return []
    return [name for name in graph.active_search_params() if name in params]


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


def _oracle_probe_params(raw_probe: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_probe.get("params"), dict):
        return copy.deepcopy(raw_probe["params"])
    if isinstance(raw_probe.get("param_values"), dict):
        return copy.deepcopy(raw_probe["param_values"])
    return {
        str(key): copy.deepcopy(value)
        for key, value in raw_probe.items()
        if key not in {"label", "name", "weight"}
    }


def _oracle_probe_labels(probe_candidates: list[dict[str, Any]]) -> list[str]:
    return [
        str(probe.get("label") or probe.get("name") or f"probe_{index:02d}")
        for index, probe in enumerate(probe_candidates)
    ]


def _browser_score_foreground_signature(
    browser_score: Any,
    *,
    bucket_size: float = 128.0,
) -> list[dict[str, Any]] | None:
    if not isinstance(browser_score, dict):
        return None
    raw_views = browser_score.get("views")
    if not isinstance(raw_views, list):
        return None
    signature: list[dict[str, Any]] = []
    for view in raw_views:
        if not isinstance(view, dict):
            continue
        view_id = str(view.get("view_id") or "")
        if not view_id:
            continue
        foreground_sum = _optional_float_value(view.get("foreground_weight_sum"))
        if foreground_sum is None:
            continue
        signature.append(
            {
                "view_id": view_id,
                "foreground_weight_sum_bucket": int(round(float(foreground_sum) / bucket_size) * bucket_size),
            }
        )
    return sorted(signature, key=lambda item: str(item["view_id"])) or None


def _oracle_stabilization_foreground_signature(
    oracle_stabilization: dict[str, Any] | None,
    *,
    bucket_size: float = 128.0,
) -> list[dict[str, Any]] | None:
    if not isinstance(oracle_stabilization, dict):
        return None
    raw_records = oracle_stabilization.get("records")
    if not isinstance(raw_records, list):
        return None
    selected_attempt = oracle_stabilization.get("selected_attempt")
    selected_records = [
        record
        for record in raw_records
        if isinstance(record, dict) and record.get("attempt") == selected_attempt
    ]
    fallback_records = [
        record
        for record in raw_records
        if isinstance(record, dict) and str(record.get("status") or "").lower() == "ok"
    ]
    for record in selected_records + fallback_records:
        signature = _browser_score_foreground_signature(record.get("browser_score"), bucket_size=bucket_size)
        if signature:
            return signature
        probe_records = record.get("probe_records")
        if not isinstance(probe_records, list):
            continue
        for probe_record in probe_records:
            if not isinstance(probe_record, dict):
                continue
            signature = _browser_score_foreground_signature(
                probe_record.get("browser_score"),
                bucket_size=bucket_size,
            )
            if signature:
                return signature
    return None


def _prepare_render_oracle(
    *,
    config: dict[str, Any],
    auto_dir: Path,
    driver: RenderDriver,
    params: dict[str, Any],
    resume_iteration: int = 0,
) -> dict[str, Any] | None:
    capture_config = config.get("laya_capture") if isinstance(config.get("laya_capture"), dict) else {}
    raw_cfg = capture_config.get("oracle_stabilization")
    if raw_cfg is None:
        raw_cfg = config.get("oracle_stabilization")
    if not isinstance(raw_cfg, dict) or not raw_cfg.get("enabled"):
        return None

    attempts = _coerce_positive_int(raw_cfg.get("attempts"), 1)
    min_fit_score = _optional_float_value(raw_cfg.get("min_fit_score"))
    iteration = int(raw_cfg.get("iteration", -1000) or -1000)
    output_subdir = str(raw_cfg.get("output_subdir") or "oracle_stabilization")
    selection_policy = str(raw_cfg.get("selection_policy") or "best")
    fail_on_error = bool(raw_cfg.get("fail_on_error", False))
    selection_params = copy.deepcopy(params)
    params_source = "current_params"
    probe_candidates: list[dict[str, Any]] | None = None
    raw_portfolio = raw_cfg.get("probe_portfolio")
    if raw_portfolio is None:
        raw_portfolio = raw_cfg.get("probe_candidates")
    if isinstance(raw_portfolio, list):
        probe_candidates = [copy.deepcopy(probe) for probe in raw_portfolio if isinstance(probe, dict)]
        probe_candidates = [probe for probe in probe_candidates if _oracle_probe_params(probe)]
        if probe_candidates:
            selection_params = _oracle_probe_params(probe_candidates[0])
            params_source = "probe_portfolio"
        else:
            probe_candidates = None

    probe_params = raw_cfg.get("probe_params")
    if probe_params is None:
        probe_params = raw_cfg.get("params")
    if probe_candidates is None and isinstance(probe_params, dict):
        selection_params = copy.deepcopy(probe_params)
        params_source = "probe_params"
    elif probe_candidates is None and isinstance(raw_cfg.get("param_overrides"), dict):
        selection_params.update(copy.deepcopy(raw_cfg["param_overrides"]))
        params_source = "param_overrides"

    if resume_iteration > 0:
        summary = {
            "status": "skipped",
            "reason": "resume_after_started",
            "enabled": True,
            "attempts_requested": attempts,
            "resume_iteration": resume_iteration,
        }
        _write_json(auto_dir / "oracle_stabilization.json", summary)
        return summary

    selector = getattr(driver, "select_persistent_oracle", None)
    if not callable(selector):
        summary = {
            "status": "skipped",
            "reason": "driver_does_not_support_oracle_selection",
            "enabled": True,
            "attempts_requested": attempts,
        }
        _write_json(auto_dir / "oracle_stabilization.json", summary)
        return summary

    try:
        selector_kwargs: dict[str, Any] = {
            "iteration": iteration,
            "params": selection_params,
            "attempts": attempts,
            "min_fit_score": min_fit_score,
            "output_subdir": output_subdir,
            "selection_policy": selection_policy,
        }
        if probe_candidates is not None:
            selector_kwargs["probe_candidates"] = probe_candidates
        summary = selector(**selector_kwargs)
    except Exception as exc:  # noqa: BLE001
        summary = {
            "status": "failed",
            "reason": "oracle_selection_exception",
            "error": str(exc),
            "enabled": True,
            "attempts_requested": attempts,
        }
        _write_json(auto_dir / "oracle_stabilization.json", summary)
        if fail_on_error:
            raise
        return summary

    if not isinstance(summary, dict):
        summary = {"status": "failed", "reason": "selector_returned_non_dict"}
    config_summary = {
        "attempts": attempts,
        "min_fit_score": min_fit_score,
        "iteration": iteration,
        "output_subdir": output_subdir,
        "selection_policy": selection_policy,
        "params_source": params_source,
        "probe_param_count": len(selection_params),
        "probe_candidate_count": len(probe_candidates) if probe_candidates is not None else 1,
    }
    if probe_candidates is not None:
        config_summary["probe_labels"] = _oracle_probe_labels(probe_candidates)

    summary = {
        **copy.deepcopy(summary),
        "enabled": True,
        "config": config_summary,
    }
    _write_json(auto_dir / "oracle_stabilization.json", summary)
    if fail_on_error and summary.get("status") == "failed":
        raise RuntimeError(f"oracle stabilization failed: {summary.get('reason')}")
    return summary


def _resolve_score_ceiling(
    config: dict[str, Any],
    *,
    target_score: float,
    oracle_stabilization: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    raw_cfg = config.get("score_ceiling")
    if raw_cfg is None:
        raw_cfg = config.get("target_score_ceiling")
    if not isinstance(raw_cfg, dict) or not raw_cfg.get("enabled"):
        return None

    target_self_score = _number_or_default(
        raw_cfg.get("target_self_score", raw_cfg.get("self_score", raw_cfg.get("ceiling_score"))),
        math.nan,
    )
    if not math.isfinite(target_self_score):
        return None
    configured_target_self_score = float(target_self_score)
    calibrated_from_oracle = False
    if bool(raw_cfg.get("calibrate_from_oracle_stabilization")) and isinstance(oracle_stabilization, dict):
        oracle_self_score = _number_or_default(oracle_stabilization.get("selected_fit_score"), math.nan)
        if math.isfinite(oracle_self_score):
            target_self_score = float(oracle_self_score)
            calibrated_from_oracle = True
    tolerance = _number_or_default(raw_cfg.get("tolerance", raw_cfg.get("margin", 0.0)), 0.0)
    if not math.isfinite(tolerance) or tolerance < 0:
        tolerance = 0.0
    raw_target = float(target_score)
    active = target_self_score < raw_target
    effective_target = raw_target
    if active:
        effective_target = max(0.0, min(raw_target, target_self_score - tolerance))
    ceiling = {
        "enabled": True,
        "target_self_score": float(target_self_score),
        "tolerance": float(tolerance),
        "effective_target_score": float(effective_target),
        "raw_target_score": raw_target,
        "source": (
            f"{str(raw_cfg.get('source') or 'configured_score_ceiling')}+oracle_stabilization"
            if calibrated_from_oracle
            else str(raw_cfg.get("source") or "configured_score_ceiling")
        ),
        "active": bool(active),
    }
    if calibrated_from_oracle:
        ceiling["calibrated_from_oracle_stabilization"] = True
        ceiling["configured_target_self_score"] = configured_target_self_score
    return ceiling


def _effective_target_score(target_score: float, score_ceiling: dict[str, Any] | None) -> float:
    if isinstance(score_ceiling, dict):
        candidate = _number_or_default(score_ceiling.get("effective_target_score"), math.nan)
        if math.isfinite(candidate):
            return float(candidate)
    return float(target_score)


def _target_stop_reason(
    fit_score: float,
    *,
    target_score: float,
    score_ceiling: dict[str, Any] | None,
) -> str | None:
    if fit_score >= float(target_score):
        return "target_reached"
    if isinstance(score_ceiling, dict) and bool(score_ceiling.get("active")):
        effective = _effective_target_score(target_score, score_ceiling)
        if fit_score >= effective:
            return "score_ceiling_reached"
    return None


def _browser_score_context_render_enabled(config: dict[str, Any]) -> bool:
    raw_cfg = config.get("browser_score_context_render")
    if raw_cfg is None:
        raw_cfg = config.get("initial_context_render")
    if isinstance(raw_cfg, dict):
        return bool(raw_cfg.get("enabled", False))
    return bool(raw_cfg)


def _context_render_iteration(iteration: int) -> int:
    return -1 - max(0, int(iteration))


def _load_iteration_series(auto_dir: Path) -> list[dict[str, Any]]:
    jsonl_path = auto_dir / "iteration_series.jsonl"
    if jsonl_path.exists():
        rows: list[dict[str, Any]] = []
        try:
            for line in jsonl_path.read_text(encoding="utf-8-sig").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(dict(item))
        except (OSError, json.JSONDecodeError):
            rows = []
        if rows:
            return rows
    series_path = auto_dir / "iteration_series.json"
    if not series_path.exists():
        return []
    try:
        payload = json.loads(series_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _optimizer_preset_from_config(config: dict[str, Any]) -> str:
    preset = str(config.get("optimizer_preset") or "manual").strip().lower()
    return preset or "manual"


def _apply_optimizer_preset_override(config: dict[str, Any], preset: str | None) -> dict[str, Any]:
    normalized = str(preset or "").strip().lower()
    if not normalized:
        return config
    if normalized not in _OPTIMIZER_PRESETS:
        normalized = "manual"
    if normalized == "manual":
        updated = copy.deepcopy(config)
        updated["optimizer_preset"] = "manual"
        return updated

    updated = copy.deepcopy(config)
    updated["optimizer_preset"] = normalized
    if normalized == "cma_mature_default":
        updated["optimizer"] = str(_CMA_MATURE_DEFAULT_PRESET["optimizer"])
        for section_name in ("cma_es", "analysis_performance"):
            preset_section = _CMA_MATURE_DEFAULT_PRESET.get(section_name)
            if not isinstance(preset_section, dict):
                continue
            existing = updated.get(section_name) if isinstance(updated.get(section_name), dict) else {}
            updated[section_name] = {**existing, **preset_section}
    elif normalized == "subspace_cma_mature_default":
        updated["optimizer"] = str(_SUBSPACE_CMA_MATURE_DEFAULT_PRESET["optimizer"])
        for section_name in ("cma_es", "analysis_performance"):
            preset_section = _SUBSPACE_CMA_MATURE_DEFAULT_PRESET.get(section_name)
            if not isinstance(preset_section, dict):
                continue
            existing = updated.get(section_name) if isinstance(updated.get(section_name), dict) else {}
            updated[section_name] = {**existing, **preset_section}
    return updated


def _cold_start_prior_anchors_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    section = config.get("cold_start_hybrid")
    if not isinstance(section, dict):
        return []
    raw_anchors = section.get("prior_anchors")
    if raw_anchors is None:
        raw_anchors = section.get("prior_anchor_portfolio")
    if isinstance(raw_anchors, dict):
        anchor_items = [raw_anchors]
    elif isinstance(raw_anchors, list):
        anchor_items = raw_anchors
    else:
        return []
    return [copy.deepcopy(anchor) for anchor in anchor_items if isinstance(anchor, dict)]


def _candidate_evaluation_cache_key(
    params: dict[str, Any],
    *,
    fit_score_mode: str,
    research_metrics_profile: str,
    perceptual_optional_enabled: bool,
    diff_visual_enabled: bool,
    fast_score_only_enabled: bool = False,
) -> str:
    payload = {
        "params": params,
        "fit_score_mode": fit_score_mode,
        "research_metrics_profile": research_metrics_profile,
        "perceptual_optional_enabled": bool(perceptual_optional_enabled),
        "diff_visual_enabled": bool(diff_visual_enabled),
        "fast_score_only_enabled": bool(fast_score_only_enabled),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_optimizer_warm_start_history(
    auto_dir: Path,
    *,
    limit: int,
    source: str = "elite_archive_first",
) -> tuple[list[tuple[dict[str, Any], float]], dict[str, Any]]:
    normalized_limit = max(int(limit), 0)
    normalized_source = _normalize_warm_start_source(source)
    sources: dict[str, Any] = {
        "limit": normalized_limit,
        "source": normalized_source,
        "elite_archive": 0,
        "iteration_history": 0,
        "total": 0,
    }
    if normalized_limit <= 0:
        return [], sources

    archive_history = (
        _load_elite_archive_warm_start_history(auto_dir, limit=normalized_limit)
        if normalized_source in {"elite_archive_first", "elite_archive_only"}
        else []
    )
    iteration_history = (
        _load_warm_start_history(auto_dir, limit=normalized_limit)
        if normalized_source in {"elite_archive_first", "iteration_history"}
        else []
    )
    out: list[tuple[dict[str, Any], float]] = []
    seen: set[str] = set()

    for source_name, history in (
        ("elite_archive", archive_history),
        ("iteration_history", iteration_history),
    ):
        for params, fit_score in history:
            key = _warm_start_params_key(params)
            if key in seen:
                continue
            seen.add(key)
            out.append((dict(params), float(fit_score)))
            sources[source_name] += 1
            if len(out) >= normalized_limit:
                sources["total"] = len(out)
                return out, sources

    sources["total"] = len(out)
    return out, sources


def _normalize_warm_start_source(value: Any) -> str:
    source = str(value or "elite_archive_first").strip().lower()
    aliases = {
        "archive": "elite_archive_first",
        "archive_first": "elite_archive_first",
        "elite_archive": "elite_archive_first",
        "combined": "elite_archive_first",
        "archive_only": "elite_archive_only",
        "elite_only": "elite_archive_only",
        "history": "iteration_history",
        "iter_history": "iteration_history",
        "iteration": "iteration_history",
        "off": "none",
        "disabled": "none",
        "false": "none",
    }
    source = aliases.get(source, source)
    return source if source in {"elite_archive_first", "elite_archive_only", "iteration_history", "none"} else "elite_archive_first"


def _warm_start_params_key(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _extract_browser_score_payload(render_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(render_result, dict):
        return None
    candidates = []
    persistent_result = render_result.get("persistent_result")
    if isinstance(persistent_result, dict):
        candidates.append(persistent_result.get("browser_score"))
    candidates.append(render_result.get("browser_score"))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("fit_score") is None and candidate.get("score") is None:
            continue
        return copy.deepcopy(candidate)
    return None


def _browser_score_analysis_payload(
    render_result: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    browser_score = _extract_browser_score_payload(render_result)
    if browser_score is None:
        raise ValueError("render_result does not contain a browser_score payload")

    foreground_score = _reference_foreground_browser_score(render_result, config=config)
    if foreground_score is not None:
        browser_score["raw_browser_score"] = copy.deepcopy(browser_score)
        browser_score["metric"] = foreground_score["metric"]
        browser_score["fit_score"] = foreground_score["fit_score"]
        browser_score["score"] = foreground_score["fit_score"]
        browser_score["diff_score"] = foreground_score["diff_score"]
        browser_score["views"] = foreground_score["views"]
        browser_score["summary"] = foreground_score["summary"]

    fit_score = _number_or_default(browser_score.get("fit_score"), math.nan)
    if not math.isfinite(fit_score):
        fit_score = _number_or_default(browser_score.get("score"), -math.inf)
        if fit_score > 1.0:
            fit_score /= 100.0
    diff_score = _number_or_default(
        browser_score.get("diff_score"),
        1.0 - fit_score if math.isfinite(fit_score) else math.inf,
    )
    mean_diff_score = diff_score
    objective = _browser_score_objective(
        browser_score,
        mean_diff_score=mean_diff_score,
        mean_fit_score=fit_score,
        config=config,
    )
    fit_score = objective["fit_score"]
    diff_score = objective["diff_score"]
    metric = str(browser_score.get("metric") or "browser_score")
    views = copy.deepcopy(browser_score.get("views") if isinstance(browser_score.get("views"), list) else [])
    summary = copy.deepcopy(browser_score.get("summary") if isinstance(browser_score.get("summary"), dict) else {})
    summary["mean_diff_score"] = mean_diff_score
    summary["mean_fit_score"] = 1.0 - mean_diff_score if math.isfinite(mean_diff_score) else fit_score
    if objective.get("worst_diff_score") is not None:
        summary["worst_diff_score"] = objective.get("worst_diff_score")
    summary["optimization_diff_score"] = diff_score
    summary["optimization_fit_score"] = fit_score
    summary["optimization_fit_score_source"] = objective["source"]
    summary["metric"] = metric

    pair = {
        "view_id": "browser_score",
        "reference": "browser_score",
        "candidate": "browser_score",
        "source": "browser_score",
        "metric": metric,
    }
    multiview_analysis = {
        "summary": summary,
        "views": views,
        "source": "browser_score",
        "browser_score": copy.deepcopy(browser_score),
    }
    analysis = {
        "status": "ok",
        "score": diff_score,
        "fit_score": fit_score,
        "optimization_fit_score": fit_score,
        "optimization_fit_score_source": objective["source"],
        "browser_score": copy.deepcopy(browser_score),
        "multiview": multiview_analysis,
    }
    residual_features = _validated_browser_residual_features(
        browser_score.get("structured_residual_features")
    )
    if residual_features is None:
        residual_features = _structured_residual_feature_payload(
            render_result,
            config=config,
        )
    if residual_features is not None:
        analysis["structured_residual_features"] = residual_features
    return {
        "image_pairs": [pair],
        "pair": pair,
        "analysis": analysis,
        "diff_score": diff_score,
        "fit_score": fit_score,
        "multiview_analysis": multiview_analysis,
    }


def _browser_score_objective(
    browser_score: dict[str, Any],
    *,
    mean_diff_score: float,
    mean_fit_score: float,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = "mean"
    worst_view_weight = 0.0
    if isinstance(config, dict):
        raw_cfg = config.get("browser_score_objective")
        if isinstance(raw_cfg, dict):
            mode = str(raw_cfg.get("mode") or mode)
            worst_view_weight = _number_or_default(raw_cfg.get("worst_view_weight"), worst_view_weight)
    if not math.isfinite(worst_view_weight) or worst_view_weight < 0:
        worst_view_weight = 0.0

    worst_diff = _browser_score_worst_diff(browser_score)
    objective_diff = mean_diff_score
    objective_fit = mean_fit_score
    source = "browser_score"
    if mode == "mean_worst_blend":
        if worst_diff is None:
            worst_diff = mean_diff_score
        penalty = max(0.0, worst_diff - mean_diff_score) * worst_view_weight
        objective_diff = mean_diff_score + penalty
        objective_fit = 1.0 - objective_diff
        source = "browser_score_mean_worst_blend"
    elif mode == "reference_foreground_mae":
        source = "browser_score_reference_foreground_mae"
    objective_diff = max(0.0, min(1.0, objective_diff)) if math.isfinite(objective_diff) else math.inf
    if not math.isfinite(objective_fit):
        objective_fit = 1.0 - objective_diff if math.isfinite(objective_diff) else -math.inf
    return {
        "diff_score": objective_diff,
        "fit_score": objective_fit,
        "source": source,
        "worst_diff_score": worst_diff,
    }


def _reference_foreground_browser_score(
    render_result: dict[str, Any],
    *,
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    objective_cfg = config.get("browser_score_objective")
    if not isinstance(objective_cfg, dict) or str(objective_cfg.get("mode") or "") != "reference_foreground_mae":
        return None
    capture_cfg = config.get("laya_capture")
    browser_cfg = capture_cfg.get("browser_score") if isinstance(capture_cfg, dict) else None
    references = browser_cfg.get("reference_images") if isinstance(browser_cfg, dict) else None
    screenshots = render_result.get("screenshots")
    if not isinstance(references, list) or not isinstance(screenshots, list):
        return None
    screenshot_by_name = {
        Path(str(path)).name: Path(str(path))
        for path in screenshots
        if isinstance(path, (str, Path))
    }
    views: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        ref_path = Path(str(ref.get("path") or ""))
        cand_path = screenshot_by_name.get(ref_path.name)
        if cand_path is None:
            continue
        view_score = _reference_foreground_view_score(
            view_id=str(ref.get("view_id") or ref_path.stem),
            reference_path=ref_path,
            candidate_path=cand_path,
            threshold=_number_or_default(objective_cfg.get("foreground_threshold"), 3.0),
        )
        if view_score is not None:
            views.append(view_score)
    if not views:
        return None
    diff_score = sum(float(view["diff_score"]) for view in views) / len(views)
    fit_score = max(0.0, min(1.0, 1.0 - diff_score))
    metric = "reference_foreground_rgb_mae_v1"
    summary = {
        "mean_diff_score": diff_score,
        "mean_fit_score": fit_score,
        "optimization_diff_score": diff_score,
        "optimization_fit_score": fit_score,
        "optimization_fit_score_source": "browser_score_reference_foreground_mae",
        "metric": metric,
        "view_count": len(views),
        "foreground_pixel_count": sum(int(view.get("foreground_pixel_count", 0)) for view in views),
    }
    return {
        "metric": metric,
        "fit_score": fit_score,
        "diff_score": diff_score,
        "views": views,
        "summary": summary,
    }


_STRUCTURED_RESIDUAL_REFERENCE_CACHE: dict[str, tuple[int, Any, Any]] = {}


def _validated_browser_residual_features(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None
    normalized: list[float] = []
    for value in features:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        normalized.append(number)
    return {
        "profile": str(payload.get("profile") or "signed_rgb_grid_v1"),
        "grid_size": int(payload.get("grid_size", 4) or 4),
        "feature_count": len(normalized),
        "features": normalized,
        "source": "browser_score",
        "feature_rms": math.sqrt(sum(value * value for value in normalized) / len(normalized)),
    }


def _structured_residual_feature_payload(
    render_result: dict[str, Any],
    *,
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return compact signed image residuals for Jacobian-based proposals."""

    if not isinstance(config, dict):
        return None
    structured_cfg = config.get("structured_fish")
    residual_cfg = (
        structured_cfg.get("residual_features")
        if isinstance(structured_cfg, dict)
        else None
    )
    if not isinstance(residual_cfg, dict) or residual_cfg.get("enabled") is not True:
        return None
    capture_cfg = config.get("laya_capture")
    browser_cfg = capture_cfg.get("browser_score") if isinstance(capture_cfg, dict) else None
    references = browser_cfg.get("reference_images") if isinstance(browser_cfg, dict) else None
    screenshots = render_result.get("screenshots")
    if not isinstance(references, list) or not isinstance(screenshots, list):
        return None
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None

    grid_size = max(1, min(int(residual_cfg.get("grid_size", 4) or 4), 16))
    threshold = max(0.0, float(residual_cfg.get("foreground_threshold", 8.0) or 8.0))
    screenshot_by_name = {
        Path(str(path)).name: Path(str(path))
        for path in screenshots
        if isinstance(path, (str, Path))
    }
    features: list[float] = []
    view_ids: list[str] = []
    global_signed_sum = np.zeros(3, dtype=np.float64)
    global_weight_sum = 0.0
    for reference in references:
        if not isinstance(reference, dict):
            continue
        reference_path = Path(str(reference.get("path") or ""))
        candidate_path = screenshot_by_name.get(reference_path.name)
        if candidate_path is None or not reference_path.exists() or not candidate_path.exists():
            continue
        try:
            cache_key = str(reference_path.resolve())
            reference_mtime = int(reference_path.stat().st_mtime_ns)
            cached = _STRUCTURED_RESIDUAL_REFERENCE_CACHE.get(cache_key)
            if cached is not None and cached[0] == reference_mtime:
                reference_rgb = cached[1]
                reference_foreground = cached[2]
            else:
                reference_rgba = np.asarray(Image.open(reference_path).convert("RGBA"), dtype=np.float32)
                reference_rgb, reference_foreground = _white_composited_foreground(
                    reference_rgba,
                    threshold=threshold,
                    np_module=np,
                )
                _STRUCTURED_RESIDUAL_REFERENCE_CACHE[cache_key] = (
                    reference_mtime,
                    reference_rgb,
                    reference_foreground,
                )
            candidate_rgba = np.asarray(Image.open(candidate_path).convert("RGBA"), dtype=np.float32)
            candidate_rgb, candidate_foreground = _white_composited_foreground(
                candidate_rgba,
                threshold=threshold,
                np_module=np,
            )
        except (OSError, ValueError):
            continue
        if candidate_rgb.shape != reference_rgb.shape:
            continue
        foreground = np.maximum(reference_foreground, candidate_foreground)
        signed = (candidate_rgb - reference_rgb) / 255.0
        height, width = foreground.shape
        for grid_y in range(grid_size):
            y0 = height * grid_y // grid_size
            y1 = height * (grid_y + 1) // grid_size
            for grid_x in range(grid_size):
                x0 = width * grid_x // grid_size
                x1 = width * (grid_x + 1) // grid_size
                cell_weight = foreground[y0:y1, x0:x1]
                weight_sum = float(cell_weight.sum())
                if weight_sum <= 0.0:
                    features.extend((0.0, 0.0, 0.0))
                    continue
                cell_signed = signed[y0:y1, x0:x1]
                means = (cell_signed * cell_weight[:, :, None]).sum(axis=(0, 1)) / weight_sum
                features.extend(float(value) for value in means)
        weight_sum = float(foreground.sum())
        if weight_sum > 0.0:
            global_signed_sum += (signed * foreground[:, :, None]).sum(axis=(0, 1))
            global_weight_sum += weight_sum
        view_ids.append(str(reference.get("view_id") or reference_path.stem))
    if not features or not view_ids:
        return None
    signed_rgb_mean = (
        (global_signed_sum / global_weight_sum).tolist()
        if global_weight_sum > 0.0
        else [0.0, 0.0, 0.0]
    )
    feature_l2 = math.sqrt(sum(value * value for value in features) / len(features))
    return {
        "profile": "signed_rgb_grid_v1",
        "grid_size": grid_size,
        "view_ids": view_ids,
        "feature_count": len(features),
        "features": features,
        "signed_rgb_candidate_minus_reference": [float(value) for value in signed_rgb_mean],
        "feature_rms": feature_l2,
    }


def _white_composited_foreground(
    rgba: Any,
    *,
    threshold: float,
    np_module: Any,
) -> tuple[Any, Any]:
    alpha = rgba[:, :, 3] / 255.0
    rgb = rgba[:, :, :3] * alpha[:, :, None] + 255.0 * (1.0 - alpha[:, :, None])
    if float(alpha.max()) > float(alpha.min()) or float(alpha.min()) < 0.98:
        foreground = alpha.astype(np_module.float32)
    else:
        foreground = (
            np_module.abs(rgb - 255.0).max(axis=2) > float(threshold)
        ).astype(np_module.float32)
    return rgb, foreground


def _reference_foreground_view_score(
    *,
    view_id: str,
    reference_path: Path,
    candidate_path: Path,
    threshold: float,
) -> dict[str, Any] | None:
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    if not reference_path.exists() or not candidate_path.exists():
        return None
    ref_rgba = np.asarray(Image.open(reference_path).convert("RGBA"), dtype=np.float32)
    cand_rgba = np.asarray(Image.open(candidate_path).convert("RGBA"), dtype=np.float32)
    if ref_rgba.shape != cand_rgba.shape:
        return None
    ref_alpha = ref_rgba[:, :, 3]
    alpha_mask = ref_alpha > float(threshold)
    if 0 < int(alpha_mask.sum()) < alpha_mask.size * 0.95:
        mask = alpha_mask
    else:
        bg = ref_rgba[0, 0, :3]
        mask = np.max(np.abs(ref_rgba[:, :, :3] - bg), axis=2) > float(threshold)
    foreground_count = int(mask.sum())
    if foreground_count <= 0:
        return None
    white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
    ref_a = ref_rgba[:, :, 3:4] / 255.0
    cand_a = cand_rgba[:, :, 3:4] / 255.0
    ref_rgb = ref_rgba[:, :, :3] * ref_a + white * (1.0 - ref_a)
    cand_rgb = cand_rgba[:, :, :3] * cand_a + white * (1.0 - cand_a)
    per_pixel = np.mean(np.abs(cand_rgb[mask] - ref_rgb[mask]) / 255.0, axis=1)
    diff_score = float(np.mean(per_pixel))
    fit_score = max(0.0, min(1.0, 1.0 - diff_score))
    return {
        "view_id": view_id,
        "diff_score": diff_score,
        "fit_score": fit_score,
        "rgb_mae": diff_score,
        "foreground_pixel_count": foreground_count,
        "reference": str(reference_path),
        "candidate": str(candidate_path),
    }


def _browser_score_worst_diff(browser_score: dict[str, Any]) -> float | None:
    worst = _number_or_default(browser_score.get("worst_diff_score"), math.nan)
    if math.isfinite(worst):
        return worst
    views = browser_score.get("views")
    if not isinstance(views, list):
        return None
    values: list[float] = []
    for view in views:
        if not isinstance(view, dict):
            continue
        diff_score = _number_or_default(view.get("diff_score"), math.nan)
        if math.isfinite(diff_score):
            values.append(float(diff_score))
    return max(values) if values else None


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
    arguments = locals()
    from . import fit_single_execution

    fit_single_execution.bind_runtime(globals())
    return fit_single_execution.run_auto_adjustment(**arguments)


def _run_cma_batch_auto_adjustment(
    *,
    config: dict[str, Any],
    project_root: Path,
    output_dir: Path,
    laya_material_path: Path,
    laya_shader_params: list[Any],
    driver: RenderDriver,
    iterations: int,
    target_score: float,
    use_capture: bool,
    write_candidate_lmat: bool,
    apply_lmat: bool,
    capture_screen_after_apply: bool,
    rerender_wait_ms: int,
    screen_capture_region: str,
    screen_capture_max_keep: int | None,
    fit_score_mode: str,
    optimizer: str,
    cma_es_config: CmaesStrategyConfig | None,
    focus_callback: Callable[[str], dict[str, Any]] | None,
    auto_dir: Path,
    external_backup_dir: Path,
    state: AdjustmentState,
    current_params: dict[str, Any],
    strategy: Any,
    analysis_performance: dict[str, Any],
    warm_history: list[tuple[dict[str, Any], float]],
    warm_start_sources: dict[str, Any],
    semantic_graph: dict[str, Any] | None,
    resume_iteration_series: list[dict[str, Any]] | None = None,
    score_ceiling: dict[str, Any] | None = None,
    effective_target_score: float | None = None,
) -> dict[str, Any]:
    arguments = locals()
    from . import fit_batch_execution

    fit_batch_execution.bind_runtime(globals())
    return fit_batch_execution.run_cma_batch_auto_adjustment(**arguments)






def _resolve_auto_adjust_status(
    *,
    best_fit_score: float,
    target_score: float,
    score_ceiling: dict[str, Any] | None,
    terminal_reason: str | None,
    completed_iterations: int,
    requested_iterations: int,
    optimizer_research_summary: dict[str, Any],
) -> str:
    if best_fit_score >= target_score:
        return "target_reached"
    if (
        isinstance(score_ceiling, dict)
        and bool(score_ceiling.get("active"))
        and best_fit_score >= _effective_target_score(target_score, score_ceiling)
    ):
        return "score_ceiling_reached"
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
    research_metrics_profile = _normalize_research_metrics_profile(
        perf.get("research_metrics_profile", perf.get("metric_profile", "tiered"))
    )
    evaluation_batch_size = _coerce_positive_int(perf.get("evaluation_batch_size"), 1)
    evaluation_workers = _coerce_positive_int(perf.get("evaluation_workers"), 1)
    evaluation_parallel_safe = bool(perf.get("evaluation_parallel_safe", False))
    full_rerank_top_k = _coerce_interval(perf.get("full_rerank_top_k"), 0)
    best_full_validation = bool(perf.get("best_full_validation", False))
    target_full_validation = bool(perf.get("target_full_validation", False))
    stability_validation_repeats = _coerce_positive_int(perf.get("stability_validation_repeats"), 1)
    stability_validation_top_k = _coerce_interval(perf.get("stability_validation_top_k"), 0)
    stability_validation_batch_chunk_size = _coerce_interval(
        perf.get("stability_validation_batch_chunk_size"),
        0,
    )
    stability_validation_mode = str(perf.get("stability_validation_mode", "reset_renderer") or "reset_renderer")
    stability_validation_mode = stability_validation_mode.strip().lower()
    if stability_validation_mode in ("reset", "persistent_reset"):
        stability_validation_mode = "reset_renderer"
    elif stability_validation_mode in ("fresh", "fresh_oracles"):
        stability_validation_mode = "fresh_oracle"
    if stability_validation_mode not in ("reset_renderer", "fresh_oracle"):
        stability_validation_mode = "reset_renderer"
    stability_validation_score_policy = _normalize_stability_score_policy(
        perf.get("stability_validation_score_policy", "min"),
        default="min",
    )
    stability_validation_restart_renderer = bool(perf.get("stability_validation_restart_renderer", False))
    stability_score_drift_threshold = _coerce_positive_float(perf.get("stability_score_drift_threshold"), 0.005)
    stability_foreground_abs_threshold = _coerce_positive_float(perf.get("stability_foreground_abs_threshold"), 128.0)
    stability_foreground_ratio_threshold = _coerce_positive_float(
        perf.get("stability_foreground_ratio_threshold"),
        0.005,
    )
    fast_score_only = bool(perf.get("fast_score_only", True))
    return {
        "multiview_workers": workers_value,
        "evaluation_batch_size": evaluation_batch_size,
        "evaluation_workers": evaluation_workers,
        "evaluation_parallel_safe": evaluation_parallel_safe,
        "full_rerank_top_k": full_rerank_top_k,
        "best_full_validation": best_full_validation,
        "target_full_validation": target_full_validation,
        "stability_validation_repeats": stability_validation_repeats,
        "stability_validation_mode": stability_validation_mode,
        "stability_validation_score_policy": stability_validation_score_policy,
        "stability_validation_top_k": stability_validation_top_k,
        "stability_validation_batch_chunk_size": stability_validation_batch_chunk_size,
        "stability_validation_restart_renderer": stability_validation_restart_renderer,
        "stability_score_drift_threshold": stability_score_drift_threshold,
        "stability_foreground_abs_threshold": stability_foreground_abs_threshold,
        "stability_foreground_ratio_threshold": stability_foreground_ratio_threshold,
        "fast_score_only": fast_score_only,
        "snapshot_interval": snapshot_interval,
        "keep_last_n_artifacts": keep_last_n,
        "always_keep_best_artifact": bool(perf.get("always_keep_best_artifact", True)),
        "always_keep_first_artifact": bool(perf.get("always_keep_first_artifact", True)),
        "research_metrics_profile": research_metrics_profile,
    }


def _coerce_interval(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(fallback))


def _coerce_positive_int(value: Any, fallback: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(fallback))


def _coerce_positive_float(value: Any, fallback: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(fallback)
    if not math.isfinite(result) or result <= 0:
        return float(fallback)
    return result


def _is_snapshot_iteration(iteration: int, interval: int) -> bool:
    if iteration == 0:
        return True
    return interval > 0 and iteration % interval == 0


def _normalize_research_metrics_profile(value: Any) -> str:
    text = str(value or "tiered").strip().lower()
    if text in {"full", "fast", "tiered"}:
        return text
    if text in {"proxy", "fast_proxy"}:
        return "fast"
    if text in {"snapshot", "snapshots", "fast_non_snapshot"}:
        return "tiered"
    return "tiered"


def _research_metrics_profile_for_iteration(setting: str, *, is_snapshot: bool) -> str:
    if setting == "tiered":
        return "full" if is_snapshot else "fast"
    if setting == "fast":
        return "fast"
    return "full"




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


def _optional_float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _round_optional_float(value: float | None, digits: int = 10) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


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
    raw_stagnation_min_delta = getattr(args, "cma_stagnation_min_delta", None)
    if raw_stagnation_min_delta is None:
        stagnation_min_delta = base.stagnation_min_delta
    else:
        try:
            stagnation_min_delta = float(raw_stagnation_min_delta)
        except (TypeError, ValueError):
            stagnation_min_delta = base.stagnation_min_delta
        if not math.isfinite(stagnation_min_delta) or stagnation_min_delta < 0.0:
            stagnation_min_delta = 0.0
    raw_restart_multiplier = getattr(args, "cma_restart_population_multiplier", None)
    if raw_restart_multiplier is None:
        restart_population_multiplier = base.restart_population_multiplier
    else:
        try:
            restart_population_multiplier = float(raw_restart_multiplier)
        except (TypeError, ValueError):
            restart_population_multiplier = base.restart_population_multiplier
        if not math.isfinite(restart_population_multiplier) or restart_population_multiplier < 1.0:
            restart_population_multiplier = 1.0
    restart_population_schedule = base.restart_population_schedule
    raw_restart_population_schedule = getattr(args, "cma_restart_population_schedule", None)
    if raw_restart_population_schedule is not None:
        candidate_restart_population_schedule = str(raw_restart_population_schedule).strip().lower()
        restart_population_schedule = (
            candidate_restart_population_schedule
            if candidate_restart_population_schedule in {"ipop", "bipop"}
            else "ipop"
        )
    stagnation_stop_after_restarts = base.stagnation_stop_after_restarts
    if bool(getattr(args, "cma_continue_after_stagnation_restarts", False)):
        stagnation_stop_after_restarts = False
    restart_center_mode = base.restart_center_mode
    raw_restart_center_mode = getattr(args, "cma_restart_center_mode", None)
    if raw_restart_center_mode is not None:
        candidate_restart_center_mode = str(raw_restart_center_mode).strip().lower()
        restart_center_mode = (
            candidate_restart_center_mode
            if candidate_restart_center_mode in {"best", "random", "alternate"}
            else "best"
        )
    initial_design_samples = base.initial_design_samples
    if getattr(args, "cma_initial_design_samples", None) is not None:
        initial_design_samples = max(int(args.cma_initial_design_samples), 0)
    initial_design_method = base.initial_design_method
    raw_initial_design_method = getattr(args, "cma_initial_design_method", None)
    if raw_initial_design_method is not None:
        candidate_initial_design_method = str(raw_initial_design_method).strip().lower()
        initial_design_method = (
            candidate_initial_design_method
            if candidate_initial_design_method in {"latin_hypercube", "local_coordinate_probe"}
            else "latin_hypercube"
        )
    initial_design_include_current = base.initial_design_include_current
    if bool(getattr(args, "cma_initial_design_no_current", False)):
        initial_design_include_current = False
    initial_design_local_step_ratio = base.initial_design_local_step_ratio
    if getattr(args, "cma_initial_design_local_step_ratio", None) is not None:
        candidate_local_step_ratio = float(args.cma_initial_design_local_step_ratio)
        initial_design_local_step_ratio = (
            min(candidate_local_step_ratio, 0.5)
            if math.isfinite(candidate_local_step_ratio) and candidate_local_step_ratio > 0.0
            else 0.05
        )
    return CmaesStrategyConfig(
        mode=base.mode,
        warm_start_iters=int(args.cma_warm_start_iters) if args.cma_warm_start_iters is not None else base.warm_start_iters,
        warm_start_source=(
            str(args.cma_warm_start_source)
            if getattr(args, "cma_warm_start_source", None) is not None
            else base.warm_start_source
        ),
        population_size=int(args.cma_population_size) if args.cma_population_size is not None else base.population_size,
        sigma=float(args.cma_sigma) if args.cma_sigma is not None else base.sigma,
        seed=int(args.cma_seed) if args.cma_seed is not None else base.seed,
        hint_bias_mix_ratio=mix_ratio,
        stagnation_patience=(
            max(int(args.cma_stagnation_patience), 0)
            if args.cma_stagnation_patience is not None
            else base.stagnation_patience
        ),
        stagnation_min_delta=stagnation_min_delta,
        stagnation_min_evaluations=(
            max(int(args.cma_stagnation_min_evaluations), 0)
            if args.cma_stagnation_min_evaluations is not None
            else base.stagnation_min_evaluations
        ),
        stagnation_max_restarts=(
            max(int(args.cma_stagnation_max_restarts), 0)
            if args.cma_stagnation_max_restarts is not None
            else base.stagnation_max_restarts
        ),
        stagnation_stop_after_restarts=stagnation_stop_after_restarts,
        restart_center_mode=restart_center_mode,
        restart_population_multiplier=restart_population_multiplier,
        restart_population_schedule=restart_population_schedule,
        restart_max_population_size=(
            max(int(args.cma_restart_max_population_size), 1)
            if args.cma_restart_max_population_size is not None
            else base.restart_max_population_size
        ),
        initial_design_samples=initial_design_samples,
        initial_design_method=initial_design_method,
        initial_design_include_current=initial_design_include_current,
        initial_design_local_step_ratio=initial_design_local_step_ratio,
        allow_scene_lighting=base.allow_scene_lighting,
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
