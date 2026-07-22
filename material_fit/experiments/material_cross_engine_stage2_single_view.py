"""Run the full V86 material fit against one tracked Unity Stage 2 PNG."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from material_fit.assets.stage2_sampling import resolve_stage2_sampling
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.stage1_fit_config import _build_fit_config
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V86,
    MAX_OPTIMIZER_ITERATIONS,
    _resolve_v86_initial_score_route,
    joint_profile_policy,
)
from material_fit.experiments.single_view_v86_policy import (
    adapt_v86_policy_for_material_only,
)
from material_fit.experiments.single_view_runtime import (
    DEFAULT_SINGLE_VIEW_SCORE_HEIGHT,
    DEFAULT_SINGLE_VIEW_SCORE_WIDTH,
)
from material_fit.experiments.stage2_archive import (
    FINAL_REGISTERED_PATTERN_MAX_PROPOSALS,
    _refine_with_registered_browser_score,
    _rerank_optimizer_archive,
)
from material_fit.experiments.stage2_evidence import (
    Stage2FinalizationContext,
    finalize_stage2_single_view,
)
from material_fit.experiments.stage2_io import (
    iteration_count as _iteration_count,
    read_json as _read_json,
    write_json as _write_json,
)
from material_fit.experiments.stage2_scoring import (
    _run_acceptance_scorer_sanity,
)
from material_fit.experiments.stage1_reporting import _write_optimizer_profile
from material_fit.laya import lmat_io
from material_fit.laya.render_driver import RenderDriver
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    compress_observationally_equivalent_candidates,
    find_candidate_for_patch,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.dists_score import (
    DEFAULT_DISTS_DEVICE,
    DEFAULT_DISTS_IMAGE_SIZE,
    DEFAULT_DISTS_TORCH_THREADS,
    DISTS_ALIGNED_RGB_METRIC,
    ForegroundDISTSAlignedRGBScorer,
)
from material_fit.vision.stage2_confidence import (
    build_frozen_confidence_mask,
)
from material_fit.vision.stage2_registration import (
    apply_frozen_stage2_registration,
    reference_in_source_frame,
)


DEFAULT_VIEW_ID = "v000_yaw0_pitch0"
OPTIMIZER_ID = "material_discrete_joint"
JOINT_PROFILE = JOINT_PROFILE_V86
DEFAULT_ITERATIONS = MAX_OPTIMIZER_ITERATIONS
ROBUST_SCORE_METRIC = DISTS_ALIGNED_RGB_METRIC
ONLINE_SCORE_WIDTH = DEFAULT_SINGLE_VIEW_SCORE_WIDTH
ONLINE_SCORE_HEIGHT = DEFAULT_SINGLE_VIEW_SCORE_HEIGHT
ONLINE_DISTS_IMAGE_SIZE = DEFAULT_DISTS_IMAGE_SIZE
ONLINE_DISTS_DEVICE = DEFAULT_DISTS_DEVICE
ONLINE_DISTS_TORCH_THREADS = DEFAULT_DISTS_TORCH_THREADS
MAXIMUM_ACCEPTANCE_DISTANCE_RATIO = 0.85


def _adapt_joint_policy_for_single_view_material_only(
    policy: dict[str, Any],
    *,
    initial_score: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return adapt_v86_policy_for_material_only(
        policy,
        optimization_score_metric=ROBUST_SCORE_METRIC,
        scene_searchable=True,
        initial_score=initial_score,
    )


def run_stage2_single_view(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str = "turtle",
    view_id: str = DEFAULT_VIEW_ID,
    iterations: int = DEFAULT_ITERATIONS,
    target_score: float = 0.995,
    max_runtime_sec: float = 1200.0,
    node_modules: Path | None = None,
) -> dict[str, Any]:
    """Run V86 unchanged except that scoring uses one requested Unity view."""

    root = repo_root.resolve()
    output = run_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = resolve_stage2_sampling(
        root,
        asset_id,
        material_variant="start",
        lighting_variant="baseline",
    )
    reference_view = _select_reference_view(spec.references.views, view_id)
    optimizer_view = {
        "view_id": reference_view["view_id"],
        "yaw": float(reference_view["yaw"]),
        "pitch": float(reference_view["pitch"]),
        "file_name": str(reference_view["candidate_file_name"]),
    }
    registration = _single_view_registration(
        spec.calibration["registration"],
        view_id,
    )

    profile = copy.deepcopy(spec.profile)
    profile["capture_defaults"]["views"] = [copy.deepcopy(optimizer_view)]
    profile_path = output / "inputs" / "asset_profile.json"
    _write_json(profile_path, profile)
    optimizer_profile_path = _write_optimizer_profile(
        profile_path,
        output / "inputs" / "optimizer_asset_profile.json",
        width=ONLINE_SCORE_WIDTH,
        height=ONLINE_SCORE_HEIGHT,
    )

    target_dir = output / "target_render"
    target_dir.mkdir(parents=True, exist_ok=True)
    source_target = spec.references.root / str(reference_view["reference_file_name"])
    target_path = target_dir / str(optimizer_view["file_name"])
    shutil.copy2(source_target, target_path)
    transform = registration["transforms"][0]
    online_target_dir = output / "inputs" / "online_target_raw_frame"
    online_target_dir.mkdir(parents=True, exist_ok=True)
    online_target_path = online_target_dir / str(optimizer_view["file_name"])
    with Image.open(target_path) as reference:
        online_reference = reference_in_source_frame(
            reference,
            output_size=tuple(int(value) for value in registration["output_size"]),
            scale=float(transform["scale"]),
            dx=float(transform["dx"]),
            dy=float(transform["dy"]),
        )
    online_reference.save(online_target_path)
    _write_json(
        output / "inputs" / "online_target_raw_frame.json",
        {
            "contract": "material_fit_stage2_online_target_raw_frame_v1",
            "source_target": str(target_path),
            "output_target": str(online_target_path),
            "view_id": view_id,
            "inverse_of_frozen_registration": {
                "scale": float(transform["scale"]),
                "dx": float(transform["dx"]),
                "dy": float(transform["dy"]),
            },
            "target_material_or_params_visible": False,
        },
    )

    start_material = spec.material_path
    start_payload = lmat_io.load_lmat(start_material)
    start_params = lmat_io.extract_params(start_payload)
    missing = [name for name in STRUCTURED_MATERIAL_PARAM_NAMES if name not in start_params]
    if missing:
        raise ValueError(f"start material is missing structured coordinates: {missing}")
    start_patch = material_patch_from_lmat(start_material)
    _write_json(output / "inputs" / "start_params.json", start_params)
    discrete_candidates = build_legal_discrete_candidates(start_patch)
    start_candidate = find_candidate_for_patch(discrete_candidates, start_patch)
    _write_json(
        output / "stage2_discrete_search_space_report.json",
        {
            "contract": "material_fit_stage2_target_independent_discrete_space_v1",
            "candidate_count": len(discrete_candidates),
            "start_candidate": start_candidate,
            "candidates": discrete_candidates,
            "target_material_visible": False,
            "target_discrete_state_visible": False,
        },
    )

    router_raw_dir = output / "initial_score_router" / "raw_start_render"
    router_start_dir = output / "initial_score_router" / "start_render"
    router_driver = _build_single_view_artifact_driver(
        profile_path=profile_path,
        output_root=output / "initial_score_router" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        node_modules=(node_modules or root / "node_modules").resolve(),
    )
    try:
        phase05._capture_artifact_set(
            driver=router_driver,
            artifact_dir=router_raw_dir,
            params=attach_discrete_candidate(start_params, start_candidate),
            views=[optimizer_view],
            iteration=0,
        )
    finally:
        router_driver.close()
    apply_frozen_stage2_registration(
        raw_dir=router_raw_dir,
        output_dir=router_start_dir,
        views=[copy.deepcopy(reference_view)],
        registration=registration,
    )
    initial_score_payload = ForegroundDISTSAlignedRGBScorer(
        image_size=ONLINE_DISTS_IMAGE_SIZE,
        device=ONLINE_DISTS_DEVICE,
        torch_threads=ONLINE_DISTS_TORCH_THREADS,
    ).score_paths(
        target_path,
        router_start_dir / str(optimizer_view["file_name"]),
    ).as_dict()
    initial_score_payload["status"] = "ok"
    initial_score = _aggregate_score(initial_score_payload)
    confidence_mask_path = output / "inputs" / "frozen_confidence_mask.png"
    confidence_report = build_frozen_confidence_mask(
        reference_path=target_path,
        registered_start_path=router_start_dir / str(optimizer_view["file_name"]),
        output_path=confidence_mask_path,
    )
    _write_json(output / "frozen_confidence_mask_report.json", confidence_report)

    parent_policy = joint_profile_policy(JOINT_PROFILE)
    (
        selected_joint_profile,
        selected_joint_policy,
        selected_iterations,
        score_metric,
        resolved_width,
        resolved_height,
        residual_grid_size,
        residual_sketch_size,
        route_report,
    ) = _resolve_v86_initial_score_route(
        policy=parent_policy,
        initial_score=initial_score,
        asset_profile=profile,
        requested_iterations=int(iterations),
        score_metric=str(parent_policy["optimization_score_metric"]),
        score_width=int(parent_policy["score_width"]),
        score_height=int(parent_policy["score_height"]),
        residual_grid_size=int(parent_policy["residual_grid_size"]),
        residual_sketch_size=int(parent_policy["residual_sketch_size"]),
    )
    selected_joint_policy, single_view_policy_report = (
        _adapt_joint_policy_for_single_view_material_only(
            selected_joint_policy,
            initial_score=initial_score,
        )
    )
    inverse_search_score_metric = str(
        single_view_policy_report["initial_optimization_score_metric"]
    )
    route_report.update(
        {
            "target_render_dir": str(target_dir),
            "online_target_raw_frame_dir": str(online_target_dir),
            "start_render_dir": str(router_start_dir),
            "score_payload": initial_score_payload,
            "initial_score_metric": DISTS_ALIGNED_RGB_METRIC,
            "scored_view_ids": [view_id],
            "selected_route_score_metric": score_metric,
            "stage2_optimization_score_metric": inverse_search_score_metric,
            "stage2_acceptance_score_metric": ROBUST_SCORE_METRIC,
            "stage2_online_score_resolution": [ONLINE_SCORE_WIDTH, ONLINE_SCORE_HEIGHT],
            "stage2_online_candidate_registration": False,
            "single_view_policy_adaptation": single_view_policy_report,
        }
    )
    _write_json(
        output / "initial_score_router" / "initial_score_route_report.json",
        route_report,
    )

    optimizer_candidates = discrete_candidates
    equivalence_report: dict[str, Any] = {}
    if selected_joint_policy.get("discrete_observation_equivalence", False):
        optimizer_candidates, equivalence_report = (
            compress_observationally_equivalent_candidates(
                discrete_candidates,
                start_candidate=start_candidate,
                start_patch=start_patch,
            )
        )
        _write_json(
            output / "stage2_discrete_observation_equivalence_report.json",
            equivalence_report,
        )

    config = _build_fit_config(
        asset=spec.asset,
        profile_path=optimizer_profile_path,
        run_dir=output,
        start_material_path=start_material,
        target_dir=online_target_dir,
        optimizer_start_patch=start_patch,
        discrete_candidates=optimizer_candidates,
        discrete_equivalence_report=equivalence_report,
        start_candidate=start_candidate,
        target_score=target_score,
        optimizer=OPTIMIZER_ID,
        warmup_iterations=1000,
        block_iterations=400,
        block_population_size=16,
        refine_iterations=800,
        node_modules=(node_modules or root / "node_modules").resolve(),
        views=[optimizer_view],
        joint_profile=selected_joint_profile,
        joint_policy_override=selected_joint_policy,
        optimization_score_metric=inverse_search_score_metric,
        browser_score_width=ONLINE_SCORE_WIDTH,
        browser_score_height=ONLINE_SCORE_HEIGHT,
        residual_grid_size=residual_grid_size,
        residual_sketch_size=residual_sketch_size,
    )
    config["laya_capture"]["browser_score"].update(
        {
            "perceptual_image_size": ONLINE_DISTS_IMAGE_SIZE,
            "perceptual_device": ONLINE_DISTS_DEVICE,
            "perceptual_torch_threads": ONLINE_DISTS_TORCH_THREADS,
            "perceptual_emit_residual_features": True,
        }
    )
    config["stage1_initial_score_router"] = copy.deepcopy(route_report)
    config["search_param_names"] = [
        *STRUCTURED_MATERIAL_PARAM_NAMES,
        *STRUCTURED_SCENE_PARAM_NAMES,
    ]
    config["search_param_space"] = (
        "structured_material_stage2_single_view_joint_material_scene_46_v1"
    )
    for contract_name in (
        "structured_material_contract",
        "material_jacobian_trust_region_contract",
        "stage1_optimizer_contract",
    ):
        contract = config.get(contract_name)
        if isinstance(contract, dict):
            contract["phase"] = "cross_engine_stage2_single_view"
            contract["material_coordinate_count"] = len(STRUCTURED_MATERIAL_ONLY_COORDINATES)
            contract["scene_coordinate_count"] = len(STRUCTURED_SCENE_PARAM_NAMES)
            contract["scene_coordinates_searchable"] = True
            contract["scene_coordinates_frozen_before_final_material_refine"] = True
            contract["optimization_score_metric"] = inverse_search_score_metric
            contract["acceptance_score_metric"] = ROBUST_SCORE_METRIC
    config["stage2_optimizer_contract"] = {
        "phase": "cross_engine_stage2_single_view",
        "algorithm": "full_v86_material_discrete_joint",
        "joint_profile": JOINT_PROFILE,
        "selected_child_profile": selected_joint_profile,
        "single_view_policy": "inverse_search_then_acceptance_polish_v51",
        "view_ids": [view_id],
        "target_source": "tracked_unity_png_only",
        "target_material_visible": False,
        "target_params_visible": False,
        "target_discrete_state_visible": False,
        "asset_id_visible_to_router_or_optimizer": False,
        "discrete_state": "searched_from_original_start_over_16_legal_states",
        "continuous_space": "40_material_coordinates_plus_6_scene_coordinates",
        "online_score_sampling": {
            "resolution": [ONLINE_SCORE_WIDTH, ONLINE_SCORE_HEIGHT],
            "dists_image_size": ONLINE_DISTS_IMAGE_SIZE,
            "dists_device": ONLINE_DISTS_DEVICE,
            "dists_torch_threads": ONLINE_DISTS_TORCH_THREADS,
            "candidate_registration": False,
            "reference_frame": "inverse_frozen_registration_of_unity_target",
            "reason": (
                "fast shared search in the raw renderer frame without "
                "per-candidate resampling"
            ),
        },
        "full_resolution_tail_sampling": {
            "maximum_proposals": FINAL_REGISTERED_PATTERN_MAX_PROPOSALS,
            "candidate_registration": True,
            "reference_frame": "original_unity_target",
            "role": "final material refinement and evidence selection",
        },
        "scene_coordinates": {
            "searchable": True,
            "frozen_before_final_material_refine": True,
            "names": list(STRUCTURED_SCENE_PARAM_NAMES),
            "initial_source": "original_start_material",
        },
        "confidence_mask_audit": {
            "path": str(confidence_mask_path),
            "frozen_before_optimization": True,
            "erosion_pixels_at_artifact_resolution": confidence_report["erosion_pixels"],
            "reference_coverage": confidence_report["reference_coverage"],
            "used_by_optimizer": False,
        },
        "renderer_environment": "baseline_game_environment",
    }
    browser_score = config["laya_capture"]["browser_score"]
    references = browser_score.get("reference_images")
    if not isinstance(references, list) or len(references) != 1:
        raise RuntimeError("single-view Stage 2 requires exactly one browser reference")
    config_path = output / "fit_config.json"
    _write_json(config_path, config)
    scorer_sanity = _run_acceptance_scorer_sanity(
        run_dir=output,
        capture_config=config["laya_capture"],
        start_params=start_params,
        start_candidate=start_candidate,
    )
    if not scorer_sanity["passed"]:
        raise RuntimeError(f"Stage 2 DISTS scorer sanity failed: {scorer_sanity}")

    total_proposal_budget = int(selected_iterations)
    registered_pattern_budget = 0
    online_proposal_budget = total_proposal_budget
    config["stage2_optimizer_contract"]["proposal_budget"] = {
        "initial_material_score": 1,
        "raw_frame_optimizer_proposals": online_proposal_budget,
        "registered_pattern_proposals": registered_pattern_budget,
        "maximum_unique_scored_materials": 1 + total_proposal_budget,
    }
    _write_json(config_path, config)
    fit_started = time.perf_counter()
    returncode = phase05._run_fit_owned(
        repo_root=root,
        run_dir=output,
        config_path=config_path,
        iterations=online_proposal_budget,
        target_score=float(target_score),
        max_runtime_sec=float(max_runtime_sec),
        optimizer=OPTIMIZER_ID,
    )
    fit_elapsed_s = time.perf_counter() - fit_started
    if returncode != 0:
        raise RuntimeError(f"Stage 2 fit exited with {returncode}; see {output / 'logs'}")

    best_params_path = output / "output" / "auto_adjust" / "best" / "params.json"
    if not best_params_path.is_file():
        raise FileNotFoundError(f"optimizer did not produce best params: {best_params_path}")
    optimizer_best_params = _read_json(best_params_path)
    best_params, acceptance_rerank = _rerank_optimizer_archive(
        output=output,
        profile_path=profile_path,
        target_path=target_path,
        optimizer_view=optimizer_view,
        reference_view=reference_view,
        registration=registration,
        start_patch=start_patch,
        optimizer_best_params=optimizer_best_params,
        node_modules=(node_modules or root / "node_modules").resolve(),
    )
    best_params, registered_pattern = _refine_with_registered_browser_score(
        output=output,
        capture_config=config["laya_capture"],
        full_resolution_profile_path=profile_path,
        target_path=target_path,
        registration=registration,
        initial_params=best_params,
        max_proposals=registered_pattern_budget,
    )
    return finalize_stage2_single_view(Stage2FinalizationContext(
        output=output,
        spec=spec,
        reference_view=reference_view,
        optimizer_view=optimizer_view,
        registration=registration,
        profile_path=profile_path,
        target_dir=target_dir,
        target_path=target_path,
        source_target=source_target,
        start_material=start_material,
        start_params=start_params,
        start_patch=start_patch,
        best_params=best_params,
        acceptance_rerank=acceptance_rerank,
        registered_pattern=registered_pattern,
        iterations=selected_iterations,
        fit_elapsed_s=fit_elapsed_s,
        resolved_width=ONLINE_SCORE_WIDTH,
        resolved_height=ONLINE_SCORE_HEIGHT,
        constraints=config["stage2_optimizer_contract"],
        route_report=route_report,
        start_candidate=start_candidate,
        confidence_mask_path=confidence_mask_path,
        node_modules=(node_modules or root / "node_modules").resolve(),
        optimizer_id=OPTIMIZER_ID,
        joint_profile=JOINT_PROFILE,
        maximum_acceptance_distance_ratio=MAXIMUM_ACCEPTANCE_DISTANCE_RATIO,
    ))


def resume_stage2_single_view(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str = "turtle",
    view_id: str = DEFAULT_VIEW_ID,
    iterations: int = DEFAULT_ITERATIONS,
    node_modules: Path | None = None,
) -> dict[str, Any]:
    """Finish evidence capture for an optimizer run that already has best params."""

    root = repo_root.resolve()
    output = run_dir.resolve()
    spec = resolve_stage2_sampling(root, asset_id, material_variant="start")
    reference_view = _select_reference_view(spec.references.views, view_id)
    optimizer_view = {
        "view_id": reference_view["view_id"],
        "yaw": float(reference_view["yaw"]),
        "pitch": float(reference_view["pitch"]),
        "file_name": str(reference_view["candidate_file_name"]),
    }
    registration = _single_view_registration(spec.calibration["registration"], view_id)
    profile_path = output / "inputs" / "asset_profile.json"
    target_dir = output / "target_render"
    source_target = spec.references.root / str(reference_view["reference_file_name"])
    target_path = target_dir / str(optimizer_view["file_name"])
    start_material = spec.material_path
    start_params = lmat_io.extract_params(lmat_io.load_lmat(start_material))
    start_patch = material_patch_from_lmat(start_material)
    optimizer_best_params = _read_json(
        output / "output" / "auto_adjust" / "best" / "params.json"
    )
    best_params, acceptance_rerank = _rerank_optimizer_archive(
        output=output,
        profile_path=profile_path,
        target_path=target_path,
        optimizer_view=optimizer_view,
        reference_view=reference_view,
        registration=registration,
        start_patch=start_patch,
        optimizer_best_params=optimizer_best_params,
        node_modules=(node_modules or root / "node_modules").resolve(),
    )
    config = _read_json(output / "fit_config.json")
    proposals_observed = _iteration_count(
        output / "output" / "auto_adjust" / "iteration_series.json"
    )
    best_params, registered_pattern = _refine_with_registered_browser_score(
        output=output,
        capture_config=config["laya_capture"],
        full_resolution_profile_path=profile_path,
        target_path=target_path,
        registration=registration,
        initial_params=best_params,
        max_proposals=max(0, int(iterations) - proposals_observed),
    )
    browser_score = config["laya_capture"]["browser_score"]
    route_report = _read_json(
        output / "initial_score_router" / "initial_score_route_report.json"
    )
    search_report = _read_json(output / "stage2_discrete_search_space_report.json")
    return finalize_stage2_single_view(Stage2FinalizationContext(
        output=output,
        spec=spec,
        reference_view=reference_view,
        optimizer_view=optimizer_view,
        registration=registration,
        profile_path=profile_path,
        target_dir=target_dir,
        target_path=target_path,
        source_target=source_target,
        start_material=start_material,
        start_params=start_params,
        start_patch=start_patch,
        best_params=best_params,
        acceptance_rerank=acceptance_rerank,
        registered_pattern=registered_pattern,
        iterations=iterations,
        fit_elapsed_s=None,
        resolved_width=int(browser_score["readback_width"]),
        resolved_height=int(browser_score["readback_height"]),
        constraints=config["stage2_optimizer_contract"],
        route_report=route_report,
        start_candidate=search_report["start_candidate"],
        confidence_mask_path=output / "inputs" / "frozen_confidence_mask.png",
        node_modules=(node_modules or root / "node_modules").resolve(),
        optimizer_id=OPTIMIZER_ID,
        joint_profile=JOINT_PROFILE,
        maximum_acceptance_distance_ratio=MAXIMUM_ACCEPTANCE_DISTANCE_RATIO,
    ))


def _build_single_view_artifact_driver(
    *,
    profile_path: Path,
    output_root: Path,
    defines: dict[str, Any],
    render_states: dict[str, Any],
    node_modules: Path,
) -> RenderDriver:
    return RenderDriver(
        output_dir=output_root,
        dry_run=False,
        capture_config={
            "runtime_bridge": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 0,
                "asset_profile": str(profile_path),
                "state_dir": str(output_root / "runtime_renderer"),
                "timeout_s": 90,
                "startup_timeout_s": 90,
                "output_subdir": "render",
                "auto_start_renderer": True,
                "node_modules": str(node_modules.resolve()),
            },
            "browser_score": {"enabled": False},
            "material_patch": {
                "target_name": "model",
                "defines": copy.deepcopy(defines),
                "render_states": copy.deepcopy(render_states),
            },
            "return_images": True,
            "preserve_artifact_alpha": False,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "visual_quality_guard": {"enabled": False},
        },
    )


def _select_reference_view(
    views: tuple[dict[str, Any], ...],
    view_id: str,
) -> dict[str, Any]:
    for view in views:
        if str(view["view_id"]) == view_id:
            return copy.deepcopy(view)
    raise ValueError(f"unknown Stage 2 view: {view_id}")


def _single_view_registration(
    registration: dict[str, Any],
    view_id: str,
) -> dict[str, Any]:
    transforms = [
        copy.deepcopy(item)
        for item in registration.get("transforms", [])
        if str(item.get("view_id")) == view_id
    ]
    if len(transforms) != 1:
        raise ValueError(f"registration must contain exactly one transform for {view_id}")
    result = copy.deepcopy(registration)
    result["transforms"] = transforms
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="turtle")
    parser.add_argument("--view-id", default=DEFAULT_VIEW_ID)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--max-runtime-sec", type=float, default=1200.0)
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument(
        "--resume-run",
        default="",
        help="Existing run directory whose optimizer best should only be finalized.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else repo_root / "artifacts"
    )
    if args.resume_run:
        run_dir = Path(args.resume_run).expanduser().resolve()
    else:
        run_name = args.run_name or (
            f"stage2_{args.asset}_single_view_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        run_dir = output_root / run_name
    try:
        common = {
            "repo_root": repo_root,
            "run_dir": run_dir,
            "asset_id": args.asset,
            "view_id": args.view_id,
            "iterations": args.iterations,
            "node_modules": (
                Path(args.node_modules).expanduser().resolve()
                if args.node_modules
                else None
            ),
        }
        if args.resume_run:
            report = resume_stage2_single_view(**common)
        else:
            report = run_stage2_single_view(
                **common,
                target_score=args.target_score,
                max_runtime_sec=args.max_runtime_sec,
            )
    finally:
        if run_dir.exists():
            phase05._cleanup_recorded_runtime(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_VIEW_ID", "resume_stage2_single_view", "run_stage2_single_view"]
