"""Shared PNG-only Stage 1 fitting from original continuous material values."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.material_stage1 import (
    resolve_material_stage1_asset,
)
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.stage1_fit_config import _build_fit_config
from material_fit.experiments.stage1_reporting import (
    _artifact_resolution,
    _discrete_alignment_report,
    _discrete_recovery_report,
    _discrete_search_space_report,
    _finite_score,
    _optimizer_boundary_report,
    _optimizer_score_resolution,
    _parameter_audit,
    _read_json,
    _require_shared_space,
    _runtime_patch_report,
    _write_json,
    _write_optimizer_profile,
    _write_profile,
)
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V30,
    JOINT_PROFILE_V42,
    JOINT_PROFILE_V85,
    JOINT_PROFILE_V86,
    JOINT_PROFILES,
    MAX_OPTIMIZER_ITERATIONS,
    MAX_SCORED_CANDIDATES,
    _joint_profile_policy,
    _joint_profile_runtime_contract,
    _joint_profile_scored_candidate_limit,
    _resolve_v86_initial_score_route,
)
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_recovery import perturb_material_params
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    compress_observationally_equivalent_candidates,
    find_candidate_for_patch,
    split_discrete_candidate,
    write_candidate_lmat_with_discrete_state,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.cross_engine_score import score_cross_engine_views_v3


STAGE1_SEARCH_PARAM_NAMES = (
    *STRUCTURED_MATERIAL_PARAM_NAMES,
    *STRUCTURED_SCENE_PARAM_NAMES,
)
STAGE1_OPTIMIZERS = (
    "cma_cold",
    "material_coordinate_pattern",
    "fish_spsa",
    "material_discrete_joint",
    "material_stage1_hybrid",
    "material_block_hybrid",
    "material_jacobian_trust_region",
    "material_secant_trust_region",
    "structured_fish",
)
STAGE1_OPTIMIZATION_SCORE_METRIC = "cross_engine_foreground_components_v3"
STAGE1_OPTIMIZATION_SCORE_METRICS = (
    STAGE1_OPTIMIZATION_SCORE_METRIC,
    "cross_engine_foreground_components_v4",
    "cross_engine_foreground_components_v5_strict_core",
)
STAGE1_VALIDATION_SCORE_METRIC = phase05.SCORE_METRIC
STAGE1_SCORE_READBACK_WIDTH = 720
STAGE1_SCORE_READBACK_HEIGHT = 0
V83_MAX_SCORED_CANDIDATES = MAX_SCORED_CANDIDATES
V83_MAX_OPTIMIZER_ITERATIONS = MAX_OPTIMIZER_ITERATIONS


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    if args.engine_libs:
        os.environ["LAYA_ENGINE_LIBS"] = str(Path(args.engine_libs).expanduser().resolve())
    run_name = args.run_name or (
        f"stage1_{args.asset}_human_png_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else repo_root / "artifacts"
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] | None = None
    try:
        report = run_stage1(
            repo_root=repo_root,
            run_dir=run_dir,
            asset_id=args.asset,
            profile_path=args.asset_profile or None,
            start_material_path=args.start_material or None,
            target_material_path=args.target_material or None,
            shader_path=args.shader_path or None,
            iterations=args.iterations,
            optimizer=args.optimizer,
            warmup_iterations=args.warmup_iterations,
            block_iterations=args.block_iterations,
            block_population_size=args.block_population_size,
            refine_iterations=args.refine_iterations,
            jacobian_search_scope=args.jacobian_search_scope,
            jacobian_difference_mode=args.jacobian_difference_mode,
            jacobian_solve_mode=args.jacobian_solve_mode,
            jacobian_acceptance_objective=args.jacobian_acceptance_objective,
            jacobian_score_feature_weight=args.jacobian_score_feature_weight,
            jacobian_maximum_score_drop=args.jacobian_maximum_score_drop,
            jacobian_active_coordinate_count=args.jacobian_active_coordinate_count,
            jacobian_full_refresh_interval=args.jacobian_full_refresh_interval,
            jacobian_accept_improving_probes=args.jacobian_accept_improving_probes,
            jacobian_minimum_probe_score_gain=args.jacobian_minimum_probe_score_gain,
            cma_sigma=args.cma_sigma,
            cma_population_size=args.cma_population_size,
            cma_seed=args.cma_seed,
            pattern_initial_step_scale=args.pattern_initial_step_scale,
            pattern_active_coordinate_count=args.pattern_active_coordinate_count,
            pattern_full_refresh_interval=args.pattern_full_refresh_interval,
            spsa_perturbation_scale=args.spsa_perturbation_scale,
            spsa_learning_rate=args.spsa_learning_rate,
            spsa_directions_per_update=args.spsa_directions_per_update,
            target_score=args.target_score,
            success_score=args.success_score,
            max_runtime_sec=args.max_runtime_sec,
            speed_gate_ms=args.speed_gate_ms,
            node_modules=args.node_modules or None,
            score_width=args.score_width,
            score_height=args.score_height,
            score_metric=args.score_metric,
            residual_grid_size=args.residual_grid_size,
            residual_sketch_size=args.residual_sketch_size,
            joint_profile=args.joint_profile,
        )
    finally:
        phase05._cleanup_recorded_runtime(run_dir)
    assert report is not None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asset",
        required=True,
        choices=("fish", "turtle", "crocodile", "fish_1504", "turtle_1506", "crocodile_1503"),
    )
    parser.add_argument("--asset-profile", default="")
    parser.add_argument("--start-material", default="")
    parser.add_argument("--target-material", default="")
    parser.add_argument("--shader-path", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--optimizer", choices=STAGE1_OPTIMIZERS, default="material_discrete_joint")
    parser.add_argument("--joint-profile", choices=JOINT_PROFILES, default=JOINT_PROFILE_V86)
    parser.add_argument("--warmup-iterations", type=int, default=1000)
    parser.add_argument("--block-iterations", type=int, default=400)
    parser.add_argument("--block-population-size", type=int, default=16)
    parser.add_argument("--refine-iterations", type=int, default=800)
    parser.add_argument(
        "--jacobian-search-scope",
        choices=("all", "scene", "material"),
        default="all",
    )
    parser.add_argument(
        "--jacobian-difference-mode",
        choices=("forward", "central"),
        default="central",
    )
    parser.add_argument(
        "--jacobian-solve-mode",
        choices=("full_least_squares", "diagonal_gauss_newton", "score_gradient"),
        default="full_least_squares",
    )
    parser.add_argument(
        "--jacobian-acceptance-objective",
        choices=("fit_score", "residual_merit"),
        default="fit_score",
    )
    parser.add_argument("--jacobian-score-feature-weight", type=float, default=20.0)
    parser.add_argument("--jacobian-maximum-score-drop", type=float, default=0.015)
    parser.add_argument("--jacobian-active-coordinate-count", type=int, default=0)
    parser.add_argument("--jacobian-full-refresh-interval", type=int, default=0)
    parser.add_argument("--jacobian-accept-improving-probes", action="store_true")
    parser.add_argument("--jacobian-minimum-probe-score-gain", type=float, default=0.0)
    parser.add_argument("--cma-sigma", type=float, default=0.03)
    parser.add_argument("--cma-population-size", type=int, default=16)
    parser.add_argument("--cma-seed", type=int, default=20260715)
    parser.add_argument("--pattern-initial-step-scale", type=float, default=0.25)
    parser.add_argument("--pattern-active-coordinate-count", type=int, default=12)
    parser.add_argument("--pattern-full-refresh-interval", type=int, default=4)
    parser.add_argument("--spsa-perturbation-scale", type=float, default=0.01)
    parser.add_argument("--spsa-learning-rate", type=float, default=0.03)
    parser.add_argument("--spsa-directions-per-update", type=int, default=8)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--success-score", type=float, default=0.98)
    parser.add_argument("--max-runtime-sec", type=float, default=3600.0)
    parser.add_argument("--speed-gate-ms", type=float, default=500.0)
    parser.add_argument("--score-width", type=int, default=STAGE1_SCORE_READBACK_WIDTH)
    parser.add_argument(
        "--score-height",
        type=int,
        default=STAGE1_SCORE_READBACK_HEIGHT,
        help="online score height; 0 preserves the asset profile aspect ratio",
    )
    parser.add_argument("--residual-grid-size", type=int, default=16)
    parser.add_argument("--residual-sketch-size", type=int, default=128)
    parser.add_argument(
        "--score-metric",
        choices=STAGE1_OPTIMIZATION_SCORE_METRICS,
        default=STAGE1_OPTIMIZATION_SCORE_METRIC,
    )
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--engine-libs", default="")
    args = parser.parse_args(argv)
    if args.iterations is None:
        max_scored_candidates = None
        if args.optimizer == "material_discrete_joint":
            max_scored_candidates = _joint_profile_scored_candidate_limit(
                _joint_profile_policy(args.joint_profile)
            )
        args.iterations = (
            max_scored_candidates - 1
            if max_scored_candidates is not None
            else 7000
        )
    return args


def run_stage1(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str,
    profile_path: str | Path | None,
    start_material_path: str | Path | None,
    target_material_path: str | Path | None,
    shader_path: str | Path | None,
    iterations: int,
    optimizer: str,
    warmup_iterations: int,
    block_iterations: int,
    block_population_size: int,
    refine_iterations: int,
    jacobian_search_scope: str,
    jacobian_difference_mode: str = "central",
    jacobian_solve_mode: str = "full_least_squares",
    target_score: float,
    success_score: float,
    max_runtime_sec: float,
    speed_gate_ms: float,
    node_modules: str | Path | None,
    jacobian_acceptance_objective: str = "fit_score",
    jacobian_score_feature_weight: float = 20.0,
    jacobian_maximum_score_drop: float = 0.015,
    jacobian_active_coordinate_count: int = 0,
    jacobian_full_refresh_interval: int = 0,
    jacobian_accept_improving_probes: bool = False,
    jacobian_minimum_probe_score_gain: float = 0.0,
    cma_sigma: float = 0.03,
    cma_population_size: int = 16,
    cma_seed: int = 20260715,
    pattern_initial_step_scale: float = 0.25,
    pattern_active_coordinate_count: int = 12,
    pattern_full_refresh_interval: int = 4,
    spsa_perturbation_scale: float = 0.01,
    spsa_learning_rate: float = 0.03,
    spsa_directions_per_update: int = 8,
    score_width: int = STAGE1_SCORE_READBACK_WIDTH,
    score_height: int = STAGE1_SCORE_READBACK_HEIGHT,
    score_metric: str = STAGE1_OPTIMIZATION_SCORE_METRIC,
    residual_grid_size: int = 16,
    residual_sketch_size: int = 128,
    joint_profile: str = JOINT_PROFILE_V86,
    discrete_round_widths: tuple[int, ...] = (8, 4, 4),
    discrete_round_budgets: tuple[int, ...] = (64, 160, 320),
    discrete_round_sigmas: tuple[float, ...] = (0.18, 0.10, 0.05),
) -> dict[str, Any]:
    joint_policy = _joint_profile_policy(joint_profile)
    selected_joint_profile = joint_profile
    selected_joint_policy = joint_policy
    selected_iterations = int(iterations)
    initial_score_route_report: dict[str, Any] = {}
    if (
        optimizer == "material_discrete_joint"
        and _joint_profile_scored_candidate_limit(joint_policy) is not None
        and joint_profile != JOINT_PROFILE_V86
    ):
        discrete_round_widths = tuple(joint_policy["round_widths"])
        discrete_round_budgets = tuple(joint_policy["round_budgets"])
        discrete_round_sigmas = tuple(joint_policy["round_sigmas"])
        (
            score_metric,
            score_width,
            score_height,
            residual_grid_size,
            residual_sketch_size,
        ) = _joint_profile_runtime_contract(
            profile=joint_profile,
            policy=joint_policy,
            iterations=iterations,
            score_metric=score_metric,
            score_width=score_width,
            score_height=score_height,
            residual_grid_size=residual_grid_size,
            residual_sketch_size=residual_sketch_size,
        )
    asset = resolve_material_stage1_asset(
        repo_root,
        asset_id,
        profile_path=profile_path,
        start_material_path=start_material_path,
        target_material_path=target_material_path,
        shader_path=shader_path,
    )
    score_width, score_height = _optimizer_score_resolution(
        asset.profile,
        requested_width=score_width,
        requested_height=score_height,
    )
    optimizer_reference_width = int(score_width)
    optimizer_reference_height = int(score_height)
    profile_file = _write_profile(asset, run_dir / "inputs/asset_profile.json")
    phase05._force_white_background(profile_file)
    optimizer_profile_file: Path | None = None
    if joint_profile != JOINT_PROFILE_V86:
        optimizer_profile_file = _write_optimizer_profile(
            profile_file,
            run_dir / "inputs/optimizer_asset_profile.json",
            width=score_width,
            height=score_height,
        )
    views = phase05._profile_views(profile_file)

    private_dir = run_dir / "private_audit"
    inputs_dir = run_dir / "inputs"
    private_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    target_payload = lmat_io.load_lmat(asset.target_material_path)
    original_start_payload = lmat_io.load_lmat(asset.start_material_path)
    target_params = lmat_io.extract_params(target_payload)
    original_start_params = lmat_io.extract_params(original_start_payload)
    _require_shared_space(target_params, asset.asset_id, role="target")
    _require_shared_space(original_start_params, asset.asset_id, role="start")
    _write_json(private_dir / "target_params.json", target_params)
    shutil.copy2(asset.target_material_path, private_dir / "target_material.lmat")

    target_patch = material_patch_from_lmat(asset.target_material_path)
    original_start_patch = material_patch_from_lmat(asset.start_material_path)
    discrete_candidates: list[dict[str, Any]] = []
    optimizer_discrete_candidates: list[dict[str, Any]] = []
    discrete_equivalence_report: dict[str, Any] = {}
    start_candidate: dict[str, Any] | None = None
    if optimizer == "material_discrete_joint":
        optimizer_start_path = asset.start_material_path
        optimizer_start_params = original_start_params
        optimizer_start_patch = original_start_patch
        discrete_candidates = build_legal_discrete_candidates(original_start_patch)
        start_candidate = find_candidate_for_patch(discrete_candidates, original_start_patch)
        optimizer_discrete_candidates = discrete_candidates
        if (
            joint_profile != JOINT_PROFILE_V86
            and joint_policy.get("discrete_observation_equivalence", False)
        ):
            (
                optimizer_discrete_candidates,
                discrete_equivalence_report,
            ) = compress_observationally_equivalent_candidates(
                discrete_candidates,
                start_candidate=start_candidate,
                start_patch=original_start_patch,
            )
            _write_json(
                run_dir / "stage1_discrete_observation_equivalence_report.json",
                discrete_equivalence_report,
            )
        discrete_report = _discrete_search_space_report(
            asset=asset,
            start_patch=original_start_patch,
            candidates=discrete_candidates,
            start_candidate=start_candidate,
        )
        if discrete_equivalence_report:
            discrete_report["optimizer_observation_equivalence"] = copy.deepcopy(
                discrete_equivalence_report
            )
        _write_json(run_dir / "stage1_discrete_search_space_report.json", discrete_report)
    else:
        aligned_start_path = inputs_dir / "discrete_aligned_start.lmat"
        alignment = lmat_io.write_discrete_aligned_lmat(
            asset.start_material_path,
            asset.target_material_path,
            aligned_start_path,
        )
        aligned_start_payload = lmat_io.load_lmat(aligned_start_path)
        optimizer_start_path = aligned_start_path
        optimizer_start_params = lmat_io.extract_params(aligned_start_payload)
        optimizer_start_patch = material_patch_from_lmat(aligned_start_path)
        discrete_report = _discrete_alignment_report(
            asset=asset,
            alignment=alignment,
            original_start=original_start_payload,
            aligned_start=aligned_start_payload,
            target=target_payload,
            target_patch=target_patch,
            aligned_patch=optimizer_start_patch,
        )
        _write_json(run_dir / "stage1_discrete_base_report.json", discrete_report)
    _write_json(inputs_dir / "start_params.json", optimizer_start_params)
    if not discrete_report["passed"]:
        raise RuntimeError(f"Stage 1 discrete start contract failed: {discrete_report}")

    tiny_params, tiny_report = perturb_material_params(target_params, preset="tiny", seed=20260713)
    _write_json(private_dir / "tiny_target_perturbation.json", tiny_report)
    target_dir = run_dir / "target_render"
    router_start_dir = run_dir / "initial_score_router/start_render"
    optimizer_target_dir = run_dir / "optimizer_target_render"
    target_repeat_dir = run_dir / "scorer_sanity/target_repeat"
    tiny_dir = run_dir / "scorer_sanity/tiny_perturbation"
    target_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_file,
        output_root=run_dir / "target_capture/runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=target_driver,
            artifact_dir=target_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
    finally:
        target_driver.close()

    if joint_profile == JOINT_PROFILE_V86:
        if optimizer != "material_discrete_joint" or start_candidate is None:
            raise ValueError("V86 requires material_discrete_joint and a start state")
        router_driver = phase05._build_artifact_capture_driver(
            profile_path=profile_file,
            output_root=run_dir / "initial_score_router/runtime",
            defines=optimizer_start_patch["defines"],
            render_states=optimizer_start_patch["render_states"],
            references=None,
            node_modules=node_modules,
        )
        try:
            phase05._capture_artifact_set(
                driver=router_driver,
                artifact_dir=router_start_dir,
                params=attach_discrete_candidate(
                    optimizer_start_params,
                    start_candidate,
                ),
                views=views,
                iteration=0,
            )
        finally:
            router_driver.close()
        initial_score_payload = score_cross_engine_views_v3(
            reference_dir=target_dir,
            candidate_dir=router_start_dir,
            views=views,
        )
        initial_score = _finite_score(initial_score_payload)
        if initial_score is None:
            raise RuntimeError(
                "V86 initial-score route render did not produce a valid Python V3 score"
            )
        (
            selected_joint_profile,
            selected_joint_policy,
            selected_iterations,
            score_metric,
            score_width,
            score_height,
            residual_grid_size,
            residual_sketch_size,
            initial_score_route_report,
        ) = _resolve_v86_initial_score_route(
            policy=joint_policy,
            initial_score=initial_score,
            asset_profile=asset.profile,
            requested_iterations=iterations,
            score_metric=score_metric,
            score_width=score_width,
            score_height=score_height,
            residual_grid_size=residual_grid_size,
            residual_sketch_size=residual_sketch_size,
        )
        initial_score_route_report.update(
            {
                "target_render_dir": str(target_dir),
                "start_render_dir": str(router_start_dir),
                "score_payload": initial_score_payload,
            }
        )
        (
            optimizer_reference_width,
            optimizer_reference_height,
        ) = initial_score_route_report["selected_reference_resolution"]
        _write_json(
            run_dir / "initial_score_router/initial_score_route_report.json",
            initial_score_route_report,
        )
        discrete_round_widths = tuple(selected_joint_policy["round_widths"])
        discrete_round_budgets = tuple(selected_joint_policy["round_budgets"])
        discrete_round_sigmas = tuple(selected_joint_policy["round_sigmas"])
        optimizer_discrete_candidates = discrete_candidates
        discrete_equivalence_report = {}
        if selected_joint_policy.get("discrete_observation_equivalence", False):
            (
                optimizer_discrete_candidates,
                discrete_equivalence_report,
            ) = compress_observationally_equivalent_candidates(
                discrete_candidates,
                start_candidate=start_candidate,
                start_patch=original_start_patch,
            )
            _write_json(
                run_dir / "stage1_discrete_observation_equivalence_report.json",
                discrete_equivalence_report,
            )
        if discrete_equivalence_report:
            discrete_report["optimizer_observation_equivalence"] = copy.deepcopy(
                discrete_equivalence_report
            )
        _write_json(
            run_dir / "stage1_discrete_search_space_report.json",
            discrete_report,
        )
        optimizer_profile_file = _write_optimizer_profile(
            profile_file,
            run_dir / "inputs/optimizer_asset_profile.json",
            width=optimizer_reference_width,
            height=optimizer_reference_height,
        )

    if optimizer_profile_file is None:
        raise RuntimeError("Stage 1 optimizer profile was not resolved")
    optimizer_target_driver = phase05._build_artifact_capture_driver(
        profile_path=optimizer_profile_file,
        output_root=run_dir / "optimizer_target_capture/runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=optimizer_target_driver,
            artifact_dir=optimizer_target_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
    finally:
        optimizer_target_driver.close()

    scorer_driver = phase05._build_artifact_capture_driver(
        profile_path=optimizer_profile_file,
        output_root=run_dir / "scorer_sanity/runtime",
        defines=target_patch["defines"],
        render_states=target_patch["render_states"],
        references=optimizer_target_dir,
        node_modules=node_modules,
    )
    try:
        repeated = phase05._capture_artifact_set(
            driver=scorer_driver,
            artifact_dir=target_repeat_dir,
            params=target_params,
            views=views,
            iteration=0,
        )
        tiny = phase05._capture_artifact_set(
            driver=scorer_driver,
            artifact_dir=tiny_dir,
            params=tiny_params,
            views=views,
            iteration=1,
        )
    finally:
        scorer_driver.close()
    scorer_report = phase05._scorer_sanity_report(
        target_dir=optimizer_target_dir,
        repeat_dir=target_repeat_dir,
        tiny_dir=tiny_dir,
        views=views,
        repeated_result=repeated,
        tiny_result=tiny,
    )
    scorer_report["target_and_candidate_daemons_overlapped"] = False
    _write_json(run_dir / "scorer_sanity/scorer_sanity_report.json", scorer_report)
    if not scorer_report["passed"]:
        raise RuntimeError(f"Stage 1 scorer sanity failed: {scorer_report}")

    fit_config = _build_fit_config(
        asset=asset,
        profile_path=optimizer_profile_file,
        run_dir=run_dir,
        start_material_path=optimizer_start_path,
        target_dir=optimizer_target_dir,
        optimizer_start_patch=optimizer_start_patch,
        discrete_candidates=optimizer_discrete_candidates,
        discrete_equivalence_report=discrete_equivalence_report,
        start_candidate=start_candidate,
        discrete_round_widths=discrete_round_widths,
        discrete_round_budgets=discrete_round_budgets,
        discrete_round_sigmas=discrete_round_sigmas,
        target_score=target_score,
        optimization_score_metric=score_metric,
        residual_grid_size=residual_grid_size,
        residual_sketch_size=residual_sketch_size,
        optimizer=optimizer,
        warmup_iterations=warmup_iterations,
        block_iterations=block_iterations,
        block_population_size=block_population_size,
        refine_iterations=refine_iterations,
        jacobian_search_scope=jacobian_search_scope,
        jacobian_difference_mode=jacobian_difference_mode,
        jacobian_solve_mode=jacobian_solve_mode,
        jacobian_acceptance_objective=jacobian_acceptance_objective,
        jacobian_score_feature_weight=jacobian_score_feature_weight,
        jacobian_maximum_score_drop=jacobian_maximum_score_drop,
        jacobian_active_coordinate_count=jacobian_active_coordinate_count,
        jacobian_full_refresh_interval=jacobian_full_refresh_interval,
        jacobian_accept_improving_probes=jacobian_accept_improving_probes,
        jacobian_minimum_probe_score_gain=jacobian_minimum_probe_score_gain,
        cma_sigma=cma_sigma,
        cma_population_size=cma_population_size,
        cma_seed=cma_seed,
        pattern_initial_step_scale=pattern_initial_step_scale,
        pattern_active_coordinate_count=pattern_active_coordinate_count,
        pattern_full_refresh_interval=pattern_full_refresh_interval,
        spsa_perturbation_scale=spsa_perturbation_scale,
        spsa_learning_rate=spsa_learning_rate,
        spsa_directions_per_update=spsa_directions_per_update,
        node_modules=node_modules,
        views=views,
        joint_profile=selected_joint_profile,
        joint_policy_override=(
            selected_joint_policy
            if optimizer == "material_discrete_joint"
            else None
        ),
        browser_score_width=score_width,
        browser_score_height=score_height,
    )
    if initial_score_route_report:
        fit_config["stage1_initial_score_router"] = copy.deepcopy(
            initial_score_route_report
        )
    boundary = _optimizer_boundary_report(
        fit_config,
        private_dir=private_dir,
        target_material_path=asset.target_material_path,
    )
    _write_json(run_dir / "optimizer_input_boundary_report.json", boundary)
    if not boundary["passed"]:
        raise RuntimeError(f"Stage 1 optimizer input boundary failed: {boundary['hits']}")
    fit_config_path = run_dir / "fit_config.json"
    _write_json(fit_config_path, fit_config)

    fit_started = time.perf_counter()
    fit_returncode = phase05._run_fit_owned(
        repo_root=repo_root,
        run_dir=run_dir,
        config_path=fit_config_path,
        iterations=selected_iterations,
        target_score=target_score,
        max_runtime_sec=max_runtime_sec,
        optimizer=optimizer,
    )
    fit_elapsed_s = time.perf_counter() - fit_started
    if fit_returncode != 0:
        raise RuntimeError(f"Stage 1 fit exited with {fit_returncode}; see {run_dir / 'logs'}")

    best_params_path = run_dir / "output/auto_adjust/best/params.json"
    if not best_params_path.is_file():
        raise FileNotFoundError(f"Stage 1 optimizer did not produce best params: {best_params_path}")
    best_params_raw = _read_json(best_params_path)
    best_continuous_params, best_candidate = split_discrete_candidate(best_params_raw)
    if optimizer == "material_discrete_joint":
        if best_candidate is None or start_candidate is None:
            raise RuntimeError("joint Stage 1 best result is missing its discrete candidate")
        start_render_params = attach_discrete_candidate(optimizer_start_params, start_candidate)
        best_render_params = attach_discrete_candidate(
            best_continuous_params,
            best_candidate,
        )
        if best_render_params != best_params_raw:
            _write_json(
                private_dir / "optimizer_best_params_with_transport_metadata.json",
                best_params_raw,
            )
            _write_json(best_params_path, best_render_params)
        final_base_patch = optimizer_start_patch
        target_candidate = find_candidate_for_patch(discrete_candidates, target_patch)
    else:
        best_continuous_params = best_params_raw
        best_candidate = None
        start_render_params = optimizer_start_params
        best_render_params = best_params_raw
        final_base_patch = target_patch
        target_candidate = None
        discrete_recovery = {
            "contract": "copied_target_discrete_state_diagnostic_v1",
            "passed": True,
            "optimizer_selected_discrete_state": False,
        }
    _write_json(run_dir / "best_continuous_params.json", best_continuous_params)
    final_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_file,
        output_root=run_dir / "final_capture/runtime",
        defines=final_base_patch["defines"],
        render_states=final_base_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
    )
    try:
        start_result = phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=run_dir / "start_render",
            params=start_render_params,
            views=views,
            iteration=0,
        )
        best_result = phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=run_dir / "best_render",
            params=best_render_params,
            views=views,
            iteration=1,
        )
        if (
            optimizer == "material_discrete_joint"
            and target_candidate is not None
            and best_candidate is not None
            and target_candidate["candidate_id"] != best_candidate["candidate_id"]
        ):
            phase05._capture_artifact_set(
                driver=final_driver,
                artifact_dir=private_dir / "best_continuous_target_discrete_render",
                params=attach_discrete_candidate(best_continuous_params, target_candidate),
                views=views,
                iteration=2,
            )
    finally:
        final_driver.close()
    artifact_resolutions = {
        role: _artifact_resolution(directory, views)
        for role, directory in {
            "target": target_dir,
            "start": run_dir / "start_render",
            "best": run_dir / "best_render",
        }.items()
    }
    if len({tuple(value) for value in artifact_resolutions.values()}) != 1:
        raise RuntimeError(f"Stage 1 artifact resolutions differ: {artifact_resolutions}")
    artifact_render_resolution = artifact_resolutions["target"]
    if optimizer == "material_discrete_joint":
        write_candidate_lmat_with_discrete_state(
            optimizer_start_path,
            run_dir / "best_material.lmat",
            best_render_params,
        )
    else:
        lmat_io.write_candidate_lmat(
            optimizer_start_path,
            run_dir / "best_material.lmat",
            best_continuous_params,
            allow_missing_keys=True,
        )

    scores = {
        "start": score_cross_engine_views_v3(
            reference_dir=target_dir,
            candidate_dir=run_dir / "start_render",
            views=views,
        ),
        "best": score_cross_engine_views_v3(
            reference_dir=target_dir,
            candidate_dir=run_dir / "best_render",
            views=views,
        ),
    }
    if optimizer == "material_discrete_joint":
        assert start_candidate is not None
        assert target_candidate is not None
        assert best_candidate is not None
        if target_candidate["candidate_id"] == best_candidate["candidate_id"]:
            target_discrete_audit_score = _finite_score(scores["best"])
        else:
            target_discrete_audit_score = _finite_score(
                score_cross_engine_views_v3(
                    reference_dir=target_dir,
                    candidate_dir=private_dir / "best_continuous_target_discrete_render",
                    views=views,
                )
            )
        discrete_recovery = _discrete_recovery_report(
            start_candidate=start_candidate,
            target_candidate=target_candidate,
            best_candidate=best_candidate,
            best_score=_finite_score(scores["best"]),
            target_discrete_audit_score=target_discrete_audit_score,
            success_score=success_score,
        )
        _write_json(private_dir / "stage1_discrete_recovery_report.json", discrete_recovery)
    _write_json(run_dir / "stage1_image_score_report.json", scores)
    parameter_audit = _parameter_audit(
        target_params,
        optimizer_start_params,
        best_continuous_params,
    )
    _write_json(private_dir / "stage1_parameter_audit.json", parameter_audit)
    timing = phase05._timing_report(run_dir / "output/auto_adjust/iteration_series.json", speed_gate_ms)
    _write_json(run_dir / "iteration_timing_report.json", timing)
    scored_candidate_count = int(timing["count"]) + 1
    budget_limit = (
        _joint_profile_scored_candidate_limit(joint_policy)
        if optimizer == "material_discrete_joint"
        else None
    )
    budget_report = {
        "contract": "material_stage1_scored_candidate_budget_v1",
        "joint_profile": joint_profile if optimizer == "material_discrete_joint" else None,
        "selected_joint_profile": (
            selected_joint_profile
            if optimizer == "material_discrete_joint"
            else None
        ),
        "optimizer_iterations_cli_requested": int(iterations),
        "optimizer_iterations_requested": int(selected_iterations),
        "optimizer_iterations_observed": int(timing["count"]),
        "initial_material_score_included": True,
        "scored_candidate_count": scored_candidate_count,
        "max_scored_candidates": budget_limit,
        "planned_proposal_budget": copy.deepcopy(
            fit_config.get("material_discrete_joint", {}).get(
                "planned_proposal_budget", {}
            )
        ),
        "passed": budget_limit is None or scored_candidate_count <= budget_limit,
    }
    _write_json(run_dir / "stage1_budget_report.json", budget_report)
    contact_sheet = phase05._write_contact_sheet(
        views=views,
        columns=(("Human target", target_dir), ("Original material start", run_dir / "start_render"), ("Optimized best", run_dir / "best_render")),
        output_path=run_dir / "human_target_start_best_eightview.png",
    )
    cleanup = phase05._cleanup_recorded_runtime(run_dir)
    view_counts = {
        "target": phase05._view_count(target_dir, views),
        "optimizer_target": phase05._view_count(optimizer_target_dir, views),
        "start": phase05._view_count(run_dir / "start_render", views),
        "best": phase05._view_count(run_dir / "best_render", views),
    }
    start_score = _finite_score(scores["start"])
    best_score = _finite_score(scores["best"])
    runtime_patch = _runtime_patch_report(
        start_patch=optimizer_start_patch,
        best_candidate=best_candidate,
        start_result=start_result,
        best_result=best_result,
    )
    _write_json(run_dir / "runtime_discrete_patch_report.json", runtime_patch)
    accepted = bool(
        discrete_report["passed"]
        and discrete_recovery["passed"]
        and scorer_report["passed"]
        and boundary["passed"]
        and runtime_patch["passed"]
        and best_score is not None
        and start_score is not None
        and best_score >= success_score
        and best_score >= start_score
        and timing["gate_passed"]
        and budget_report["passed"]
        and cleanup["remaining_owned_pid_count"] == 0
        and all(count == 8 for count in view_counts.values())
    )
    report = {
        "contract": "shared_material_human_reference_stage1_v2_joint_discrete",
        "accepted": accepted,
        "asset_id": asset.asset_id,
        "run_dir": str(run_dir),
        "optimizer_runtime_id": optimizer,
        "optimization_score_metric": score_metric,
        "validation_score_metric": STAGE1_VALIDATION_SCORE_METRIC,
        "artifact_score_metric": "cross_engine_material_score_v3",
        "optimizer_visible_target": "eight target PNGs and online score/residuals only",
        "target_continuous_params_visible_to_optimizer": False,
        "target_discrete_state_visible_to_optimizer": False,
        "discrete_base": (
            "original discrete and continuous material state"
            if optimizer == "material_discrete_joint"
            else "original continuous params plus copied target shader/hard state"
        ),
        "material_coordinate_count": int(
            fit_config["stage1_optimizer_contract"]["material_coordinate_count"]
        ),
        "scene_coordinate_count": int(
            fit_config["stage1_optimizer_contract"]["scene_coordinate_count"]
        ),
        "scene_coordinates_searchable": bool(
            fit_config["stage1_optimizer_contract"]["scene_coordinates_searchable"]
        ),
        "iterations_cli_requested": iterations,
        "iterations_requested": selected_iterations,
        "joint_profile": joint_profile if optimizer == "material_discrete_joint" else None,
        "selected_joint_profile": (
            selected_joint_profile
            if optimizer == "material_discrete_joint"
            else None
        ),
        "initial_score_route": copy.deepcopy(initial_score_route_report),
        "budget": budget_report,
        "fit_elapsed_s": fit_elapsed_s,
        "start_score": start_score,
        "best_score": best_score,
        "score_gain": (
            best_score - start_score
            if best_score is not None and start_score is not None
            else None
        ),
        "success_score": success_score,
        "discrete_base_report": discrete_report,
        "discrete_recovery_passed": bool(discrete_recovery["passed"]),
        "discrete_recovery_private_audit_path": str(
            private_dir / "stage1_discrete_recovery_report.json"
        ) if optimizer == "material_discrete_joint" else None,
        "runtime_discrete_patch": runtime_patch,
        "scorer_sanity": scorer_report,
        "optimizer_input_boundary": boundary,
        "timing": timing,
        "process_cleanup": cleanup,
        "view_counts": view_counts,
        "contact_sheet": str(contact_sheet),
        "target_render_dir": str(target_dir),
        "optimizer_target_render_dir": str(optimizer_target_dir),
        "optimizer_render_resolution": [score_width, score_height],
        "artifact_render_resolution": artifact_render_resolution,
        "artifact_render_resolutions": artifact_resolutions,
        "start_render_dir": str(run_dir / "start_render"),
        "best_render_dir": str(run_dir / "best_render"),
        "best_params_path": str(best_params_path),
        "best_continuous_params_path": str(run_dir / "best_continuous_params.json"),
        "best_material_path": str(run_dir / "best_material.lmat"),
    }
    _write_json(run_dir / "stage1_report.json", report)
    return report

if __name__ == "__main__":
    raise SystemExit(main())
