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
    configured_optimizer = (args.optimizer or str(config.get("optimizer", "heuristic"))).strip().lower()
    if configured_optimizer not in (
        "heuristic",
        "cma_cold",
        "cma_warm",
        "semantic_group",
        "adaptive_response_search",
        "semantic_group_legacy_081",
        "subspace_cma_es",
        "cold_start_hybrid",
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
    objective_diff = max(0.0, min(1.0, objective_diff)) if math.isfinite(objective_diff) else math.inf
    if not math.isfinite(objective_fit):
        objective_fit = 1.0 - objective_diff if math.isfinite(objective_diff) else -math.inf
    return {
        "diff_score": objective_diff,
        "fit_score": objective_fit,
        "source": source,
        "worst_diff_score": worst_diff,
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
    """Run the fourth part: analysis-driven adjustment orchestration."""

    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)
    external_backup_dir = _resolve_external_backup_dir(config, project_root, output_dir)
    state = AdjustmentState(best_params=dict(initial_params), best_fit_params=dict(initial_params))
    current_params = dict(initial_params)
    resume_requested = bool(config.get("auto_adjust_resume", False))
    resume_iteration_series: list[dict[str, Any]] = []
    if resume_requested and (auto_dir / "state.json").exists():
        state = load_adjustment_state(auto_dir / "state.json")
        resume_iteration_series = _load_iteration_series(auto_dir)
        if not resume_iteration_series and state.history:
            resume_iteration_series = list(state.history)
        current_params = dict(state.best_fit_params or state.best_params or initial_params)
    result_iterations: list[dict[str, Any]] = []
    iteration_series: list[dict[str, Any]] = []
    snapshot_iterations: set[int] = set()
    full_payloads: dict[int, dict[str, Any]] = {}
    best_fit_score = -math.inf
    candidate_override: str | dict[str, str] | None = None
    candidate_browser_score_result: dict[str, Any] | None = None
    require_real_closed_loop = apply_lmat and capture_screen_after_apply
    terminal_reason: str | None = None

    warm_history: list[tuple[dict[str, Any], float]] = []
    warm_start_sources: dict[str, Any] = {
        "limit": 0,
        "source": "none",
        "elite_archive": 0,
        "iteration_history": 0,
        "total": 0,
    }
    if optimizer == "cma_warm":
        warm_history, warm_start_sources = _load_optimizer_warm_start_history(
            auto_dir,
            limit=(cma_es_config.warm_start_iters if cma_es_config else 12),
            source=(cma_es_config.warm_start_source if cma_es_config else "elite_archive_first"),
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
            initial_params=current_params,
            shader_params=laya_shader_params,
            policies=policies,
            unity_material_params=unity_material_params,
            cma_es_config=cma_es_config,
            warm_start_history=warm_history,
            semantic_graph=semantic_graph,
            auto_adjust_mode=str(config.get("auto_adjust_mode", "fresh_fit")),
            cold_start_prior_anchors=_cold_start_prior_anchors_from_config(config),
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
    optimizer_checkpoint_path = auto_dir / "optimizer_checkpoint.pkl"
    if resume_requested and optimizer_checkpoint_path.exists() and hasattr(strategy, "load_checkpoint"):
        try:
            strategy.load_checkpoint(optimizer_checkpoint_path)
        except (OSError, EOFError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            payload = {
                "status": "configuration_error",
                "reason": str(exc),
                "optimizer": optimizer,
                "target_score": target_score,
                "iterations": resume_iteration_series,
                "state_path": str(auto_dir / "state.json"),
                "optimizer_checkpoint_path": str(optimizer_checkpoint_path),
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

    oracle_stabilization = _prepare_render_oracle(
        config=config,
        auto_dir=auto_dir,
        driver=driver,
        params=current_params,
        resume_iteration=int(state.iteration),
    )
    score_ceiling = _resolve_score_ceiling(
        config,
        target_score=target_score,
        oracle_stabilization=oracle_stabilization,
    )
    effective_target_score = _effective_target_score(target_score, score_ceiling)

    analysis_performance = _resolve_analysis_performance(config)
    snapshot_interval = int(analysis_performance["snapshot_interval"])
    keep_last_n_artifacts = int(analysis_performance["keep_last_n_artifacts"])
    multiview_workers = analysis_performance["multiview_workers"]
    evaluation_batch_size = int(analysis_performance["evaluation_batch_size"])
    evaluation_workers = int(analysis_performance["evaluation_workers"])
    research_metrics_profile_setting = str(analysis_performance["research_metrics_profile"])
    full_rerank_top_k = int(analysis_performance["full_rerank_top_k"])
    best_full_validation = bool(analysis_performance["best_full_validation"])
    target_full_validation = bool(analysis_performance["target_full_validation"])
    stability_validation_repeats = int(analysis_performance["stability_validation_repeats"])
    stability_validation_mode = str(analysis_performance["stability_validation_mode"])
    stability_validation_score_policy = str(analysis_performance["stability_validation_score_policy"])
    stability_validation_top_k = int(analysis_performance["stability_validation_top_k"])
    stability_validation_batch_chunk_size = int(analysis_performance["stability_validation_batch_chunk_size"])
    stability_validation_restart_renderer = bool(analysis_performance["stability_validation_restart_renderer"])
    stability_score_drift_threshold = float(analysis_performance["stability_score_drift_threshold"])
    stability_foreground_abs_threshold = float(analysis_performance["stability_foreground_abs_threshold"])
    stability_foreground_ratio_threshold = float(analysis_performance["stability_foreground_ratio_threshold"])
    stability_canonical_foreground_signature = _oracle_stabilization_foreground_signature(
        oracle_stabilization,
    )
    if stability_canonical_foreground_signature is not None:
        analysis_performance["stability_canonical_foreground_signature"] = copy.deepcopy(
            stability_canonical_foreground_signature
        )
    fast_score_only_allowed = (
        bool(analysis_performance["fast_score_only"])
        and optimizer in ("cma_cold", "cma_warm", "cold_start_hybrid")
        and fit_score_mode in ("research", "perceptual")
    )
    if optimizer in ("cma_cold", "cma_warm", "cold_start_hybrid") and evaluation_batch_size > 1:
        batch_payload = _run_cma_batch_auto_adjustment(
            config=config,
            project_root=project_root,
            output_dir=output_dir,
            laya_material_path=laya_material_path,
            laya_shader_params=laya_shader_params,
            driver=driver,
            iterations=iterations,
            target_score=target_score,
            use_capture=use_capture,
            write_candidate_lmat=write_candidate_lmat,
            apply_lmat=apply_lmat,
            capture_screen_after_apply=capture_screen_after_apply,
            rerender_wait_ms=rerender_wait_ms,
            screen_capture_region=screen_capture_region,
            screen_capture_max_keep=screen_capture_max_keep,
            fit_score_mode=fit_score_mode,
            optimizer=optimizer,
            cma_es_config=cma_es_config,
            focus_callback=focus_callback,
            auto_dir=auto_dir,
            external_backup_dir=external_backup_dir,
            state=state,
            current_params=current_params,
            strategy=strategy,
            analysis_performance=analysis_performance,
            warm_history=warm_history,
            warm_start_sources=warm_start_sources,
            semantic_graph=semantic_graph,
            resume_iteration_series=resume_iteration_series,
            score_ceiling=score_ceiling,
            effective_target_score=effective_target_score,
        )
        if oracle_stabilization is not None:
            batch_payload["oracle_stabilization"] = oracle_stabilization
            _write_json(auto_dir / "auto_adjust_result.json", batch_payload)
        return batch_payload
    for local_index in range(iterations):
        iteration_started = time.perf_counter()
        iteration = state.iteration
        is_snapshot_iteration = _is_snapshot_iteration(iteration, snapshot_interval)
        research_metrics_profile = _research_metrics_profile_for_iteration(
            research_metrics_profile_setting,
            is_snapshot=is_snapshot_iteration,
        )
        timing: dict[str, Any] = {
            "snapshot_interval": snapshot_interval,
            "is_snapshot": is_snapshot_iteration,
            "perceptual_optional_enabled": is_snapshot_iteration,
            "diff_visual_enabled": is_snapshot_iteration,
            "keep_last_n_artifacts": keep_last_n_artifacts,
            "multiview_workers": multiview_workers,
            "evaluation_batch_size": evaluation_batch_size,
            "evaluation_workers": evaluation_workers,
            "research_metrics_profile": research_metrics_profile,
            "fast_score_only_enabled": fast_score_only_allowed and research_metrics_profile == "fast",
        }
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        initial_editor_capture_result: dict[str, Any] | None = None
        if candidate_override is None and candidate_browser_score_result is None:
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

        if (
            candidate_override is None
            and candidate_browser_score_result is None
            and _browser_score_context_render_enabled(config)
        ):
            context_iteration = _context_render_iteration(iteration)
            timing_step = time.perf_counter()
            try:
                context_render_result = driver.render_candidate(context_iteration, current_params)
            except Exception as exc:  # noqa: BLE001
                context_render_result = {"status": "failed", "error": str(exc), "screenshots": []}
            timing["initial_context_render_ms"] = _elapsed_ms(timing_step)
            timing["initial_context_render_iteration"] = context_iteration
            if isinstance(context_render_result, dict):
                timing["initial_context_render_status"] = context_render_result.get("status")
            if _extract_browser_score_payload(context_render_result if isinstance(context_render_result, dict) else None) is not None:
                candidate_browser_score_result = copy.deepcopy(context_render_result)
                timing["initial_context_browser_score_used"] = True
            else:
                timing["initial_context_browser_score_used"] = False
                screenshots = context_render_result.get("screenshots", []) if isinstance(context_render_result, dict) else []
                candidate_overrides = (
                    context_render_result.get("candidate_overrides")
                    if isinstance(context_render_result, dict)
                    else None
                )
                if isinstance(candidate_overrides, dict) and candidate_overrides:
                    candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}
                elif screenshots:
                    candidate_override = str(screenshots[0])

        if candidate_browser_score_result is not None:
            score_payload = _browser_score_analysis_payload(candidate_browser_score_result, config=config)
            image_pairs = score_payload["image_pairs"]
            pair = score_payload["pair"]
            analysis = score_payload["analysis"]
            diff_score = score_payload["diff_score"]
            fit_score = score_payload["fit_score"]
            multiview_analysis = score_payload["multiview_analysis"]
            timing["collect_image_pairs_ms"] = 0.0
            timing["analyze_multiview_ms"] = 0.0
            timing["browser_score_used"] = True
            timing["browser_score_metric"] = multiview_analysis.get("summary", {}).get("metric")
            candidate_browser_score_result = None
        else:
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
                research_metrics_profile=research_metrics_profile,
                workers=multiview_workers,
                fast_score_only=bool(timing["fast_score_only_enabled"]),
                write_report=not (
                    bool(timing["fast_score_only_enabled"])
                    and not bool(timing["is_snapshot"])
                ),
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
        scored_params = copy.deepcopy(current_params)

        target_stop_reason = _target_stop_reason(
            fit_score,
            target_score=target_score,
            score_ceiling=score_ceiling,
        )
        if target_stop_reason and not (require_real_closed_loop and not result_iterations):
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
                "target_score": target_score,
                "effective_target_score": effective_target_score,
                "score_ceiling": copy.deepcopy(score_ceiling),
                "selected_stage": target_stop_reason,
                "decision": {"stop_reason": target_stop_reason},
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
            terminal_reason = target_stop_reason
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
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
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
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
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
        if editor_capture_result is not None:
            render_result = editor_capture_result
        else:
            render_result = driver.capture_candidate(iteration, next_params) if use_capture else driver.render_candidate(iteration, next_params)
        timing["candidate_capture_ms"] = _elapsed_ms(timing_step)
        candidate_override = None
        candidate_browser_score_result = None
        screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
        candidate_overrides = render_result.get("candidate_overrides") if isinstance(render_result, dict) else None
        if _extract_browser_score_payload(render_result if isinstance(render_result, dict) else None) is not None:
            candidate_browser_score_result = copy.deepcopy(render_result)
        elif isinstance(candidate_overrides, dict) and candidate_overrides:
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
            "scored_params": copy.deepcopy(scored_params),
            "score_params_role": "current_params",
            "target_score": target_score,
            "selected_stage": selected_stage_name,
            "decision": decision,
            "params_path": str(params_path),
            "candidate_params": copy.deepcopy(next_params),
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
        score_ceiling=score_ceiling,
        terminal_reason=terminal_reason,
        completed_iterations=len(result_iterations),
        requested_iterations=iterations,
        optimizer_research_summary=optimizer_research_summary,
    )
    cma_es_payload = (
        cmaes_strategy_config_to_dict(cma_es_config)
        if cma_es_config and optimizer in ("cma_cold", "cma_warm")
        else None
    )
    optimizer_candidate_archive = _build_optimizer_candidate_archive(iteration_series)
    optimizer_candidate_archive_path = auto_dir / "optimizer_candidate_archive.json"
    _write_json(optimizer_candidate_archive_path, optimizer_candidate_archive)
    optimizer_evidence_summary = _build_optimizer_evidence_summary(
        status=final_status,
        terminal_reason=terminal_reason,
        target_score=target_score,
        effective_target_score=effective_target_score,
        score_ceiling=score_ceiling,
        best_fit_score=best_fit_score,
        iterations=iteration_series,
        fit_score_mode=fit_score_mode,
        optimizer_preset=_optimizer_preset_from_config(config),
        optimizer=optimizer,
        cma_es_config=cma_es_payload,
        warm_start_history_size=len(warm_history) if optimizer == "cma_warm" else 0,
        warm_start_sources=warm_start_sources,
        analysis_performance=analysis_performance,
        batch_execution=None,
        candidate_archive=optimizer_candidate_archive,
        candidate_archive_path=str(optimizer_candidate_archive_path),
    )
    optimizer_evidence_summary_path = auto_dir / "optimizer_evidence_summary.json"
    _write_json(optimizer_evidence_summary_path, optimizer_evidence_summary)
    payload = {
        "status": final_status,
        "terminal_reason": terminal_reason,
        "target_score": target_score,
        "effective_target_score": effective_target_score,
        "score_ceiling": copy.deepcopy(score_ceiling),
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
        "analysis_performance": analysis_performance,
        "optimizer_preset": _optimizer_preset_from_config(config),
        "optimizer": optimizer,
        "cma_es_config": cma_es_payload,
        "warm_start_history_size": len(warm_history) if optimizer == "cma_warm" else 0,
        "warm_start_sources": warm_start_sources,
        "optimizer_evidence_summary": optimizer_evidence_summary,
        "optimizer_evidence_summary_path": str(optimizer_evidence_summary_path),
        "optimizer_candidate_archive": optimizer_candidate_archive,
        "optimizer_candidate_archive_path": str(optimizer_candidate_archive_path),
        "effect_graph": semantic_graph,
        "optimizer_research_summary": optimizer_research_summary,
    }
    if oracle_stabilization is not None:
        payload["oracle_stabilization"] = oracle_stabilization
    _write_json(auto_dir / "auto_adjust_result.json", payload)
    return payload


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
    """Run CMA-ES in explicit ask-many/tell-many batches.

    The implementation is intentionally sequential at the renderer boundary:
    the current Laya path writes one shared ``.lmat`` file, so true renderer
    parallelism needs multiple isolated workspaces or renderer instances. This
    helper establishes the optimizer contract first.
    """

    result_iterations: list[dict[str, Any]] = list(resume_iteration_series or [])
    iteration_series: list[dict[str, Any]] = list(resume_iteration_series or [])
    snapshot_iterations: set[int] = {
        int(entry["iteration"])
        for entry in iteration_series
        if isinstance(entry.get("iteration"), int) and bool(entry.get("is_snapshot"))
    }
    full_payloads: dict[int, dict[str, Any]] = {}
    best_fit_score = float(state.best_fit_score) if math.isfinite(float(state.best_fit_score)) else -math.inf
    terminal_reason: str | None = None
    require_real_closed_loop = apply_lmat and capture_screen_after_apply
    snapshot_interval = int(analysis_performance["snapshot_interval"])
    keep_last_n_artifacts = int(analysis_performance["keep_last_n_artifacts"])
    multiview_workers = analysis_performance["multiview_workers"]
    evaluation_batch_size = int(analysis_performance["evaluation_batch_size"])
    evaluation_workers_requested = int(analysis_performance["evaluation_workers"])
    evaluation_parallel_safe = bool(analysis_performance["evaluation_parallel_safe"])
    research_metrics_profile_setting = str(analysis_performance["research_metrics_profile"])
    full_rerank_top_k = int(analysis_performance["full_rerank_top_k"])
    best_full_validation = bool(analysis_performance["best_full_validation"])
    target_full_validation = bool(analysis_performance["target_full_validation"])
    stability_validation_repeats = int(analysis_performance["stability_validation_repeats"])
    stability_validation_mode = str(analysis_performance["stability_validation_mode"])
    stability_validation_score_policy = str(analysis_performance["stability_validation_score_policy"])
    stability_validation_top_k = int(analysis_performance["stability_validation_top_k"])
    stability_validation_batch_chunk_size = int(analysis_performance["stability_validation_batch_chunk_size"])
    stability_validation_restart_renderer = bool(analysis_performance["stability_validation_restart_renderer"])
    stability_score_drift_threshold = float(analysis_performance["stability_score_drift_threshold"])
    stability_foreground_abs_threshold = float(analysis_performance["stability_foreground_abs_threshold"])
    stability_foreground_ratio_threshold = float(analysis_performance["stability_foreground_ratio_threshold"])
    stability_canonical_foreground_signature = analysis_performance.get("stability_canonical_foreground_signature")
    fast_score_only_allowed = (
        bool(analysis_performance["fast_score_only"])
        and optimizer in ("cma_cold", "cma_warm", "cold_start_hybrid")
        and fit_score_mode in ("research", "perceptual")
    )
    if effective_target_score is None:
        effective_target_score = _effective_target_score(target_score, score_ceiling)
    editor_capture_cfg = config.get("laya_editor_capture") if isinstance(config.get("laya_editor_capture"), dict) else {}
    driver_is_dry_run = bool(getattr(driver, "dry_run", False))
    renderer_parallel_safe = bool(getattr(driver, "parallel_safe", False))
    renderer_worker_count_value = getattr(driver, "worker_count", None)
    renderer_worker_count = max(1, int(renderer_worker_count_value or 1))
    renderer_has_worker_pool = renderer_parallel_safe and renderer_worker_count_value is not None and renderer_worker_count > 1
    evaluation_cache_enabled = not (
        apply_lmat
        or capture_screen_after_apply
        or bool(editor_capture_cfg.get("enabled"))
        or focus_callback is not None
    )
    evaluation_cache: dict[str, dict[str, Any]] = {}
    evaluation_cache_lock = threading.Lock()
    parallel_disabled_reason = ""
    if evaluation_workers_requested <= 1:
        parallel_disabled_reason = "evaluation_workers<=1"
    elif apply_lmat:
        parallel_disabled_reason = "apply_lmat_writes_shared_material"
    elif capture_screen_after_apply:
        parallel_disabled_reason = "screen_capture_uses_shared_viewport"
    elif bool(editor_capture_cfg.get("enabled")):
        parallel_disabled_reason = "laya_editor_capture_uses_shared_command_file"
    elif focus_callback is not None:
        parallel_disabled_reason = "focus_callback_controls_shared_window"
    elif not (evaluation_parallel_safe or renderer_parallel_safe or driver_is_dry_run):
        parallel_disabled_reason = "renderer_not_marked_parallel_safe"
    if parallel_disabled_reason:
        effective_evaluation_workers = 1
    else:
        effective_evaluation_workers = min(evaluation_workers_requested, evaluation_batch_size)
        if renderer_has_worker_pool:
            effective_evaluation_workers = min(effective_evaluation_workers, renderer_worker_count)
    analysis_pipeline_enabled = (
        effective_evaluation_workers <= 1
        and evaluation_workers_requested > 1
        and evaluation_batch_size > 1
        and not evaluation_cache_enabled
    )
    analysis_pipeline_workers = (
        min(evaluation_workers_requested, evaluation_batch_size) if analysis_pipeline_enabled else 1
    )

    def _base_timing(iteration: int) -> dict[str, Any]:
        is_snapshot = _is_snapshot_iteration(iteration, snapshot_interval)
        research_metrics_profile = _research_metrics_profile_for_iteration(
            research_metrics_profile_setting,
            is_snapshot=is_snapshot,
        )
        return {
            "snapshot_interval": snapshot_interval,
            "is_snapshot": is_snapshot,
            "perceptual_optional_enabled": is_snapshot,
            "diff_visual_enabled": is_snapshot,
            "keep_last_n_artifacts": keep_last_n_artifacts,
            "multiview_workers": multiview_workers,
            "evaluation_batch_size": evaluation_batch_size,
            "evaluation_workers": effective_evaluation_workers,
            "evaluation_workers_requested": evaluation_workers_requested,
            "evaluation_parallel_safe": evaluation_parallel_safe,
            "renderer_parallel_safe": renderer_parallel_safe,
            "renderer_worker_count": renderer_worker_count,
            "research_metrics_profile": research_metrics_profile,
            "fast_score_only_enabled": fast_score_only_allowed and research_metrics_profile == "fast",
            "full_rerank_top_k": full_rerank_top_k,
            "best_full_validation": best_full_validation,
            "target_full_validation": target_full_validation,
            "evaluation_mode": "cma_batch_parallel" if effective_evaluation_workers > 1 else "cma_batch_sequential",
            **(
                {"evaluation_parallel_disabled_reason": parallel_disabled_reason}
                if parallel_disabled_reason and evaluation_workers_requested > 1
                else {}
            ),
        }

    def _analyze_override(
        *,
        iteration_dir: Path,
        candidate_override: str | dict[str, str] | None,
        timing: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], float, float, dict[str, Any]]:
        timing_step = time.perf_counter()
        image_pairs = _collect_image_pairs(
            config,
            project_root,
            output_dir,
            candidate_override=candidate_override,
        )
        timing["collect_image_pairs_ms"] = _elapsed_ms(timing_step)
        if not image_pairs:
            raise ImagePairCollectionError(
                "No image_pairs/reference_images configured and no auto reference/candidate pair found."
            )

        timing_step = time.perf_counter()
        multiview_result = analyze_multiview_pairs(
            image_pairs,
            iteration_dir / "image_analysis",
            fit_score_mode=fit_score_mode,
            aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            compute_perceptual_optional=bool(timing["perceptual_optional_enabled"]),
            generate_diff_image=bool(timing["diff_visual_enabled"]),
            research_metrics_profile=str(timing["research_metrics_profile"]),
            workers=multiview_workers,
            fast_score_only=bool(timing["fast_score_only_enabled"]),
            write_report=not (
                bool(timing["fast_score_only_enabled"])
                and not bool(timing["is_snapshot"])
            ),
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
        return image_pairs, image_pairs[0], analysis, diff_score, fit_score, multiview_analysis

    def _analysis_from_multiview_result(
        multiview_result: dict[str, Any],
    ) -> tuple[dict[str, Any], float, float, dict[str, Any]]:
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
        return analysis, diff_score, fit_score, multiview_analysis

    def _render_candidate(
        *,
        iteration: int,
        iteration_dir: Path,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        timing: dict[str, Any],
    ) -> tuple[Path, str, dict[str, Any], dict[str, Any] | None, str | dict[str, str] | None]:
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
        if editor_capture_result is not None:
            render_result = editor_capture_result
        else:
            render_result = driver.capture_candidate(iteration, next_params) if use_capture else driver.render_candidate(iteration, next_params)
        timing["candidate_capture_ms"] = _elapsed_ms(timing_step)

        candidate_override: str | dict[str, str] | None = None
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
                        previous_candidate_path=None,
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
                if focus_callback is not None:
                    focus_log.append(focus_callback(f"iter_{iteration:04d}_before_capture"))
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
        return params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override

    context_timing = _base_timing(state.iteration)
    context_override: str | dict[str, str] | None = None
    initial_editor_capture_result: dict[str, Any] | None = None
    context_browser_score_result: dict[str, Any] | None = None
    initial_context_render_result: dict[str, Any] | None = None
    timing_step = time.perf_counter()
    try:
        initial_editor_capture_result = trigger_editor_multiview_capture(
            config=config,
            project_root=project_root,
            iteration_dir=auto_dir / "batch_context",
            iteration=state.iteration,
            laya_material_path=laya_material_path,
        )
    except LayaEditorCaptureError as exc:
        initial_editor_capture_result = {
            "status": "failed",
            "error": str(exc),
            "screenshots": [],
        }
    context_timing["initial_editor_capture_ms"] = _elapsed_ms(timing_step)
    if initial_editor_capture_result is not None:
        candidate_overrides = initial_editor_capture_result.get("candidate_overrides")
        screenshots = initial_editor_capture_result.get("screenshots", [])
        if isinstance(candidate_overrides, dict) and candidate_overrides:
            context_override = {str(key): str(value) for key, value in candidate_overrides.items()}
        elif screenshots:
            context_override = str(screenshots[0])

    if context_override is None and _browser_score_context_render_enabled(config):
        context_iteration = _context_render_iteration(state.iteration)
        timing_step = time.perf_counter()
        try:
            initial_context_render_result = driver.render_candidate(context_iteration, current_params)
        except Exception as exc:  # noqa: BLE001
            initial_context_render_result = {"status": "failed", "error": str(exc), "screenshots": []}
        context_timing["initial_context_render_ms"] = _elapsed_ms(timing_step)
        context_timing["initial_context_render_iteration"] = context_iteration
        context_timing["initial_context_render_status"] = initial_context_render_result.get("status")
        if _extract_browser_score_payload(initial_context_render_result) is not None:
            context_browser_score_result = copy.deepcopy(initial_context_render_result)
            context_timing["initial_context_browser_score_used"] = True
        else:
            context_timing["initial_context_browser_score_used"] = False
            candidate_overrides = initial_context_render_result.get("candidate_overrides")
            screenshots = initial_context_render_result.get("screenshots", [])
            if isinstance(candidate_overrides, dict) and candidate_overrides:
                context_override = {str(key): str(value) for key, value in candidate_overrides.items()}
            elif screenshots:
                context_override = str(screenshots[0])

    if context_browser_score_result is not None:
        score_payload = _browser_score_analysis_payload(context_browser_score_result, config=config)
        context_image_pairs = score_payload["image_pairs"]
        context_pair = score_payload["pair"]
        context_analysis = score_payload["analysis"]
        context_diff_score = score_payload["diff_score"]
        context_fit_score = score_payload["fit_score"]
        context_multiview = score_payload["multiview_analysis"]
        context_timing["collect_image_pairs_ms"] = 0.0
        context_timing["analyze_multiview_ms"] = 0.0
        context_timing["browser_score_used"] = True
        context_timing["browser_score_metric"] = context_multiview.get("summary", {}).get("metric")
    else:
        try:
            context_image_pairs, context_pair, context_analysis, context_diff_score, context_fit_score, context_multiview = _analyze_override(
                iteration_dir=auto_dir / "batch_context",
                candidate_override=context_override,
                timing=context_timing,
            )
        except ImagePairCollectionError as exc:
            payload = {
                "status": "pending",
                "reason": str(exc),
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

    best_fit_score = context_fit_score
    state.best_fit_score = context_fit_score
    state.best_fit_params = dict(current_params)
    state.best_score = context_diff_score
    state.best_params = dict(current_params)

    context_stop_reason = _target_stop_reason(
        context_fit_score,
        target_score=target_score,
        score_ceiling=score_ceiling,
    )
    if context_stop_reason:
        iteration = state.iteration
        iteration_payload = {
            "iteration": iteration,
            "input_pair": context_pair,
            "input_pairs": [context_pair],
            "diff_score_before": context_diff_score,
            "fit_score_before": context_fit_score,
            "scored_params": copy.deepcopy(current_params),
            "score_params_role": "batch_context",
            "target_score": target_score,
            "effective_target_score": effective_target_score,
            "score_ceiling": copy.deepcopy(score_ceiling),
            "selected_stage": context_stop_reason,
            "decision": {"stop_reason": context_stop_reason},
            "perceptual_signals": _extract_perceptual_signals(context_analysis),
            "multiview_analysis": context_multiview,
            "initial_editor_capture_result": initial_editor_capture_result,
            "timing": {**context_timing, "iteration_total_ms": 0.0},
        }
        _record_iteration_outputs(
            auto_dir=auto_dir,
            iteration_payload=iteration_payload,
            result_iterations=result_iterations,
            iteration_series=iteration_series,
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            is_snapshot=True,
            is_best=True,
        )
        terminal_reason = context_stop_reason

    def _cache_key_for_candidate(iteration: int, next_params: dict[str, Any]) -> str:
        timing = _base_timing(iteration)
        return _candidate_evaluation_cache_key(
            next_params,
            fit_score_mode=fit_score_mode,
            research_metrics_profile=str(timing["research_metrics_profile"]),
            perceptual_optional_enabled=bool(timing["perceptual_optional_enabled"]),
            diff_visual_enabled=bool(timing["diff_visual_enabled"]),
            fast_score_only_enabled=bool(timing["fast_score_only_enabled"]),
        )

    def _cache_payload(cache_key: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "cache_key": cache_key,
            "source_iteration": int(record["iteration"]),
            "render_result": copy.deepcopy(record["render_result"]),
            "image_pairs": copy.deepcopy(record["image_pairs"]),
            "pair": copy.deepcopy(record["pair"]),
            "analysis": copy.deepcopy(record["analysis"]),
            "diff_score": float(record["diff_score"]),
            "fit_score": float(record["fit_score"]),
            "multiview_analysis": copy.deepcopy(record["multiview_analysis"]),
        }

    context_cache_key = _candidate_evaluation_cache_key(
        current_params,
        fit_score_mode=fit_score_mode,
        research_metrics_profile=str(context_timing["research_metrics_profile"]),
        perceptual_optional_enabled=bool(context_timing["perceptual_optional_enabled"]),
        diff_visual_enabled=bool(context_timing["diff_visual_enabled"]),
        fast_score_only_enabled=bool(context_timing["fast_score_only_enabled"]),
    )
    context_render_result = (
        copy.deepcopy(context_browser_score_result)
        if isinstance(context_browser_score_result, dict)
        else copy.deepcopy(initial_context_render_result)
        if isinstance(initial_context_render_result, dict)
        else copy.deepcopy(initial_editor_capture_result)
        if isinstance(initial_editor_capture_result, dict)
        else {"status": "batch_context", "screenshots": []}
    )
    context_render_result.setdefault("status", "batch_context")
    context_cache_payload = _cache_payload(
        context_cache_key,
        {
            "iteration": state.iteration,
            "render_result": context_render_result,
            "image_pairs": context_image_pairs,
            "pair": context_pair,
            "analysis": context_analysis,
            "diff_score": context_diff_score,
            "fit_score": context_fit_score,
            "multiview_analysis": context_multiview,
        },
    )
    if evaluation_cache_enabled:
        evaluation_cache[context_cache_key] = context_cache_payload
    batch_context_summary = {
        "fit_score": context_fit_score,
        "diff_score": context_diff_score,
        "score_params_role": "batch_context",
        "timing": copy.deepcopy(context_timing),
    }

    def _cached_batch_candidate_record(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
        cache_key: str,
        cached: dict[str, Any],
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        candidate_dir = iteration_dir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        timing_step = time.perf_counter()
        params_path = candidate_dir / "params.json"
        _write_json(params_path, next_params)
        candidate_lmat_path = ""
        if write_candidate_lmat:
            candidate_lmat_path = str(candidate_dir / laya_material_path.name)
            lmat_io.write_candidate_lmat(
                laya_material_path,
                candidate_lmat_path,
                next_params,
                allow_missing_keys=True,
            )
        timing["write_candidate_ms"] = _elapsed_ms(timing_step)
        timing["candidate_capture_ms"] = 0.0
        timing["collect_image_pairs_ms"] = 0.0
        timing["analyze_multiview_ms"] = 0.0
        timing["candidate_evaluation_cache_hit"] = True
        timing["candidate_evaluation_cache_key"] = cache_key
        timing["candidate_evaluation_cache_source_iteration"] = int(cached["source_iteration"])
        timing["iteration_total_ms"] = _elapsed_ms(iteration_started)
        return {
            "batch_index": batch_index,
            "iteration": iteration,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": {
                "status": "cached_evaluation",
                "cache_key": cache_key,
                "source_iteration": int(cached["source_iteration"]),
                "source_render_result": copy.deepcopy(cached.get("render_result")),
            },
            "screen_capture_result": None,
            "image_pairs": copy.deepcopy(cached["image_pairs"]),
            "pair": copy.deepcopy(cached["pair"]),
            "analysis": copy.deepcopy(cached["analysis"]),
            "diff_score": float(cached["diff_score"]),
            "fit_score": float(cached["fit_score"]),
            "multiview_analysis": copy.deepcopy(cached["multiview_analysis"]),
            "timing": timing,
        }

    def _evaluate_batch_candidate(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        cache_key = _cache_key_for_candidate(iteration, next_params)
        if cache_key == context_cache_key:
            return _cached_batch_candidate_record(
                batch_index=batch_index,
                batch_size=batch_size,
                iteration=iteration,
                next_params=next_params,
                decision=decision,
                batch_propose_ms=batch_propose_ms,
                cache_key=cache_key,
                cached=context_cache_payload,
            )
        if evaluation_cache_enabled:
            with evaluation_cache_lock:
                cached = evaluation_cache.get(cache_key)
            if cached is not None:
                return _cached_batch_candidate_record(
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=iteration,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                    cache_key=cache_key,
                    cached=cached,
                )
        timing["candidate_evaluation_cache_hit"] = False
        timing["candidate_evaluation_cache_key"] = cache_key
        params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override = _render_candidate(
            iteration=iteration,
            iteration_dir=iteration_dir,
            next_params=next_params,
            decision=decision,
            timing=timing,
        )
        if _extract_browser_score_payload(render_result) is not None:
            score_payload = _browser_score_analysis_payload(render_result, config=config)
            image_pairs = score_payload["image_pairs"]
            pair = score_payload["pair"]
            analysis = score_payload["analysis"]
            diff_score = score_payload["diff_score"]
            fit_score = score_payload["fit_score"]
            multiview_analysis = score_payload["multiview_analysis"]
            timing["collect_image_pairs_ms"] = 0.0
            timing["analyze_multiview_ms"] = 0.0
            timing["browser_score_used"] = True
            timing["browser_score_metric"] = multiview_analysis.get("summary", {}).get("metric")
        else:
            image_pairs, pair, analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                iteration_dir=iteration_dir,
                candidate_override=candidate_override,
                timing=timing,
            )
        timing["iteration_total_ms"] = _elapsed_ms(iteration_started)
        record = {
            "batch_index": batch_index,
            "iteration": iteration,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "screen_capture_result": screen_capture_result,
            "image_pairs": image_pairs,
            "pair": pair,
            "analysis": analysis,
            "diff_score": diff_score,
            "fit_score": fit_score,
            "multiview_analysis": multiview_analysis,
            "timing": timing,
        }
        if evaluation_cache_enabled:
            with evaluation_cache_lock:
                evaluation_cache.setdefault(cache_key, _cache_payload(cache_key, record))
        return record

    def _render_batch_candidate_for_analysis_pipeline(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        timing["candidate_evaluation_cache_hit"] = False
        timing["candidate_evaluation_cache_key"] = _cache_key_for_candidate(iteration, next_params)
        timing["evaluation_mode"] = "cma_batch_render_analysis_pipeline"
        timing["analysis_pipeline_enabled"] = True
        timing["analysis_pipeline_workers"] = min(analysis_pipeline_workers, batch_size)
        params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override = _render_candidate(
            iteration=iteration,
            iteration_dir=iteration_dir,
            next_params=next_params,
            decision=decision,
            timing=timing,
        )
        return {
            "batch_index": batch_index,
            "iteration": iteration,
            "iteration_started": iteration_started,
            "iteration_dir": iteration_dir,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "screen_capture_result": screen_capture_result,
            "candidate_override": candidate_override,
            "timing": timing,
        }

    def _finish_analysis_pipeline_candidate(rendered: dict[str, Any]) -> dict[str, Any]:
        timing = rendered["timing"]
        render_result = rendered["render_result"]
        if _extract_browser_score_payload(render_result) is not None:
            score_payload = _browser_score_analysis_payload(render_result, config=config)
            image_pairs = score_payload["image_pairs"]
            pair = score_payload["pair"]
            analysis = score_payload["analysis"]
            diff_score = score_payload["diff_score"]
            fit_score = score_payload["fit_score"]
            multiview_analysis = score_payload["multiview_analysis"]
            timing["collect_image_pairs_ms"] = 0.0
            timing["analyze_multiview_ms"] = 0.0
            timing["browser_score_used"] = True
            timing["browser_score_metric"] = multiview_analysis.get("summary", {}).get("metric")
        else:
            image_pairs, pair, analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                iteration_dir=rendered["iteration_dir"],
                candidate_override=rendered["candidate_override"],
                timing=timing,
            )
        timing["iteration_total_ms"] = _elapsed_ms(float(rendered["iteration_started"]))
        return {
            "batch_index": rendered["batch_index"],
            "iteration": rendered["iteration"],
            "next_params": rendered["next_params"],
            "decision": rendered["decision"],
            "params_path": rendered["params_path"],
            "candidate_lmat_path": rendered["candidate_lmat_path"],
            "render_result": rendered["render_result"],
            "screen_capture_result": rendered["screen_capture_result"],
            "image_pairs": image_pairs,
            "pair": pair,
            "analysis": analysis,
            "diff_score": diff_score,
            "fit_score": fit_score,
            "multiview_analysis": multiview_analysis,
            "timing": timing,
        }

    def _evaluate_batch_records_with_analysis_pipeline(
        proposals: list[tuple[dict[str, Any], dict[str, Any]]],
        *,
        batch_size: int,
        first_iteration: int,
        batch_propose_ms: float,
    ) -> list[dict[str, Any]]:
        records_by_index: dict[int, dict[str, Any]] = {}
        max_workers = max(1, min(analysis_pipeline_workers, batch_size))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="candidate-analysis") as executor:
            futures = {}
            for batch_index, (next_params, decision) in enumerate(proposals):
                cache_key = _cache_key_for_candidate(first_iteration + batch_index, next_params)
                if cache_key == context_cache_key:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=context_cache_payload,
                    )
                    continue
                rendered = _render_batch_candidate_for_analysis_pipeline(
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=first_iteration + batch_index,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                )
                if rendered.get("candidate_override") is None and require_real_closed_loop:
                    timing = rendered["timing"]
                    timing["evaluation_mode"] = "cma_batch_sequential"
                    timing["analysis_pipeline_enabled"] = False
                    timing["analysis_pipeline_skipped"] = "missing_candidate_override"
                    records_by_index[batch_index] = _finish_analysis_pipeline_candidate(rendered)
                    continue
                futures[executor.submit(_finish_analysis_pipeline_candidate, rendered)] = batch_index
            for future in as_completed(futures):
                batch_index = futures[future]
                records_by_index[batch_index] = future.result()
        return [records_by_index[index] for index in range(batch_size)]

    def _evaluate_batch_records(
        proposals: list[tuple[dict[str, Any], dict[str, Any]]],
        *,
        batch_size: int,
        first_iteration: int,
        batch_propose_ms: float,
    ) -> list[dict[str, Any]]:
        records_by_index: dict[int, dict[str, Any]] = {}
        max_workers = min(effective_evaluation_workers, batch_size)
        cache_keys: dict[int, str] = {
            batch_index: _cache_key_for_candidate(first_iteration + batch_index, next_params)
            for batch_index, (next_params, _decision) in enumerate(proposals)
        }
        first_index_by_cache_key: dict[str, int] = {}
        duplicate_source_by_index: dict[int, int] = {}
        scheduled_unique_indices: set[int] = set()

        if evaluation_cache_enabled:
            for batch_index, (next_params, decision) in enumerate(proposals):
                cache_key = cache_keys[batch_index]
                if cache_key == context_cache_key:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=context_cache_payload,
                    )
                    continue
                with evaluation_cache_lock:
                    cached = evaluation_cache.get(cache_key)
                if cached is not None:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=cached,
                    )
                    continue
                source_index = first_index_by_cache_key.get(cache_key)
                if source_index is not None:
                    duplicate_source_by_index[batch_index] = source_index
                    continue
                first_index_by_cache_key[cache_key] = batch_index
                scheduled_unique_indices.add(batch_index)
        else:
            scheduled_unique_indices = set(range(batch_size))

        def _submit_wave(
            executor: ThreadPoolExecutor,
            wave: list[tuple[int, tuple[dict[str, Any], dict[str, Any]]]],
        ) -> None:
            if not wave:
                return
            futures = {
                executor.submit(
                    _evaluate_batch_candidate,
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=first_iteration + batch_index,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                ): batch_index
                for batch_index, (next_params, decision) in wave
            }
            for future in as_completed(futures):
                batch_index = futures[future]
                records_by_index[batch_index] = future.result()

        def _materialize_duplicate(batch_index: int) -> None:
            if batch_index in records_by_index:
                return
            cache_key = cache_keys[batch_index]
            with evaluation_cache_lock:
                cached = evaluation_cache.get(cache_key)
            if cached is None:
                source_index = duplicate_source_by_index[batch_index]
                source_record = records_by_index.get(source_index)
                if source_record is None:
                    raise RuntimeError(
                        "Duplicate candidate cache source was not evaluated: "
                        f"source batch index {source_index}, duplicate batch index {batch_index}"
                    )
                cached = _cache_payload(cache_key, source_record)
                with evaluation_cache_lock:
                    cached = evaluation_cache.setdefault(cache_key, cached)
            next_params, decision = proposals[batch_index]
            records_by_index[batch_index] = _cached_batch_candidate_record(
                batch_index=batch_index,
                batch_size=batch_size,
                iteration=first_iteration + batch_index,
                next_params=next_params,
                decision=decision,
                batch_propose_ms=batch_propose_ms,
                cache_key=cache_key,
                cached=cached,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            if renderer_has_worker_pool:
                for start in range(0, batch_size, max_workers):
                    end = min(start + max_workers, batch_size)
                    wave = [
                        (batch_index, proposals[batch_index])
                        for batch_index in range(start, end)
                        if batch_index in scheduled_unique_indices
                    ]
                    _submit_wave(executor, wave)
                    for batch_index in range(start, end):
                        if batch_index in duplicate_source_by_index:
                            _materialize_duplicate(batch_index)
            else:
                wave = [
                    (batch_index, proposals[batch_index])
                    for batch_index in range(batch_size)
                    if batch_index in scheduled_unique_indices
                ]
                _submit_wave(executor, wave)
                for batch_index in range(batch_size):
                    if batch_index in duplicate_source_by_index:
                        _materialize_duplicate(batch_index)

        return [records_by_index[index] for index in range(batch_size)]

    def _full_rerank_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if full_rerank_top_k <= 0 or len(batch_records) <= 1:
            return
        eligible_records = [
            record
            for record in batch_records
            if str(record.get("timing", {}).get("research_metrics_profile") or "").lower() != "full"
        ]
        if not eligible_records:
            return
        top_records = sorted(
            eligible_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )[:full_rerank_top_k]
        selected_ids = {int(record["iteration"]) for record in top_records}
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["full_rerank_selected"] = int(record.get("iteration", -1)) in selected_ids
            timing["full_rerank_top_k"] = full_rerank_top_k
        for record in top_records:
            timing = record["timing"]
            source_fit_score = float(record["fit_score"])
            source_diff_score = float(record["diff_score"])
            timing["full_rerank_source_fit_score"] = source_fit_score
            timing["full_rerank_source_diff_score"] = source_diff_score
            timing["full_rerank_profile"] = "full"
            timing_step = time.perf_counter()
            iteration_dir = auto_dir / f"iter_{int(record['iteration']):04d}"
            multiview_result = analyze_multiview_pairs(
                record["image_pairs"],
                iteration_dir / "full_rerank",
                fit_score_mode=fit_score_mode,
                aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
                compute_perceptual_optional=False,
                generate_diff_image=False,
                research_metrics_profile="full",
                workers=multiview_workers,
            )
            timing["full_rerank_ms"] = _elapsed_ms(timing_step)
            analysis, diff_score, fit_score, multiview_analysis = _analysis_from_multiview_result(multiview_result)
            record["analysis"] = analysis
            record["diff_score"] = diff_score
            record["fit_score"] = fit_score
            record["multiview_analysis"] = multiview_analysis

    def _record_has_full_profile(record: dict[str, Any]) -> bool:
        timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
        return (
            str(timing.get("research_metrics_profile") or "").lower() == "full"
            or str(timing.get("full_rerank_profile") or "").lower() == "full"
            or str(timing.get("best_full_validation_profile") or "").lower() == "full"
            or str(timing.get("target_full_validation_profile") or "").lower() == "full"
        )

    def _full_validate_record(record: dict[str, Any], subdir_name: str) -> None:
        timing = record["timing"]
        timing_step = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{int(record['iteration']):04d}"
        multiview_result = analyze_multiview_pairs(
            record["image_pairs"],
            iteration_dir / subdir_name,
            fit_score_mode=fit_score_mode,
            aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            compute_perceptual_optional=False,
            generate_diff_image=False,
            research_metrics_profile="full",
            workers=multiview_workers,
        )
        timing[f"{subdir_name}_ms"] = _elapsed_ms(timing_step)
        analysis, diff_score, fit_score, multiview_analysis = _analysis_from_multiview_result(multiview_result)
        record["analysis"] = analysis
        record["diff_score"] = diff_score
        record["fit_score"] = fit_score
        record["multiview_analysis"] = multiview_analysis

    def _stability_validate_record(record: dict[str, Any], subdir_name: str) -> None:
        timing = record["timing"]
        timing["stability_validation_repeats"] = stability_validation_repeats
        timing["stability_validation_mode"] = stability_validation_mode
        timing["stability_validation_score_policy_config"] = stability_validation_score_policy
        timing["stability_validation_restart_renderer"] = stability_validation_restart_renderer
        timing["stability_validation_selected"] = False
        if stability_validation_repeats <= 1:
            return
        if isinstance(record.get("stability_validation"), dict):
            timing["stability_validation_skipped"] = "already_validated"
            return
        if apply_lmat or capture_screen_after_apply:
            timing["stability_validation_skipped"] = "mutating_apply_or_screen_capture_path"
            return

        timing["stability_validation_selected"] = True
        timing_step = time.perf_counter()
        original_iteration = int(record["iteration"])

        def _apply_fresh_oracle_summary(fresh_summary: dict[str, Any] | None) -> None:
            summary = _fresh_oracle_stability_summary(fresh_summary)
            record["stability_validation"] = summary
            timing["stability_validation_ms"] = _elapsed_ms(timing_step)
            timing["stability_validation_stable"] = bool(summary["stable"])
            timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
            timing["stability_validation_worst_foreground_weight_sum_spread"] = summary.get(
                "worst_foreground_weight_sum_spread"
            )
            timing["stability_validation_score_policy"] = summary["score_policy"]
            if summary["conservative_fit_score"] is not None:
                record["fit_score"] = float(summary["conservative_fit_score"])
            if summary["conservative_diff_score"] is not None:
                record["diff_score"] = float(summary["conservative_diff_score"])

        if stability_validation_mode == "fresh_oracle":
            validator = getattr(driver, "validate_persistent_oracle_stability", None)
            if callable(validator):
                output_subdir = str(
                    Path("auto_adjust")
                    / f"iter_{original_iteration:04d}"
                    / f"{subdir_name}_fresh_oracle"
                )
                fresh_summary = validator(
                    iteration=original_iteration + 1_000_000,
                    params=record["next_params"],
                    attempts=stability_validation_repeats,
                    output_subdir=output_subdir,
                )
                _apply_fresh_oracle_summary(fresh_summary)
                return
            timing["stability_validation_fresh_oracle_fallback"] = "driver_does_not_support_validation"

        samples = [_stability_sample_from_record(record, repeat_index=0, label="primary")]
        for repeat_index in range(1, stability_validation_repeats):
            validation_iteration = original_iteration + repeat_index * 1_000_000
            validation_dir = auto_dir / f"iter_{original_iteration:04d}" / f"{subdir_name}_repeat_{repeat_index:02d}"
            repeat_timing = _base_timing(validation_iteration)
            repeat_timing["stability_validation_repeat_index"] = repeat_index
            if stability_validation_restart_renderer:
                restart_payload = _restart_renderer_for_stability(repeat_index)
                timing.setdefault("stability_validation_restart_results", []).append(restart_payload)
            repeat_decision = copy.deepcopy(record["decision"])
            _params_path, _candidate_lmat_path, render_result, _screen_capture_result, candidate_override = _render_candidate(
                iteration=validation_iteration,
                iteration_dir=validation_dir,
                next_params=record["next_params"],
                decision=repeat_decision,
                timing=repeat_timing,
            )
            if _extract_browser_score_payload(render_result) is not None:
                score_payload = _browser_score_analysis_payload(render_result, config=config)
                diff_score = float(score_payload["diff_score"])
                fit_score = float(score_payload["fit_score"])
                multiview_analysis = score_payload["multiview_analysis"]
            else:
                screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
                if not candidate_override and not screenshots:
                    repeat_timing["stability_validation_render_failed"] = True
                    repeat_timing["stability_validation_render_status"] = (
                        render_result.get("status") if isinstance(render_result, dict) else None
                    )
                    if stability_validation_restart_renderer:
                        recovery_payload = _restart_renderer_for_stability(repeat_index)
                        recovery_payload["phase"] = "after_failed_stability_render"
                        timing.setdefault("stability_validation_restart_results", []).append(recovery_payload)
                    diff_score = 1.0
                    fit_score = 0.0
                    multiview_analysis = _failed_stability_multiview_analysis(render_result)
                else:
                    _image_pairs, _pair, _analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                        iteration_dir=validation_dir,
                        candidate_override=candidate_override,
                        timing=repeat_timing,
                    )
            samples.append(
                _stability_sample(
                    repeat_index=repeat_index,
                    label=f"repeat_{repeat_index:02d}",
                    fit_score=float(fit_score),
                    diff_score=float(diff_score),
                    multiview_analysis=multiview_analysis,
                    render_result=render_result,
                    timing=repeat_timing,
                )
            )

        summary = _stability_summary(samples)
        record["stability_validation"] = summary
        timing["stability_validation_ms"] = _elapsed_ms(timing_step)
        timing["stability_validation_stable"] = bool(summary["stable"])
        timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
        timing["stability_validation_worst_foreground_weight_sum_spread"] = summary[
            "worst_foreground_weight_sum_spread"
        ]
        timing["stability_validation_score_policy"] = "conservative_min"
        if summary["conservative_fit_score"] is not None:
            record["fit_score"] = float(summary["conservative_fit_score"])
        if summary["conservative_diff_score"] is not None:
            record["diff_score"] = float(summary["conservative_diff_score"])

    def _restart_renderer_for_stability(repeat_index: int) -> dict[str, Any]:
        reset_fn = getattr(driver, "reset_persistent_queue", None)
        if not callable(reset_fn):
            return {
                "repeat_index": repeat_index,
                "applied": False,
                "reason": "driver_does_not_support_reset",
            }
        timing_step = time.perf_counter()
        applied = bool(reset_fn())
        return {
            "repeat_index": repeat_index,
            "applied": applied,
            "elapsed_ms": _elapsed_ms(timing_step),
            **({} if applied else {"reason": "driver_reset_no_stop_command"}),
        }

    def _stability_sample_from_record(
        record: dict[str, Any],
        *,
        repeat_index: int,
        label: str,
    ) -> dict[str, Any]:
        return _stability_sample(
            repeat_index=repeat_index,
            label=label,
            fit_score=float(record["fit_score"]),
            diff_score=float(record["diff_score"]),
            multiview_analysis=record["multiview_analysis"],
            render_result=record["render_result"],
            timing=record["timing"],
        )

    def _stability_sample(
        *,
        repeat_index: int,
        label: str,
        fit_score: float,
        diff_score: float,
        multiview_analysis: dict[str, Any],
        render_result: dict[str, Any],
        timing: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "repeat_index": repeat_index,
            "label": label,
            "fit_score": fit_score,
            "diff_score": diff_score,
            "render_status": render_result.get("status") if isinstance(render_result, dict) else None,
            "candidate_capture_ms": timing.get("candidate_capture_ms"),
            "views": _stability_views(multiview_analysis),
        }

    def _stability_views(multiview_analysis: dict[str, Any]) -> list[dict[str, Any]]:
        raw_views = multiview_analysis.get("views") if isinstance(multiview_analysis, dict) else None
        if not isinstance(raw_views, list):
            return []
        views: list[dict[str, Any]] = []
        for item in raw_views:
            if not isinstance(item, dict):
                continue
            views.append(
                {
                    "view_id": str(item.get("view_id") or item.get("pair_id") or item.get("pair_index") or ""),
                    "fit_score": _optional_float_value(item.get("fit_score")),
                    "diff_score": _optional_float_value(item.get("diff_score")),
                    "foreground_weight_sum": _optional_float_value(item.get("foreground_weight_sum")),
                }
            )
        return views

    def _failed_stability_multiview_analysis(render_result: dict[str, Any] | None) -> dict[str, Any]:
        render_status = render_result.get("status") if isinstance(render_result, dict) else None
        return {
            "summary": {
                "mean_diff_score": 1.0,
                "mean_fit_score": 0.0,
                "optimization_fit_score": 0.0,
                "optimization_fit_score_source": "stability_render_failed",
                "metric": "stability_render_failed",
                "render_status": render_status,
            },
            "views": [],
            "source": "stability_render_failed",
        }

    def _fresh_oracle_stability_summary(fresh_summary: dict[str, Any] | None) -> dict[str, Any]:
        score_policy = f"fresh_oracle_{stability_validation_score_policy}"
        if not isinstance(fresh_summary, dict) or fresh_summary.get("status") != "ok":
            return {
                "stable": False,
                "sample_count": 0,
                "score_stable": False,
                "foreground_stable": None,
                "score_policy": score_policy,
                "fit_score_min": 0.0,
                "fit_score_max": None,
                "fit_score_median": None,
                "fit_score_mean": None,
                "fit_score_spread": None,
                "conservative_fit_score": 0.0,
                "conservative_diff_score": 1.0,
                "thresholds": {
                    "score_drift_threshold": stability_score_drift_threshold,
                    "foreground_abs_threshold": stability_foreground_abs_threshold,
                    "foreground_ratio_threshold": stability_foreground_ratio_threshold,
                },
                "fresh_oracle_summary": copy.deepcopy(fresh_summary),
            }

        spread = _optional_float_value(fresh_summary.get("fit_score_spread"))
        record_stability = _summarize_fresh_oracle_records(
            fresh_summary,
            score_drift_threshold=stability_score_drift_threshold,
            foreground_abs_threshold=stability_foreground_abs_threshold,
            foreground_ratio_threshold=stability_foreground_ratio_threshold,
            canonical_foreground_signature=stability_canonical_foreground_signature,
        )
        policy_summary = copy.deepcopy(fresh_summary)
        if isinstance(record_stability, dict):
            policy_summary.update(record_stability)
        score_stable = (
            bool(record_stability["score_stable"])
            if isinstance(record_stability, dict) and "score_stable" in record_stability
            else bool(spread is None or spread <= stability_score_drift_threshold)
        )
        foreground_stable = (
            record_stability.get("foreground_stable")
            if isinstance(record_stability, dict)
            else None
        )
        stable = bool(score_stable and foreground_stable is not False)
        selected_fit_score = _fresh_oracle_policy_value(policy_summary, "fit_score")
        selected_diff_score = _fresh_oracle_policy_value(
            policy_summary,
            "diff_score",
            allow_conservative_fallback=stability_validation_score_policy == "min",
        )
        if selected_diff_score is None and selected_fit_score is not None:
            selected_diff_score = max(0.0, 1.0 - selected_fit_score)
        return {
            "stable": stable,
            "sample_count": int(
                record_stability.get("sample_count")
                if isinstance(record_stability, dict) and record_stability.get("sample_count") is not None
                else fresh_summary.get("attempts_scored") or fresh_summary.get("attempts_completed") or 0
            ),
            "score_stable": score_stable,
            "foreground_stable": foreground_stable,
            "score_policy": score_policy,
            "fit_score_min": _optional_float_value(fresh_summary.get("fit_score_min")),
            "fit_score_max": _optional_float_value(fresh_summary.get("fit_score_max")),
            "fit_score_median": _optional_float_value(fresh_summary.get("fit_score_median")),
            "fit_score_mean": _optional_float_value(fresh_summary.get("fit_score_mean")),
            "fit_score_spread": spread,
            "conservative_fit_score": selected_fit_score,
            "conservative_diff_score": selected_diff_score,
            "worst_foreground_view_id": (
                record_stability.get("worst_foreground_view_id")
                if isinstance(record_stability, dict)
                else None
            ),
            "worst_foreground_weight_sum_spread": (
                record_stability.get("worst_foreground_weight_sum_spread")
                if isinstance(record_stability, dict)
                else None
            ),
            "worst_foreground_weight_sum_spread_ratio": (
                record_stability.get("worst_foreground_weight_sum_spread_ratio")
                if isinstance(record_stability, dict)
                else None
            ),
            "thresholds": {
                "score_drift_threshold": stability_score_drift_threshold,
                "foreground_abs_threshold": stability_foreground_abs_threshold,
                "foreground_ratio_threshold": stability_foreground_ratio_threshold,
            },
            "view_stats": copy.deepcopy(record_stability.get("view_stats")) if isinstance(record_stability, dict) else [],
            "foreground_modes": copy.deepcopy(record_stability.get("foreground_modes"))
            if isinstance(record_stability, dict)
            else [],
            "dominant_foreground_mode": copy.deepcopy(record_stability.get("dominant_foreground_mode"))
            if isinstance(record_stability, dict)
            else None,
            "canonical_foreground_signature": copy.deepcopy(record_stability.get("canonical_foreground_signature"))
            if isinstance(record_stability, dict)
            else copy.deepcopy(stability_canonical_foreground_signature),
            "canonical_foreground_mode": copy.deepcopy(record_stability.get("canonical_foreground_mode"))
            if isinstance(record_stability, dict)
            else None,
            "fresh_oracle_summary": copy.deepcopy(fresh_summary),
        }

    def _fresh_oracle_policy_value(
        fresh_summary: dict[str, Any],
        prefix: str,
        *,
        allow_conservative_fallback: bool = True,
    ) -> float | None:
        return _select_stability_policy_value(
            fresh_summary,
            prefix,
            stability_validation_score_policy,
            allow_conservative_fallback=allow_conservative_fallback,
        )

    def _stability_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
        return _summarize_stability_samples(
            samples,
            score_drift_threshold=stability_score_drift_threshold,
            foreground_abs_threshold=stability_foreground_abs_threshold,
            foreground_ratio_threshold=stability_foreground_ratio_threshold,
        )

    def _best_full_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        stability_enabled = stability_validation_repeats > 1
        if not best_full_validation and not stability_enabled:
            return
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["best_full_validation_selected"] = False

        confirmed_best_score = best_fit_score
        ranked_records = sorted(
            batch_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )
        for record in ranked_records:
            current_score = float(record.get("fit_score", -math.inf))
            if current_score <= confirmed_best_score:
                break
            timing = record["timing"]
            if not best_full_validation and target_full_validation:
                timing["best_stability_validation_skipped"] = "target_validation_enabled"
                continue
            if best_full_validation:
                timing["best_full_validation_source_fit_score"] = float(record["fit_score"])
                timing["best_full_validation_source_diff_score"] = float(record["diff_score"])
                if _record_has_full_profile(record):
                    timing["best_full_validation_skipped"] = "already_full_profile"
                else:
                    timing["best_full_validation_selected"] = True
                    timing["best_full_validation_profile"] = "full"
                    _full_validate_record(record, "best_full_validation")
            else:
                timing["best_full_validation_skipped"] = "disabled"
            if isinstance(record.get("stability_validation"), dict):
                timing["best_stability_validation_skipped"] = "already_validated"
            else:
                _stability_validate_record(record, "best_stability_validation")
            confirmed_best_score = max(confirmed_best_score, float(record["fit_score"]))

    def _top_k_stability_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if stability_validation_repeats <= 1 or stability_validation_top_k <= 0:
            return
        ranked_records = sorted(
            batch_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )
        selected_records = [
            record for record in ranked_records[:stability_validation_top_k]
            if not isinstance(record.get("stability_validation"), dict)
        ]
        if not selected_records:
            return
        for rank, record in enumerate(selected_records):
            timing = record["timing"]
            timing["stability_validation_top_k"] = stability_validation_top_k
            timing["stability_validation_batch_chunk_size"] = stability_validation_batch_chunk_size
            timing["stability_validation_top_k_selected"] = True
            timing["stability_validation_top_k_rank"] = rank
        batch_validator = getattr(driver, "validate_persistent_oracle_stability_many", None)
        if stability_validation_mode == "fresh_oracle" and callable(batch_validator):
            chunk_size = (
                stability_validation_batch_chunk_size
                if stability_validation_batch_chunk_size > 0
                else len(selected_records)
            )
            chunks = [
                selected_records[start : start + chunk_size]
                for start in range(0, len(selected_records), chunk_size)
            ]
            fallback_records: list[dict[str, Any]] = []
            for chunk_index, chunk_records in enumerate(chunks):
                timing_step = time.perf_counter()
                candidates = []
                for record in chunk_records:
                    candidate_id = f"iter_{int(record['iteration']):04d}"
                    candidates.append(
                        {
                            "candidate_id": candidate_id,
                            "params": copy.deepcopy(record["next_params"]),
                        }
                    )
                    record["timing"]["stability_validation_repeats"] = stability_validation_repeats
                    record["timing"]["stability_validation_mode"] = stability_validation_mode
                    record["timing"]["stability_validation_score_policy_config"] = stability_validation_score_policy
                    record["timing"]["stability_validation_restart_renderer"] = stability_validation_restart_renderer
                    record["timing"]["stability_validation_selected"] = True
                    record["timing"]["stability_validation_batch_candidate_id"] = candidate_id
                    record["timing"]["stability_validation_batch_chunk_index"] = chunk_index
                    record["timing"]["stability_validation_batch_chunk_count"] = len(chunks)
                output_path = (
                    Path("auto_adjust")
                    / f"iter_{int(chunk_records[0]['iteration']):04d}"
                    / "batch_top_k_stability_validation_fresh_oracle"
                )
                if len(chunks) > 1:
                    output_path = output_path / f"chunk_{chunk_index:02d}"
                batch_summary = batch_validator(
                    iteration=int(chunk_records[0]["iteration"]) + 1_000_000,
                    candidates=candidates,
                    attempts=stability_validation_repeats,
                    output_subdir=str(output_path),
                )
                if isinstance(batch_summary, dict) and batch_summary.get("status") in ("ok", "partial", "failed"):
                    candidate_summaries = batch_summary.get("candidates")
                    if isinstance(candidate_summaries, list):
                        summary_by_id = {
                            str(item.get("candidate_id")): item
                            for item in candidate_summaries
                            if isinstance(item, dict) and item.get("candidate_id") is not None
                        }
                        for index, record in enumerate(chunk_records):
                            timing = record["timing"]
                            candidate_id = str(timing.get("stability_validation_batch_candidate_id"))
                            fresh_summary = summary_by_id.get(candidate_id)
                            if fresh_summary is None and index < len(candidate_summaries):
                                fallback_summary = candidate_summaries[index]
                                fresh_summary = fallback_summary if isinstance(fallback_summary, dict) else None
                            summary = _fresh_oracle_stability_summary(fresh_summary)
                            record["stability_validation"] = summary
                            timing["stability_validation_ms"] = _elapsed_ms(timing_step)
                            timing["stability_validation_batch_ms"] = _elapsed_ms(timing_step)
                            timing["stability_validation_stable"] = bool(summary["stable"])
                            timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
                            timing["stability_validation_worst_foreground_weight_sum_spread"] = summary.get(
                                "worst_foreground_weight_sum_spread"
                            )
                            timing["stability_validation_score_policy"] = summary["score_policy"]
                            timing["stability_validation_batch_status"] = batch_summary.get("status")
                            if summary["conservative_fit_score"] is not None:
                                record["fit_score"] = float(summary["conservative_fit_score"])
                            if summary["conservative_diff_score"] is not None:
                                record["diff_score"] = float(summary["conservative_diff_score"])
                        continue
                for record in chunk_records:
                    record["timing"]["stability_validation_batch_fallback"] = (
                        batch_summary.get("reason") if isinstance(batch_summary, dict) else "invalid_batch_summary"
                    )
                    fallback_records.append(record)
            if not fallback_records:
                return
            selected_records = fallback_records
        for rank, record in enumerate(selected_records):
            _stability_validate_record(record, f"batch_top_k_stability_validation_rank_{rank:02d}")

    def _target_full_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if not target_full_validation:
            return
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["target_full_validation_selected"] = False
            if float(record.get("fit_score", -math.inf)) < float(effective_target_score):
                continue
            if _record_has_full_profile(record):
                timing["target_full_validation_skipped"] = "already_full_profile"
            else:
                timing["target_full_validation_selected"] = True
                timing["target_full_validation_source_fit_score"] = float(record["fit_score"])
                timing["target_full_validation_source_diff_score"] = float(record["diff_score"])
                timing["target_full_validation_profile"] = "full"
                _full_validate_record(record, "target_full_validation")
            if isinstance(record.get("stability_validation"), dict):
                timing["target_stability_validation_skipped"] = "already_validated"
            else:
                _stability_validate_record(record, "target_stability_validation")

    while terminal_reason is None and state.iteration < iterations:
        remaining = iterations - state.iteration
        batch_size = min(evaluation_batch_size, remaining)
        timing_step = time.perf_counter()
        proposals = strategy.propose_many(
            StrategyContext(
                iteration=state.iteration,
                current_params=current_params,
                analysis=context_analysis,
                diff_score=context_diff_score,
                fit_score=context_fit_score,
                state=state,
            ),
            count=batch_size,
        )
        if not proposals:
            terminal_reason = "no_candidate_proposals"
            break
        batch_size = len(proposals)
        batch_propose_ms = _elapsed_ms(timing_step)
        score_pairs: list[tuple[float, float]] = []
        batch_context: tuple[dict[str, Any], dict[str, Any], float, float] | None = None
        batch_context_score = -math.inf
        first_iteration = state.iteration

        try:
            if analysis_pipeline_enabled and batch_size > 1:
                batch_records = _evaluate_batch_records_with_analysis_pipeline(
                    proposals,
                    batch_size=batch_size,
                    first_iteration=first_iteration,
                    batch_propose_ms=batch_propose_ms,
                )
            elif effective_evaluation_workers > 1 and batch_size > 1:
                batch_records = _evaluate_batch_records(
                    proposals,
                    batch_size=batch_size,
                    first_iteration=first_iteration,
                    batch_propose_ms=batch_propose_ms,
                )
            else:
                batch_records = [
                    _evaluate_batch_candidate(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                    )
                    for batch_index, (next_params, decision) in enumerate(proposals)
                ]
        except ImagePairCollectionError as exc:
            payload = {
                "status": "failed",
                "reason": str(exc),
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload
        _full_rerank_batch_records(batch_records)
        _top_k_stability_validate_batch_records(batch_records)
        _best_full_validate_batch_records(batch_records)
        _target_full_validate_batch_records(batch_records)

        for record in batch_records:
            iteration = int(record["iteration"])
            next_params = record["next_params"]
            decision = record["decision"]
            timing = record["timing"]
            diff_score = float(record["diff_score"])
            fit_score = float(record["fit_score"])
            prev_best_score = state.best_score
            is_new_best = fit_score > best_fit_score
            if is_new_best:
                best_fit_score = fit_score
            if fit_score > state.best_fit_score:
                state.best_fit_score = fit_score
                state.best_fit_params = dict(next_params)
            if diff_score < state.best_score:
                state.best_score = diff_score
                state.best_params = dict(next_params)
            if diff_score < prev_best_score - 1e-6:
                state.global_no_improve = 0
            else:
                state.global_no_improve += 1
            decision["global_no_improve"] = state.global_no_improve

            decision_stage = decision.get("stage")
            selected_stage_name = decision_stage.get("name") if isinstance(decision_stage, dict) else None
            target_stop_reason = _target_stop_reason(
                fit_score,
                target_score=target_score,
                score_ceiling=score_ceiling,
            )
            if target_stop_reason:
                decision["stop_reason"] = target_stop_reason
                selected_stage_name = target_stop_reason
            iteration_payload = {
                "iteration": iteration,
                "input_pair": record["pair"],
                "input_pairs": record["image_pairs"],
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(next_params),
                "score_params_role": "candidate_params",
                "target_score": target_score,
                "effective_target_score": effective_target_score,
                "score_ceiling": copy.deepcopy(score_ceiling),
                "selected_stage": selected_stage_name,
                "decision": decision,
                "params_path": str(record["params_path"]),
                "candidate_params": copy.deepcopy(next_params),
                "candidate_lmat_path": record["candidate_lmat_path"],
                "render_result": record["render_result"],
                "initial_editor_capture_result": initial_editor_capture_result if iteration == 0 else None,
                "screen_capture_after_apply": record["screen_capture_result"],
                "perceptual_signals": _extract_perceptual_signals(record["analysis"]),
                "multiview_analysis": record["multiview_analysis"],
                "stability_validation": copy.deepcopy(record.get("stability_validation")),
                "timing": timing,
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
                is_snapshot=bool(timing["is_snapshot"]),
                is_best=is_new_best,
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
            score_pairs.append((fit_score, diff_score))
            if fit_score > batch_context_score:
                batch_context_score = fit_score
                batch_context = (dict(next_params), record["analysis"], diff_score, fit_score)
            if target_stop_reason and not (require_real_closed_loop and not result_iterations):
                terminal_reason = target_stop_reason
            state.iteration += 1
            state.history = list(iteration_series)
            save_adjustment_state(auto_dir / "state.json", state)

        strategy.tell_many_scores(score_pairs)
        if hasattr(strategy, "save_checkpoint"):
            strategy.save_checkpoint(auto_dir / "optimizer_checkpoint.pkl")
        if batch_context is not None:
            current_params, context_analysis, context_diff_score, context_fit_score = batch_context
        strategy_stop = strategy.stop_reason()
        if strategy_stop:
            terminal_reason = strategy_stop

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
        score_ceiling=score_ceiling,
        terminal_reason=terminal_reason,
        completed_iterations=len(result_iterations),
        requested_iterations=iterations,
        optimizer_research_summary=optimizer_research_summary,
    )
    cma_es_payload = (
        cmaes_strategy_config_to_dict(cma_es_config)
        if cma_es_config and optimizer in ("cma_cold", "cma_warm")
        else None
    )
    optimizer_candidate_archive = _build_optimizer_candidate_archive(iteration_series)
    optimizer_candidate_archive_path = auto_dir / "optimizer_candidate_archive.json"
    _write_json(optimizer_candidate_archive_path, optimizer_candidate_archive)
    optimizer_evidence_summary = _build_optimizer_evidence_summary(
        status=final_status,
        terminal_reason=terminal_reason,
        target_score=target_score,
        effective_target_score=float(effective_target_score),
        score_ceiling=score_ceiling,
        best_fit_score=best_fit_score,
        iterations=iteration_series,
        fit_score_mode=fit_score_mode,
        optimizer_preset=_optimizer_preset_from_config(config),
        optimizer=optimizer,
        cma_es_config=cma_es_payload,
        warm_start_history_size=len(warm_history) if optimizer == "cma_warm" else 0,
        warm_start_sources=warm_start_sources,
        analysis_performance=analysis_performance,
        batch_execution=_build_batch_execution_summary(
            iteration_series,
            analysis_performance=analysis_performance,
            context=batch_context_summary,
        ),
        candidate_archive=optimizer_candidate_archive,
        candidate_archive_path=str(optimizer_candidate_archive_path),
    )
    optimizer_evidence_summary_path = auto_dir / "optimizer_evidence_summary.json"
    _write_json(optimizer_evidence_summary_path, optimizer_evidence_summary)
    payload = {
        "status": final_status,
        "terminal_reason": terminal_reason,
        "target_score": target_score,
        "effective_target_score": effective_target_score,
        "score_ceiling": copy.deepcopy(score_ceiling),
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
        "analysis_performance": analysis_performance,
        "batch_execution": optimizer_evidence_summary["batch_execution"],
        "optimizer_preset": _optimizer_preset_from_config(config),
        "optimizer": optimizer,
        "cma_es_config": cma_es_payload,
        "warm_start_history_size": len(warm_history) if optimizer == "cma_warm" else 0,
        "warm_start_sources": warm_start_sources,
        "optimizer_evidence_summary": optimizer_evidence_summary,
        "optimizer_evidence_summary_path": str(optimizer_evidence_summary_path),
        "optimizer_candidate_archive": optimizer_candidate_archive,
        "optimizer_candidate_archive_path": str(optimizer_candidate_archive_path),
        "effect_graph": semantic_graph,
        "optimizer_research_summary": optimizer_research_summary,
    }
    _write_json(auto_dir / "auto_adjust_result.json", payload)
    return payload




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
