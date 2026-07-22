"""Shared Phase 0.5 continuous-material recovery for any validated Laya asset."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from material_fit.assets.material_phase05 import MaterialAssetSpec, resolve_material_asset
from material_fit.laya import lmat_io
from material_fit.laya.render_driver import RenderDriver
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_recovery import (
    PERTURBATION_PRESETS,
    material_parameter_distance,
    perturb_material_params,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
    structured_material_coordinates,
    structured_material_space_manifest,
)
from material_fit.vision.cross_engine_score import score_cross_engine_views_v3


OPTIMIZATION_SCORE_METRIC = "cross_engine_foreground_components_v3"
VALIDATION_SCORE_METRIC = "cross_engine_foreground_components_v4"
SCORE_METRIC = VALIDATION_SCORE_METRIC
OPTIMIZER_ID = "material_jacobian_trust_region"
PHASE05_SCORE_READBACK_WIDTH = 720
PHASE05_SCORE_READBACK_HEIGHT = 560


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    if args.engine_libs:
        os.environ["LAYA_ENGINE_LIBS"] = str(Path(args.engine_libs).expanduser().resolve())
    run_name = args.run_name or (
        f"phase05_{args.asset}_{args.perturbation_preset}_seed{args.seed}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else repo_root / "artifacts"
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        report = run_recovery(
            repo_root=repo_root,
            run_dir=run_dir,
            asset_id=args.asset,
            profile_path=args.asset_profile or None,
            target_material_path=args.target_material or None,
            shader_path=args.shader_path or None,
            perturbation_preset=args.perturbation_preset,
            seed=args.seed,
            iterations=args.iterations,
            target_score=args.target_score,
            success_score=args.success_score,
            max_runtime_sec=args.max_runtime_sec,
            speed_gate_ms=args.speed_gate_ms,
            node_modules=args.node_modules or None,
        )
    finally:
        _cleanup_recorded_runtime(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, help="Asset adapter id, for example fish or turtle.")
    parser.add_argument("--asset-profile", default="")
    parser.add_argument("--target-material", default="")
    parser.add_argument("--shader-path", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--perturbation-preset", choices=tuple(PERTURBATION_PRESETS), default="medium")
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--iterations", type=int, default=600)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--success-score", type=float, default=0.98)
    parser.add_argument("--max-runtime-sec", type=float, default=900.0)
    parser.add_argument("--speed-gate-ms", type=float, default=500.0)
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--engine-libs", default="")
    return parser.parse_args(argv)


def run_recovery(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str,
    profile_path: str | Path | None,
    target_material_path: str | Path | None,
    shader_path: str | Path | None,
    perturbation_preset: str,
    seed: int,
    iterations: int,
    target_score: float,
    success_score: float,
    max_runtime_sec: float,
    speed_gate_ms: float,
    node_modules: str | Path | None,
) -> dict[str, Any]:
    asset = resolve_material_asset(
        repo_root,
        asset_id,
        profile_path=profile_path,
        target_material_path=target_material_path,
        shader_path=shader_path,
    )
    profile_file = asset.write_profile(run_dir / "inputs/asset_profile.json")
    _force_white_background(profile_file)
    optimizer_profile_file = _write_optimizer_profile(
        profile_file,
        run_dir / "inputs/optimizer_asset_profile.json",
        width=PHASE05_SCORE_READBACK_WIDTH,
        height=PHASE05_SCORE_READBACK_HEIGHT,
    )
    views = _profile_views(profile_file, expected_count=8)

    target_material = lmat_io.load_lmat(asset.target_material_path)
    target_params = lmat_io.extract_params(target_material)
    target_patch = material_patch_from_lmat(asset.target_material_path)
    material_coordinates = structured_material_coordinates(target_params, material_only=True)
    scene_coordinates = structured_material_coordinates(target_params, material_only=False)
    scene_coordinates = [row for row in scene_coordinates if row.param_name in STRUCTURED_SCENE_PARAM_NAMES]
    if len(material_coordinates) != 40 or len(scene_coordinates) != 6:
        raise RuntimeError(
            f"{asset.asset_id} does not satisfy the shared 40+6 parameter contract: "
            f"material={len(material_coordinates)} scene={len(scene_coordinates)}"
        )

    start_params, perturbation = perturb_material_params(
        target_params,
        preset=perturbation_preset,
        seed=seed,
    )
    tiny_params, tiny_perturbation = perturb_material_params(target_params, preset="tiny", seed=seed)
    private_dir = run_dir / "private_audit"
    inputs_dir = run_dir / "inputs"
    _write_json(private_dir / "target_params.json", target_params)
    _write_json(inputs_dir / "start_params.json", start_params)
    _write_json(inputs_dir / "perturbation_report.json", perturbation)
    _write_json(inputs_dir / "tiny_perturbation_report.json", tiny_perturbation)
    shutil.copy2(asset.target_material_path, private_dir / "target_material.lmat")
    start_material_path = inputs_dir / "start_material.lmat"
    lmat_io.write_candidate_lmat(
        asset.target_material_path,
        start_material_path,
        start_params,
        allow_missing_keys=True,
    )
    start_patch = material_patch_from_lmat(start_material_path)
    discrete_state = _discrete_state_report(
        target_params=target_params,
        start_params=start_params,
        target_patch=target_patch,
        start_patch=start_patch,
    )
    _write_json(run_dir / "discrete_state_report.json", discrete_state)
    if not discrete_state["passed"]:
        raise RuntimeError(f"start material changed locked/discrete state: {discrete_state}")
    asset_contract = _asset_contract(
        asset,
        profile_file,
        target_patch,
        material_coordinates,
        scene_coordinates,
    )
    _write_json(run_dir / "asset_contract_report.json", asset_contract)

    target_dir = run_dir / "target_render"
    optimizer_target_dir = run_dir / "optimizer_target_render"
    target_repeat_dir = run_dir / "scorer_sanity/target_repeat"
    tiny_dir = run_dir / "scorer_sanity/tiny_perturbation"
    target_driver = _build_artifact_capture_driver(
        profile_path=profile_file,
        output_root=run_dir / "target_capture_runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        _capture_artifact_set(
            driver=target_driver,
            artifact_dir=target_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
    finally:
        target_driver.close()

    optimizer_target_driver = _build_artifact_capture_driver(
        profile_path=optimizer_profile_file,
        output_root=run_dir / "optimizer_target_capture_runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        _capture_artifact_set(
            driver=optimizer_target_driver,
            artifact_dir=optimizer_target_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
    finally:
        optimizer_target_driver.close()

    scorer_driver = _build_artifact_capture_driver(
        profile_path=optimizer_profile_file,
        output_root=run_dir / "scorer_sanity/runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=optimizer_target_dir,
        node_modules=node_modules,
    )
    try:
        repeated = _capture_artifact_set(
            driver=scorer_driver,
            artifact_dir=target_repeat_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
        tiny = _capture_artifact_set(
            driver=scorer_driver,
            artifact_dir=tiny_dir,
            params=tiny_params,
            views=views,
            iteration=1,
        )
    finally:
        scorer_driver.close()
    scorer_report = _scorer_sanity_report(
        target_dir=optimizer_target_dir,
        repeat_dir=target_repeat_dir,
        tiny_dir=tiny_dir,
        views=views,
        repeated_result=repeated,
        tiny_result=tiny,
    )
    _write_json(run_dir / "scorer_sanity/scorer_sanity_report.json", scorer_report)
    if not scorer_report["passed"]:
        raise RuntimeError(f"scorer sanity failed: {scorer_report}")

    fit_config = _build_fit_config(
        asset=asset,
        profile_path=optimizer_profile_file,
        run_dir=run_dir,
        start_material_path=start_material_path,
        target_dir=optimizer_target_dir,
        target_defines=target_patch["defines"],
        target_render_states=target_patch["render_states"],
        target_score=target_score,
        node_modules=node_modules,
        views=views,
    )
    boundary = _optimizer_boundary_report(fit_config, private_dir=private_dir)
    _write_json(run_dir / "optimizer_input_boundary_report.json", boundary)
    if not boundary["passed"]:
        raise RuntimeError(f"optimizer input boundary failed: {boundary['hits']}")
    fit_config_path = run_dir / "fit_config.json"
    _write_json(fit_config_path, fit_config)

    fit_started = time.perf_counter()
    fit_returncode = _run_fit_owned(
        repo_root=repo_root,
        run_dir=run_dir,
        config_path=fit_config_path,
        iterations=iterations,
        target_score=target_score,
        max_runtime_sec=max_runtime_sec,
    )
    fit_elapsed_s = time.perf_counter() - fit_started
    if fit_returncode != 0:
        raise RuntimeError(f"fit_material exited with {fit_returncode}; see {run_dir / 'logs'}")

    best_params_path = run_dir / "output/auto_adjust/best/params.json"
    if not best_params_path.is_file():
        raise FileNotFoundError(f"optimizer did not produce best params: {best_params_path}")
    best_params = _read_json(best_params_path)
    final_driver = _build_artifact_capture_driver(
        profile_path=profile_file,
        output_root=run_dir / "final_capture/runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
    )
    try:
        start_result = _capture_artifact_set(
            driver=final_driver,
            artifact_dir=run_dir / "start_render",
            params=start_params,
            views=views,
            iteration=0,
        )
        best_result = _capture_artifact_set(
            driver=final_driver,
            artifact_dir=run_dir / "best_render",
            params=best_params,
            views=views,
            iteration=1,
        )
    finally:
        final_driver.close()
    lmat_io.write_candidate_lmat(
        asset.target_material_path,
        run_dir / "best_material.lmat",
        best_params,
        allow_missing_keys=True,
    )

    start_distance, start_rows = material_parameter_distance(target_params, start_params)
    best_distance, best_rows = material_parameter_distance(target_params, best_params)
    parameter_report = {
        "contract": "shared_material_parameter_recovery_v1",
        "optimizer_target_params_visible": False,
        "start": start_distance,
        "best": best_distance,
        "mean_normalized_error_reduction": (
            start_distance["mean_normalized_abs_error"] - best_distance["mean_normalized_abs_error"]
        ),
        "improved": best_distance["mean_normalized_abs_error"] < start_distance["mean_normalized_abs_error"],
        "coordinates": {
            name: {"start": start_rows[name], "best": best_rows[name]}
            for name in start_rows
        },
    }
    _write_json(run_dir / "parameter_recovery_report.json", parameter_report)
    timing = _timing_report(run_dir / "output/auto_adjust/iteration_series.json", speed_gate_ms)
    _write_json(run_dir / "iteration_timing_report.json", timing)
    contact_sheet = _write_contact_sheet(
        views=views,
        columns=(
            ("Target", target_dir),
            ("Perturbed start", run_dir / "start_render"),
            ("Recovered best", run_dir / "best_render"),
        ),
        output_path=run_dir / "target_start_best_eightview.png",
    )
    cleanup = _cleanup_recorded_runtime(run_dir)
    shader_default_anchor_audit = _shader_default_anchor_audit(
        shader_params_path=run_dir / "output/laya_shader_params.json",
        target_params=target_params,
        coordinates=material_coordinates,
    )
    _write_json(run_dir / "shader_default_anchor_audit.json", shader_default_anchor_audit)
    start_score = _browser_fit_score(start_result)
    best_score = _browser_fit_score(best_result)
    view_counts = {
        "target": _view_count(target_dir, views),
        "optimizer_target": _view_count(optimizer_target_dir, views),
        "start": _view_count(run_dir / "start_render", views),
        "best": _view_count(run_dir / "best_render", views),
    }
    accepted = bool(
        perturbation["changed_coordinate_count"] == 40
        and asset_contract["passed"]
        and discrete_state["passed"]
        and boundary["passed"]
        and scorer_report["passed"]
        and start_score is not None
        and best_score is not None
        and best_score >= success_score
        and parameter_report["improved"]
        and timing["gate_passed"]
        and cleanup["remaining_owned_pid_count"] == 0
        and all(count == 8 for count in view_counts.values())
    )
    report = {
        "contract": "shared_material_phase05_recovery_v1",
        "accepted": accepted,
        "asset_id": asset.asset_id,
        "run_dir": str(run_dir),
        "optimizer": "structured_material_v1",
        "optimizer_runtime_id": OPTIMIZER_ID,
        "optimization_score_metric": OPTIMIZATION_SCORE_METRIC,
        "validation_score_metric": VALIDATION_SCORE_METRIC,
        "search_coordinate_count": 40,
        "scene_coordinate_count": 6,
        "scene_coordinates_fixed": True,
        "discrete_state_fixed": True,
        "discrete_state_audit_passed": discrete_state["passed"],
        "perturbation_preset": perturbation_preset,
        "seed": seed,
        "iterations_requested": iterations,
        "fit_elapsed_s": fit_elapsed_s,
        "start_score": start_score,
        "best_score": best_score,
        "score_gain": best_score - start_score if start_score is not None and best_score is not None else None,
        "success_score": success_score,
        "parameter_recovery": parameter_report,
        "shader_default_anchor_audit": shader_default_anchor_audit,
        "scorer_sanity": scorer_report,
        "timing": timing,
        "process_cleanup": cleanup,
        "contact_sheet": str(contact_sheet),
        "target_render_dir": str(target_dir),
        "optimizer_target_render_dir": str(optimizer_target_dir),
        "optimizer_render_resolution": _profile_resolution(optimizer_profile_file),
        "artifact_render_resolution": _profile_resolution(profile_file),
        "start_render_dir": str(run_dir / "start_render"),
        "best_render_dir": str(run_dir / "best_render"),
        "best_params_path": str(best_params_path),
        "best_material_path": str(run_dir / "best_material.lmat"),
        "optimizer_input_boundary_passed": True,
        "asset_contract_passed": asset_contract["passed"],
        "view_counts": view_counts,
    }
    _write_json(run_dir / "phase05_report.json", report)
    return report


def _shader_default_anchor_audit(
    *,
    shader_params_path: Path,
    target_params: dict[str, Any],
    coordinates: list[Any],
) -> dict[str, Any]:
    payload = _read_json(shader_params_path)
    rows = payload.get("params") if isinstance(payload, dict) else None
    defaults = {
        str(row["name"]): row.get("default")
        for row in rows or []
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    matches: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for coordinate in coordinates:
        default = defaults.get(coordinate.param_name)
        try:
            default_value = float(default if coordinate.component is None else default[coordinate.component])
            target_value = float(coordinate.read(target_params))
        except (KeyError, IndexError, TypeError, ValueError):
            mismatches.append({
                "coordinate": coordinate.coordinate_id,
                "reason": "shader_default_unavailable",
            })
            continue
        if math.isclose(default_value, target_value, rel_tol=0.0, abs_tol=1.0e-9):
            matches.append(coordinate.coordinate_id)
        else:
            mismatches.append({
                "coordinate": coordinate.coordinate_id,
                "target": target_value,
                "shader_default": default_value,
            })
    return {
        "contract": "shader_default_anchor_audit_v1",
        "source": str(shader_params_path),
        "coordinate_count": len(coordinates),
        "matching_coordinate_count": len(matches),
        "all_searchable_targets_equal_shader_defaults": len(matches) == len(coordinates),
        "matching_coordinates": matches,
        "mismatches": mismatches,
        "interpretation": (
            "A passing run validates generic shader-default recovery for this target; "
            "it does not by itself validate arbitrary non-default target inversion."
        ),
    }


def _build_fit_config(
    *,
    asset: MaterialAssetSpec,
    profile_path: Path,
    run_dir: Path,
    start_material_path: Path,
    target_dir: Path,
    target_defines: dict[str, Any],
    target_render_states: dict[str, Any] | None = None,
    target_score: float,
    node_modules: str | Path | None,
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_bridge: dict[str, Any] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 0,
        "asset_profile": str(profile_path),
        "state_dir": str(run_dir / "runtime_renderer"),
        "timeout_s": 90,
        "startup_timeout_s": 90,
        "output_subdir": "score_only",
        "auto_start_renderer": True,
    }
    if node_modules:
        runtime_bridge["node_modules"] = str(Path(node_modules).expanduser().resolve())
    return {
        "case_name": run_dir.name,
        "asset_set": {
            "asset_id": asset.asset_id,
            "project_root": str(asset.project_root),
            "scene_path": str(asset.scene_path),
            "start_material_path": str(start_material_path),
            "asset_profile": str(profile_path),
        },
        "laya_shader_path": str(asset.shader_path),
        "laya_material_path": str(start_material_path),
        "unity_shader_path": "",
        "unity_material_params_path": "",
        "image_pairs": [],
        "initial_params_mode": "material",
        "auto_adjust_target_score": target_score,
        "capture_screen_after_apply": False,
        "fit_score_mode": "research",
        "browser_score_context_render": {"enabled": True},
        "browser_score_objective": {"mode": "mean"},
        "analysis_performance": {
            "multiview_workers": 1,
            "evaluation_batch_size": 1,
            "evaluation_workers": 1,
            "evaluation_parallel_safe": False,
            "full_rerank_top_k": 0,
            "best_full_validation": False,
            "target_full_validation": False,
            "snapshot_interval": 25,
            "research_metrics_profile": "tiered",
            "fast_score_only": True,
            "keep_last_n_artifacts": 8,
            "always_keep_best_artifact": True,
            "always_keep_first_artifact": True,
        },
        "optimizer": OPTIMIZER_ID,
        "optimizer_contract": "structured_material_v1",
        "search_param_space": "structured_material_v1",
        "search_param_names": list(STRUCTURED_MATERIAL_PARAM_NAMES),
        "structured_material_contract": {
            "phase": "perturb_recovery",
            "phase_profile": "material_only_recovery",
            "asset_independent": True,
            "material_coordinate_count": 40,
            "scene_coordinates_fixed": True,
            "target_params_visible_to_optimizer": False,
            "discrete_render_state": "fixed_from_target_material",
            "runtime_optimizer_id": OPTIMIZER_ID,
            "optimization_score_metric": OPTIMIZATION_SCORE_METRIC,
        },
        "material_jacobian_trust_region_contract": {
            "phase": "perturb_recovery",
            "phase_profile": "material_only_recovery",
            "asset_independent": True,
            "material_coordinate_count": 40,
            "scene_coordinates_fixed": True,
            "target_params_visible_to_optimizer": False,
            "discrete_render_state": "fixed_from_target_material",
            "optimization_score_metric": OPTIMIZATION_SCORE_METRIC,
        },
        "material_jacobian_trust_region": {
            "profile": "material_jacobian_trust_region_v1",
            "difference_mode": "forward",
            "solve_mode": "full_least_squares",
            "shader_default_anchor_enabled": True,
            "probe_step": 0.025,
            "minimum_probe_step": 0.006,
            "ridge": 0.10,
            "trust_radius": 0.12,
            "maximum_trust_radius": 0.24,
            "max_axis_update": 0.18,
            "line_search_scales": [1.0, 0.5, 0.25, 0.125],
            "feedback_source": "online_target_png_score_and_residuals_only",
            "target_params_visible": False,
        },
        "output_dir": str(run_dir / "output"),
        "dry_run": False,
        "render_command": [],
        "laya_capture": {
            "runtime_bridge": runtime_bridge,
            "browser_score": {
                "enabled": True,
                "metric": OPTIMIZATION_SCORE_METRIC,
                "rgb_weight": 1.0,
                "alpha_weight": 0.0,
                "residual_grid_size": 16,
                "reference_images": _reference_images(target_dir, views),
            },
            "material_patch": {
                "target_name": "model",
                "defines": copy.deepcopy(target_defines),
                "render_states": copy.deepcopy(target_render_states or {}),
            },
            "return_images": False,
            "persist_browser_score": False,
            "preserve_artifact_alpha": False,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "visual_quality_guard": {"enabled": False},
        },
    }


def _build_artifact_capture_driver(
    *,
    profile_path: Path,
    output_root: Path,
    defines: dict[str, Any],
    render_states: dict[str, Any] | None = None,
    references: Path | None,
    node_modules: str | Path | None,
    score_metric: str | None = None,
    candidate_registration: dict[str, Any] | None = None,
) -> RenderDriver:
    views = _profile_views(profile_path)
    runtime: dict[str, Any] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 0,
        "asset_profile": str(profile_path),
        "state_dir": str(output_root / "runtime_renderer"),
        "timeout_s": 90,
        "startup_timeout_s": 90,
        "output_subdir": "render",
        "auto_start_renderer": True,
    }
    if node_modules:
        runtime["node_modules"] = str(Path(node_modules).expanduser().resolve())
    browser_score = {"enabled": False}
    if references is not None:
        browser_score = {
            "enabled": True,
            "metric": score_metric or VALIDATION_SCORE_METRIC,
            "rgb_weight": 1.0,
            "alpha_weight": 0.0,
            "emit_artifacts": "always",
            "residual_grid_size": 16,
            "reference_images": _reference_images(references, views),
        }
        if candidate_registration is not None:
            browser_score["candidate_registration"] = copy.deepcopy(candidate_registration)
    return RenderDriver(
        output_dir=output_root,
        dry_run=False,
        capture_config={
            "runtime_bridge": runtime,
            "browser_score": browser_score,
            "material_patch": {
                "target_name": "model",
                "defines": copy.deepcopy(defines),
                "render_states": copy.deepcopy(render_states or {}),
            },
            "return_images": True,
            "preserve_artifact_alpha": False,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "visual_quality_guard": {"enabled": False},
        },
    )


def _capture_artifact_set(
    *,
    driver: RenderDriver,
    artifact_dir: Path,
    params: dict[str, Any],
    views: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    result = driver.render_candidate(iteration, params)
    if result.get("status") != "ok":
        raise RuntimeError(f"runtime artifact capture failed: {result}")
    screenshots = [Path(str(value)) for value in result.get("screenshots", [])]
    if len(screenshots) != len(views):
        raise RuntimeError(f"expected {len(views)} screenshots, got {len(screenshots)}")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for view, source in zip(views, screenshots, strict=True):
        shutil.copy2(source, artifact_dir / str(view["file_name"]))
    _write_json(artifact_dir / "capture_result.json", result)
    return result


def _run_fit_owned(
    *,
    repo_root: Path,
    run_dir: Path,
    config_path: Path,
    iterations: int,
    target_score: float,
    max_runtime_sec: float,
    optimizer: str = OPTIMIZER_ID,
) -> int:
    logs = run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "material_fit.fit_material",
        "--config",
        str(config_path),
        "--auto-adjust",
        "--iterations",
        str(iterations),
        "--target-score",
        str(target_score),
        "--optimizer",
        optimizer,
        "--write-candidate-lmat",
        "--fit-score-mode",
        "research",
    ]
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    if sys.platform.startswith("linux"):
        env.setdefault("TMPDIR", "/tmp")
        env.setdefault("TMP", "/tmp")
        env.setdefault("TEMP", "/tmp")
        env.setdefault(
            "MATERIAL_FIT_CHROMIUM_ARGS",
            "--ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox",
        )
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
    }
    with (logs / "fit_stdout.log").open("w", encoding="utf-8") as stdout, (
        logs / "fit_stderr.log"
    ).open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            **kwargs,
        )
        (run_dir / "fit.pid").write_text(f"{proc.pid}\n", encoding="ascii")
        try:
            return int(proc.wait(timeout=max_runtime_sec if max_runtime_sec > 0 else None))
        except subprocess.TimeoutExpired:
            _terminate_owned_process(proc)
            return 124
        finally:
            if proc.poll() is None:
                _terminate_owned_process(proc)
            (run_dir / "fit.pid").unlink(missing_ok=True)
            _cleanup_recorded_runtime(run_dir)


def _terminate_owned_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=8)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)


def _cleanup_recorded_runtime(run_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for record in run_dir.rglob("fit.pid"):
        try:
            pid = int(record.read_text(encoding="ascii").strip())
        except (OSError, TypeError, ValueError):
            continue
        before = _pid_exists(pid)
        command_line = _process_command_line(pid)
        owned_fit = bool(
            before
            and command_line
            and "material_fit.fit_material" in command_line
            and str(run_dir) in command_line
        )
        if before and not owned_fit:
            checks.append(
                {
                    "pid": pid,
                    "record": str(record),
                    "before": True,
                    "after": True,
                    "owned_fit": False,
                    "owned_renderer": False,
                    "action": "pid_reused_or_identity_unverified_no_action",
                    "command_line": command_line,
                }
            )
            continue
        action = "already_stopped"
        if before:
            action = "terminated_owned_tree"
            _terminate_recorded_process(pid)
        checks.append(
            {
                "pid": pid,
                "record": str(record),
                "before": before,
                "after": _pid_exists(pid),
                "owned_fit": owned_fit,
                "owned_renderer": False,
                "action": action,
                "command_line": command_line,
            }
        )
    for record in run_dir.rglob("runtime_renderer_pid.json"):
        try:
            pid = int(_read_json(record).get("pid"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        before = _pid_exists(pid)
        command_line = _process_command_line(pid)
        owned_renderer = bool(
            before
            and command_line
            and "run_runtime_renderer" in command_line
            and "material_fit" in command_line
        )
        if before and not owned_renderer:
            checks.append(
                {
                    "pid": pid,
                    "record": str(record),
                    "before": True,
                    "after": True,
                    "owned_renderer": False,
                    "action": "pid_reused_or_identity_unverified_no_action",
                    "command_line": command_line,
                }
            )
            continue
        action = "already_stopped"
        if before:
            action = "terminated_owned_tree"
            _terminate_recorded_process(pid)
        checks.append(
            {
                "pid": pid,
                "record": str(record),
                "before": before,
                "after": _pid_exists(pid),
                "owned_renderer": owned_renderer,
                "action": action,
                "command_line": command_line,
            }
        )
    report_path = run_dir / "process_cleanup_report.json"
    previous = _read_json(report_path).get("checks", []) if report_path.is_file() else []
    latest_by_record: dict[str, dict[str, Any]] = {}
    for row in [*previous, *checks]:
        record = row.get("record")
        if isinstance(record, str) and record:
            latest_by_record[record] = row
    combined = list(latest_by_record.values())
    report = {
        "contract": "owned_material_runtime_cleanup_v1",
        "checks": combined,
        "remaining_owned_pid_count": sum(
            bool(row.get("after"))
            and bool(row.get("owned_renderer") or row.get("owned_fit"))
            for row in combined
        ),
        "pid_reuse_or_unverified_count": sum(
            row.get("action") == "pid_reused_or_identity_unverified_no_action"
            for row in combined
        ),
    }
    _write_json(report_path, report)
    return report


def _terminate_recorded_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    _wait_for_pid_exit(pid, timeout_s=5.0)
    if _pid_exists(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        _wait_for_pid_exit(pid, timeout_s=2.0)


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f'"{pid}"' in completed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_pid_exit(pid: int, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while _pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.1)


def _process_command_line(pid: int) -> str:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$p = Get-CimInstance Win32_Process -Filter \"ProcessId = "
                    f"{int(pid)}\" -ErrorAction SilentlyContinue; "
                    "if ($null -ne $p) { [Console]::Out.Write($p.CommandLine) }"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip()
    path = Path(f"/proc/{pid}/cmdline")
    if not path.is_file():
        return ""
    return path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")


def _scorer_sanity_report(
    *,
    target_dir: Path,
    repeat_dir: Path,
    tiny_dir: Path,
    views: list[dict[str, Any]],
    repeated_result: dict[str, Any],
    tiny_result: dict[str, Any],
) -> dict[str, Any]:
    repeat_python = score_cross_engine_views_v3(reference_dir=target_dir, candidate_dir=repeat_dir, views=views)
    tiny_python = score_cross_engine_views_v3(reference_dir=target_dir, candidate_dir=tiny_dir, views=views)
    repeat_browser = _browser_fit_score(repeated_result)
    tiny_browser = _browser_fit_score(tiny_result)
    passed = bool(
        repeat_browser is not None
        and repeat_browser >= 0.999
        and tiny_browser is not None
        and tiny_browser >= 0.995
        and repeat_python is not None
        and repeat_python.get("score", 0.0) >= 0.999
        and tiny_python is not None
        and tiny_python.get("score", 0.0) >= 0.995
    )
    return {
        "contract": "shared_material_scorer_sanity_v1",
        "passed": passed,
        "same_params_independent_browser_score": repeat_browser,
        "tiny_perturbation_browser_score": tiny_browser,
        "same_params_independent_python": repeat_python,
        "tiny_perturbation_python": tiny_python,
        "target_directory_compared_to_itself": False,
    }


def _timing_report(
    path: Path,
    speed_gate_ms: float,
    *,
    stability_warmup_iterations: int = 0,
) -> dict[str, Any]:
    payload = _read_json(path)
    rows = payload if isinstance(payload, list) else payload.get("iterations", [])
    values = [
        float(row["timing"]["iteration_total_ms"])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("timing"), dict)
        and isinstance(row["timing"].get("iteration_total_ms"), (int, float))
        and row.get("iteration", 0) != 0
    ]
    if not values:
        return {"count": 0, "gate_ms": speed_gate_ms, "gate_passed": False}
    warmup_count = min(max(int(stability_warmup_iterations), 0), max(len(values) - 1, 0))
    stable_values = values[warmup_count:]
    ordered = sorted(stable_values)
    return {
        "count": len(values),
        "stable_count": len(stable_values),
        "stability_warmup_iterations_excluded": warmup_count,
        "all_iteration_mean_ms": statistics.fmean(values),
        "mean_ms": statistics.fmean(stable_values),
        "p50_ms": statistics.median(stable_values),
        "p95_ms": ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "gate_ms": speed_gate_ms,
        "gate_passed": statistics.fmean(stable_values) <= speed_gate_ms,
        "scope": (
            "isolated stable decision iteration_total_ms excluding the initial "
            "context render and configured scorer/runtime warmup"
        ),
    }


def _asset_contract(
    asset: MaterialAssetSpec,
    profile_path: Path,
    target_patch: dict[str, Any],
    material_coordinates: list[Any],
    scene_coordinates: list[Any],
) -> dict[str, Any]:
    return {
        "contract": "shared_material_asset_adapter_v1",
        "passed": len(material_coordinates) == 40 and len(scene_coordinates) == 6,
        "asset": asset.manifest(),
        "generated_profile": str(profile_path),
        "target_material_sha256": _sha256(asset.target_material_path),
        "target_enabled_defines": target_patch["defines"]["enabled"],
        "material_coordinate_count": len(material_coordinates),
        "scene_coordinate_count": len(scene_coordinates),
        "search_space": structured_material_space_manifest(lmat_io.extract_params(lmat_io.load_lmat(asset.target_material_path))),
    }


def _discrete_state_report(
    *,
    target_params: dict[str, Any],
    start_params: dict[str, Any],
    target_patch: dict[str, Any],
    start_patch: dict[str, Any],
) -> dict[str, Any]:
    searchable = set(STRUCTURED_MATERIAL_PARAM_NAMES)
    locked_names = sorted((set(target_params) | set(start_params)) - searchable)
    differences = [
        {
            "name": name,
            "target": target_params.get(name),
            "start": start_params.get(name),
        }
        for name in locked_names
        if target_params.get(name) != start_params.get(name)
    ]
    target_defines = copy.deepcopy(target_patch.get("defines", {}))
    start_defines = copy.deepcopy(start_patch.get("defines", {}))
    defines_match = target_defines == start_defines
    scene_differences = [
        name
        for name in STRUCTURED_SCENE_PARAM_NAMES
        if target_params.get(name) != start_params.get(name)
    ]
    return {
        "contract": "shared_material_discrete_state_fixed_v1",
        "passed": defines_match and not differences and not scene_differences,
        "defines_match": defines_match,
        "target_defines": target_defines,
        "start_defines": start_defines,
        "locked_param_count": len(locked_names),
        "locked_param_differences": differences,
        "scene_coordinate_differences": scene_differences,
        "searchable_material_param_names": list(STRUCTURED_MATERIAL_PARAM_NAMES),
    }


def _optimizer_boundary_report(config: dict[str, Any], *, private_dir: Path) -> dict[str, Any]:
    forbidden = (str(private_dir.resolve()).lower(), "target_params.json", "human_adjusted", "teacher")
    hits: list[dict[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        else:
            text = str(value).lower()
            for token in forbidden:
                if token in text:
                    hits.append({"path": path, "token": token, "value": str(value)})

    visit(config, "")
    return {
        "contract": "optimizer_sees_start_params_target_pngs_and_online_feedback_only",
        "passed": not hits,
        "hits": hits,
    }


def _force_white_background(profile_path: Path) -> None:
    profile = _read_json(profile_path)
    runtime = profile.setdefault("runtime", {})
    runtime["background_color"] = [255, 255, 255, 255]
    capture = profile.setdefault("capture_defaults", {})
    capture["visual_background_color"] = [255, 255, 255, 255]
    capture["settle_frames"] = 0
    capture["animation_freeze_settle_frames"] = 0
    _write_json(profile_path, profile)


def _write_optimizer_profile(
    source: Path,
    output: Path,
    *,
    width: int,
    height: int,
) -> Path:
    profile = _read_json(source)
    profile["width"] = max(int(width), 64)
    profile["height"] = max(int(height), 64)
    profile["online_score_surrogate"] = {
        "enabled": True,
        "role": "proposal_ranking_only",
        "final_artifacts_use_source_profile": True,
    }
    _write_json(output, profile)
    return output


def _profile_resolution(profile_path: Path) -> list[int]:
    profile = _read_json(profile_path)
    return [int(profile.get("width", 0)), int(profile.get("height", 0))]


def _profile_views(
    profile_path: Path,
    *,
    expected_count: int | None = None,
) -> list[dict[str, Any]]:
    profile = _read_json(profile_path)
    views = profile.get("capture_defaults", {}).get("views")
    if not isinstance(views, list) or not views:
        raise ValueError(f"capture profile has no views: {profile_path}")
    if expected_count is not None and len(views) != int(expected_count):
        raise ValueError(
            f"expected exactly {int(expected_count)} capture views: {profile_path}"
        )
    return copy.deepcopy(views)


def _reference_images(directory: Path, views: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"view_id": str(view["view_id"]), "path": str(directory / str(view["file_name"]))}
        for view in views
    ]


def _browser_fit_score(result: dict[str, Any]) -> float | None:
    score = result.get("browser_score", {}).get("fit_score")
    return float(score) if isinstance(score, (int, float)) else None


def _view_count(directory: Path, views: list[dict[str, Any]]) -> int:
    return sum((directory / str(view["file_name"])).is_file() for view in views)


def _write_contact_sheet(
    *,
    views: list[dict[str, Any]],
    columns: tuple[tuple[str, Path], ...],
    output_path: Path,
) -> Path:
    tile_width, tile_height, label_height = 360, 280, 28
    sheet = Image.new(
        "RGB",
        (tile_width * len(columns), label_height + len(views) * (tile_height + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for column_index, (label, directory) in enumerate(columns):
        draw.text((column_index * tile_width + 8, 6), label, fill="black")
        for row_index, view in enumerate(views):
            path = directory / str(view["file_name"])
            with Image.open(path) as source:
                image = source.convert("RGBA")
                white = Image.new("RGBA", image.size, "white")
                white.alpha_composite(image)
                rendered = white.convert("RGB")
            rendered.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
            y = label_height + row_index * (tile_height + label_height)
            x = column_index * tile_width + (tile_width - rendered.width) // 2
            sheet.paste(rendered, (x, y + (tile_height - rendered.height) // 2))
            draw.text((column_index * tile_width + 8, y + tile_height + 5), str(view["view_id"]), fill="black")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
