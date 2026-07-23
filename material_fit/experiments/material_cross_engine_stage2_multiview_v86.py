"""Run one shared V86 optimizer against any non-empty set of external PNG views."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.assets.material_stage1 import MaterialStage1AssetSpec
from material_fit.assets.stage2_unity_references import resolve_stage2_unity_references
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.material_cross_engine_stage2_multiview_ablation import (
    _copy_unity_targets,
    _evaluation_payload,
    _select_views,
    _validate_frozen_camera,
    _write_variant_profile,
    _write_json,
)
from material_fit.experiments.stage1_fit_config import _build_fit_config
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V86,
    MAX_OPTIMIZER_ITERATIONS,
    _resolve_v86_initial_score_route,
    joint_profile_policy,
)
from material_fit.experiments.stage1_reporting import _write_optimizer_profile
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    find_candidate_for_patch,
    split_discrete_candidate,
    write_candidate_lmat_with_discrete_state,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.cross_engine_score import score_cross_engine_views_v3


ASSET_ID = "holiday_1613"
OPTIMIZER_ID = "material_discrete_joint"
FINAL_RERANK_COUNT = 24


@dataclass(frozen=True)
class ExternalObservationSet:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    views: tuple[dict[str, Any], ...]


def load_external_observations(path: Path) -> ExternalObservationSet:
    """Load any positive number of yaw-labelled PNG observations.

    The manifest controls observations only.  It cannot provide material,
    shader, camera, optimizer, or parameter hints.
    """

    manifest_path = path.expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_observations = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ValueError("observation manifest must contain a non-empty observations list")

    views: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_observations):
        if not isinstance(raw, dict):
            raise ValueError(f"observation {index} must be an object")
        image_value = raw.get("image_path")
        if not isinstance(image_value, str) or not image_value.strip():
            raise ValueError(f"observation {index} has no image_path")
        image_path = Path(image_value).expanduser()
        if not image_path.is_absolute():
            image_path = manifest_path.parent / image_path
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"missing observation image: {image_path}")

        try:
            yaw = float(raw["yaw"])
            pitch = float(raw.get("pitch", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"observation {index} has invalid yaw/pitch") from exc
        if not math.isfinite(yaw) or not math.isfinite(pitch):
            raise ValueError(f"observation {index} yaw/pitch must be finite")
        view_id = str(raw.get("view_id") or f"obs_{index:04d}").strip()
        if not view_id or view_id in seen_ids:
            raise ValueError(f"observation view_id must be unique: {view_id!r}")
        seen_ids.add(view_id)
        views.append(
            {
                "index": index,
                "view_id": view_id,
                "yaw": yaw,
                "pitch": pitch,
                "capture_yaw": float(raw.get("capture_yaw", yaw)),
                "reference_file_name": str(image_path),
                "candidate_file_name": f"laya_observation_{index:04d}.png",
                "file_name": f"laya_observation_{index:04d}.png",
            }
        )

    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return ExternalObservationSet(
        root=manifest_path.parent,
        manifest_path=manifest_path,
        manifest_sha256=digest,
        views=tuple(views),
    )


def run_v86_multiview(
    *,
    repo_root: Path,
    run_dir: Path,
    iterations: int = MAX_OPTIMIZER_ITERATIONS,
    target_score: float = 0.995,
    max_runtime_sec: float = 1800.0,
    node_modules: Path | None = None,
    final_rerank_count: int = FINAL_RERANK_COUNT,
    view_ids: tuple[str, ...] | None = None,
    start_material_path: Path | None = None,
    observation_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Fit any available number of views through the exact same V86 path.

    ``view_ids=None`` consumes every supplied reference.  Passing one, eight,
    or any intermediate subset changes only the observations aggregated by the
    scorer; it does not select a view-count-specific optimizer or policy.
    """
    root = repo_root.resolve()
    output = run_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    base = resolve_material_asset(root, ASSET_ID)
    _validate_frozen_camera(base.profile)
    selected_start_material_path = (
        start_material_path.expanduser().resolve()
        if start_material_path is not None
        else base.target_material_path
    )
    if not selected_start_material_path.is_file():
        raise FileNotFoundError(f"missing start material: {selected_start_material_path}")
    references = (
        load_external_observations(observation_manifest_path)
        if observation_manifest_path is not None
        else resolve_stage2_unity_references(root, ASSET_ID)
    )
    target_source = (
        "external_png_manifest"
        if observation_manifest_path is not None
        else "tracked_unity_png_only"
    )
    all_profile_path = base.write_profile(output / "inputs" / "asset_profile_all_views.json")
    phase05._force_white_background(all_profile_path)
    if observation_manifest_path is None:
        all_views = phase05._profile_views(all_profile_path)
    else:
        all_views = [
            {
                "view_id": str(view["view_id"]),
                "yaw": float(view["yaw"]),
                "pitch": float(view["pitch"]),
                "file_name": str(view["file_name"]),
            }
            for view in references.views
        ]
    views = (
        copy.deepcopy(all_views)
        if view_ids is None
        else _select_views(all_views, tuple(view_ids))
    )
    all_profile = json.loads(all_profile_path.read_text(encoding="utf-8"))
    full_profile_path = _write_variant_profile(
        all_profile_path,
        output / "inputs" / "asset_profile.json",
        views,
        width=int(all_profile["width"]),
        height=int(all_profile["height"]),
    )
    stage_asset = MaterialStage1AssetSpec(
        asset_id=base.asset_id,
        project_root=base.project_root,
        scene_path=base.scene_path,
        shader_path=base.shader_path,
        start_material_path=selected_start_material_path,
        target_material_path=base.target_material_path,
        profile=json.loads(full_profile_path.read_text(encoding="utf-8")),
    )
    target_dir = output / "target_render"
    _copy_unity_targets(references, views, target_dir)

    start_material_path = stage_asset.start_material_path
    start_params = lmat_io.extract_params(lmat_io.load_lmat(start_material_path))
    missing = [name for name in STRUCTURED_MATERIAL_PARAM_NAMES if name not in start_params]
    if missing:
        raise ValueError(f"1613 start material is missing shared coordinates: {missing}")
    start_patch = material_patch_from_lmat(start_material_path)
    candidates = build_legal_discrete_candidates(start_patch)
    start_candidate = find_candidate_for_patch(candidates, start_patch)
    start_render_params = attach_discrete_candidate(start_params, start_candidate)
    _write_json(output / "inputs" / "start_params.json", start_params)
    _write_json(
        output / "stage2_discrete_search_space_report.json",
        {
            "contract": "material_fit_stage2_target_independent_discrete_space_v1",
            "candidate_count": len(candidates),
            "start_candidate": start_candidate,
            "candidates": candidates,
            "target_material_visible": False,
            "target_discrete_state_visible": False,
        },
    )

    initial_driver = phase05._build_artifact_capture_driver(
        profile_path=full_profile_path,
        output_root=output / "initial_score_router" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=phase05.VALIDATION_SCORE_METRIC,
    )
    try:
        initial_result = phase05._capture_artifact_set(
            driver=initial_driver,
            artifact_dir=output / "initial_score_router" / "start_render",
            params=start_render_params,
            views=views,
            iteration=0,
        )
    finally:
        initial_driver.close()
    initial_evaluation = _evaluation_payload(
        result=initial_result,
        target_dir=target_dir,
        candidate_dir=output / "initial_score_router" / "start_render",
        views=views,
    )
    initial_score = float(initial_evaluation["python_cross_engine_v3"]["score"])

    parent_policy = joint_profile_policy(JOINT_PROFILE_V86)
    (
        selected_profile,
        selected_policy,
        selected_iterations,
        score_metric,
        score_width,
        score_height,
        residual_grid_size,
        residual_sketch_size,
        route_report,
    ) = _resolve_v86_initial_score_route(
        policy=parent_policy,
        initial_score=initial_score,
        asset_profile=base.profile,
        requested_iterations=int(iterations),
        score_metric=str(parent_policy["optimization_score_metric"]),
        score_width=int(parent_policy["score_width"]),
        score_height=int(parent_policy["score_height"]),
        residual_grid_size=int(parent_policy["residual_grid_size"]),
        residual_sketch_size=int(parent_policy["residual_sketch_size"]),
    )
    route_report.update(
        {
            "target_source": target_source,
            "target_material_visible": False,
            "target_params_visible": False,
            "scored_view_ids": [str(view["view_id"]) for view in views],
        }
    )
    _write_json(
        output / "initial_score_router" / "initial_score_route_report.json",
        route_report,
    )

    optimizer_profile_path = _write_optimizer_profile(
        full_profile_path,
        output / "inputs" / "optimizer_asset_profile.json",
        width=score_width,
        height=score_height,
    )
    optimizer_target_dir = output / "optimizer_target_render"
    _copy_unity_targets(
        references,
        views,
        optimizer_target_dir,
        output_size=(score_width, score_height),
    )
    _run_same_parameter_sanity(
        run_dir=output,
        profile_path=optimizer_profile_path,
        views=views,
        start_params=start_render_params,
        start_patch=start_patch,
        node_modules=node_modules,
    )

    config = _build_fit_config(
        asset=stage_asset,
        profile_path=optimizer_profile_path,
        run_dir=output,
        start_material_path=start_material_path,
        target_dir=optimizer_target_dir,
        optimizer_start_patch=start_patch,
        discrete_candidates=candidates,
        start_candidate=start_candidate,
        target_score=target_score,
        optimizer=OPTIMIZER_ID,
        warmup_iterations=1000,
        block_iterations=400,
        block_population_size=16,
        refine_iterations=800,
        node_modules=node_modules,
        views=views,
        joint_profile=selected_profile,
        joint_policy_override=selected_policy,
        optimization_score_metric=score_metric,
        browser_score_width=score_width,
        browser_score_height=score_height,
        residual_grid_size=residual_grid_size,
        residual_sketch_size=residual_sketch_size,
    )
    config["stage1_initial_score_router"] = copy.deepcopy(route_report)
    config["stage2_optimizer_contract"] = {
        "phase": "cross_engine_stage2_png_set",
        "algorithm": "shared_v86_material_discrete_joint",
        "view_count": len(views),
        "view_ids": [str(view["view_id"]) for view in views],
        "target_source": target_source,
        "target_material_visible": False,
        "target_params_visible": False,
        "target_discrete_state_visible": False,
        "asset_id_visible_to_router_or_optimizer": False,
        "camera_searchable": False,
        "continuous_space": "40_material_coordinates_plus_6_scene_coordinates",
        "scene_coordinates_frozen_before_final_material_refine": True,
        "legal_hard_state_count": len(candidates),
        "selected_child_profile": selected_profile,
        "proposal_budget": int(selected_iterations),
    }
    config_path = output / "fit_config.json"
    _write_json(config_path, config)

    fit_started = time.perf_counter()
    returncode = phase05._run_fit_owned(
        repo_root=root,
        run_dir=output,
        config_path=config_path,
        iterations=selected_iterations,
        target_score=target_score,
        max_runtime_sec=max_runtime_sec,
        optimizer=OPTIMIZER_ID,
    )
    fit_elapsed_s = time.perf_counter() - fit_started
    if returncode != 0:
        raise RuntimeError(f"V86 Stage 2 fit exited with {returncode}; see {output / 'logs'}")

    rerank = _rerank_archive(
        run_dir=output,
        profile_path=full_profile_path,
        target_dir=target_dir,
        views=views,
        start_patch=start_patch,
        node_modules=node_modules,
        limit=max(1, int(final_rerank_count)),
        baseline_params=start_render_params,
    )
    best_render_params = rerank["best_params"]
    _, best_candidate = split_discrete_candidate(best_render_params)
    if best_candidate is None:
        raise RuntimeError("V86 rerank winner has no discrete candidate")
    best_params_path = output / "best_params_full_resolution_reranked.json"
    _write_json(best_params_path, best_render_params)
    write_candidate_lmat_with_discrete_state(
        start_material_path,
        output / "best_material.lmat",
        best_render_params,
    )
    final_driver = phase05._build_artifact_capture_driver(
        profile_path=full_profile_path,
        output_root=output / "final_capture" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=phase05.VALIDATION_SCORE_METRIC,
    )
    try:
        best_result = phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=output / "best_render",
            params=best_render_params,
            views=views,
            iteration=0,
        )
    finally:
        final_driver.close()
    best_evaluation = _evaluation_payload(
        result=best_result,
        target_dir=target_dir,
        candidate_dir=output / "best_render",
        views=views,
    )
    best_score = float(best_evaluation["python_cross_engine_v3"]["score"])
    timing = phase05._timing_report(
        output / "output" / "auto_adjust" / "iteration_series.json",
        500.0,
    )
    cleanup = phase05._cleanup_recorded_runtime(output)
    contact_sheet = phase05._write_contact_sheet(
        views=views,
        columns=(
            ("Unity target", target_dir),
            ("Original Laya", output / "initial_score_router" / "start_render"),
            ("V86 best", output / "best_render"),
        ),
        output_path=output / "unity_start_v86_best.png",
    )
    report = {
        "contract": "material_fit_stage2_external_png_v86_v1",
        "accepted": bool(
            best_score >= 0.98
            and cleanup["remaining_owned_pid_count"] == 0
            and timing["gate_passed"]
        ),
        "asset_id": base.asset_id,
        "view_count": len(views),
        "view_ids": [str(view["view_id"]) for view in views],
        "run_dir": str(output),
        "optimizer": OPTIMIZER_ID,
        "parent_profile": JOINT_PROFILE_V86,
        "selected_profile": selected_profile,
        "iterations_requested": int(iterations),
        "iterations_run": int(selected_iterations),
        "fit_elapsed_s": fit_elapsed_s,
        "initial_evaluation": initial_evaluation,
        "best_evaluation": best_evaluation,
        "initial_score": initial_score,
        "best_score": best_score,
        "score_gain": best_score - initial_score,
        "acceptance_score": 0.98,
        "rerank": {key: value for key, value in rerank.items() if key != "best_params"},
        "search_contract": {
            "target_png_only": True,
            "same_algorithm_for_any_positive_view_count": True,
            "view_count_changes_observations_only": True,
            "asset_name_visible_to_optimizer": False,
            "material_coordinates": list(STRUCTURED_MATERIAL_PARAM_NAMES),
            "scene_coordinates": list(STRUCTURED_SCENE_PARAM_NAMES),
            "legal_hard_state_count": len(candidates),
            "camera_frozen": True,
            "observation_manifest_path": (
                str(references.manifest_path)
                if isinstance(references, ExternalObservationSet)
                else None
            ),
            "observation_manifest_sha256": (
                references.manifest_sha256
                if isinstance(references, ExternalObservationSet)
                else None
            ),
        },
        "timing": timing,
        "process_cleanup": cleanup,
        "best_params_path": str(best_params_path),
        "best_material_path": str(output / "best_material.lmat"),
        "best_render_dir": str(output / "best_render"),
        "contact_sheet": str(contact_sheet),
    }
    _write_json(output / "stage2_v86_report.json", report)
    return report


def _run_same_parameter_sanity(
    *,
    run_dir: Path,
    profile_path: Path,
    views: list[dict[str, Any]],
    start_params: dict[str, Any],
    start_patch: dict[str, Any],
    node_modules: Path | None,
) -> None:
    reference_dir = run_dir / "scorer_sanity" / "start_reference"
    reference_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=run_dir / "scorer_sanity" / "reference_runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=reference_driver,
            artifact_dir=reference_dir,
            params=start_params,
            views=views,
            iteration=0,
        )
    finally:
        reference_driver.close()
    repeat_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=run_dir / "scorer_sanity" / "repeat_runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=reference_dir,
        node_modules=node_modules,
        score_metric=phase05.VALIDATION_SCORE_METRIC,
    )
    try:
        repeat_result = phase05._capture_artifact_set(
            driver=repeat_driver,
            artifact_dir=run_dir / "scorer_sanity" / "start_repeat",
            params=start_params,
            views=views,
            iteration=0,
        )
    finally:
        repeat_driver.close()
    score = phase05._browser_fit_score(repeat_result)
    _write_json(
        run_dir / "scorer_sanity" / "same_parameter_report.json",
        {"score": score, "passed": score is not None and score >= 0.995},
    )
    if score is None or score < 0.995:
        raise RuntimeError(f"same-parameter scorer sanity failed: {score}")


def _rerank_archive(
    *,
    run_dir: Path,
    profile_path: Path,
    target_dir: Path,
    views: list[dict[str, Any]],
    start_patch: dict[str, Any],
    node_modules: Path | None,
    limit: int,
    baseline_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    series_path = run_dir / "output" / "auto_adjust" / "iteration_series.json"
    payload = json.loads(series_path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("iterations", [])
    ranked = sorted(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("fit_score_before"), (int, float))
            and isinstance(row.get("scored_params"), dict)
        ),
        key=lambda row: float(row["fit_score_before"]),
        reverse=True,
    )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    if baseline_params is not None:
        key = json.dumps(baseline_params, sort_keys=True, separators=(",", ":"))
        seen.add(key)
        unique.append(
            {
                "iteration": -1,
                "fit_score_before": None,
                "scored_params": copy.deepcopy(baseline_params),
            }
        )
    for row in ranked:
        params = row["scored_params"]
        key = json.dumps(params, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
        if len(unique) >= limit:
            break
    if not unique:
        raise RuntimeError("optimizer archive contains no rerankable candidates")

    driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=run_dir / "full_resolution_rerank" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=phase05.VALIDATION_SCORE_METRIC,
    )
    records: list[dict[str, Any]] = []
    try:
        for index, row in enumerate(unique):
            result = driver.render_candidate(index, row["scored_params"])
            score = phase05._browser_fit_score(result)
            if score is None:
                continue
            candidate_dir = (
                run_dir
                / "full_resolution_rerank"
                / "runtime"
                / "iterations"
                / f"iter_{index:04d}"
                / "render"
            )
            independent = score_cross_engine_views_v3(
                reference_dir=target_dir,
                candidate_dir=candidate_dir,
                views=views,
            )
            if not isinstance(independent, dict) or independent.get("status") != "ok":
                continue
            records.append(
                {
                    "rank": index,
                    "source_iteration": int(row["iteration"]),
                    "online_fit_score": (
                        float(row["fit_score_before"])
                        if row["fit_score_before"] is not None
                        else None
                    ),
                    "full_resolution_browser_v4_score": float(score),
                    "independent_python_cross_engine_v3_score": float(
                        independent["score"]
                    ),
                    "params": copy.deepcopy(row["scored_params"]),
                }
            )
    finally:
        driver.close()
    if not records:
        raise RuntimeError("full-resolution rerank produced no valid scores")
    records.sort(
        key=lambda row: (
            row["independent_python_cross_engine_v3_score"],
            row["full_resolution_browser_v4_score"],
        ),
        reverse=True,
    )
    _write_json(run_dir / "full_resolution_rerank" / "rerank_report.json", records)
    return {
        "candidate_count": len(records),
        "winner_source_iteration": records[0]["source_iteration"],
        "winner_online_fit_score": records[0]["online_fit_score"],
        "winner_full_resolution_browser_v4_score": records[0][
            "full_resolution_browser_v4_score"
        ],
        "winner_independent_python_cross_engine_v3_score": records[0][
            "independent_python_cross_engine_v3_score"
        ],
        "best_params": records[0]["params"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=MAX_OPTIMIZER_ITERATIONS)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--max-runtime-sec", type=float, default=1800.0)
    parser.add_argument("--final-rerank-count", type=int, default=FINAL_RERANK_COUNT)
    parser.add_argument(
        "--view-ids",
        default="",
        help="Comma-separated view ids; empty consumes every available reference",
    )
    parser.add_argument("--start-material", default="")
    parser.add_argument(
        "--observation-manifest",
        default="",
        help=(
            "JSON with a non-empty observations list; each item contains "
            "image_path, yaw, optional pitch, and optional view_id"
        ),
    )
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else repo_root / "artifacts"
    )
    run_name = args.run_name or (
        f"stage2_1613_v86_png_set_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = output_root / run_name
    try:
        report = run_v86_multiview(
            repo_root=repo_root,
            run_dir=run_dir,
            iterations=args.iterations,
            target_score=args.target_score,
            max_runtime_sec=args.max_runtime_sec,
            node_modules=(
                Path(args.node_modules).expanduser().resolve()
                if args.node_modules
                else None
            ),
            final_rerank_count=args.final_rerank_count,
            view_ids=(
                tuple(part.strip() for part in args.view_ids.split(",") if part.strip())
                if args.view_ids.strip()
                else None
            ),
            start_material_path=(
                Path(args.start_material) if args.start_material else None
            ),
            observation_manifest_path=(
                Path(args.observation_manifest)
                if args.observation_manifest
                else None
            ),
        )
    finally:
        if run_dir.exists():
            phase05._cleanup_recorded_runtime(run_dir)
    print(
        json.dumps(
            {
                "accepted": report["accepted"],
                "run_dir": report["run_dir"],
                "initial_score": report["initial_score"],
                "best_score": report["best_score"],
                "contact_sheet": report["contact_sheet"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ExternalObservationSet", "load_external_observations", "run_v86_multiview"]
