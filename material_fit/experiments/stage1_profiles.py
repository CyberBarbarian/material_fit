"""Maintained policy profiles for shared human-reference Stage 1 fitting.

The optimizer originally accumulated one Python branch per experiment version.
Only V86 and the three policies selected by its score router are runtime
contracts now.  The child policies are checked-in JSON snapshots so their
contents remain reviewable and reproducible without retaining every discarded
experiment branch in executable code.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from material_fit.experiments.stage1_reporting import _optimizer_score_resolution
from material_fit.optimizer.structured_material_space import STRUCTURED_SCENE_PARAM_NAMES


JOINT_PROFILE_V30 = "v30_budget1000_v4_forward_double_rescan"
JOINT_PROFILE_V42 = "v42_budget1000_structured_then_active8_jacobian"
JOINT_PROFILE_V85 = "v85_budget1500_v4_portfolio_scene_refine"
JOINT_PROFILE_V86 = "v86_budget1500_initial_score_routed_unified"
JOINT_PROFILES = (JOINT_PROFILE_V86,)

MAX_SCORED_CANDIDATES = 1500
MAX_OPTIMIZER_ITERATIONS = MAX_SCORED_CANDIDATES - 1

_PROFILE_FILES = {
    JOINT_PROFILE_V30: (
        "high_v30.json",
        "36383f2f059dab07bb067efe4bd2d32fad5efe8a0fd308255e7a13faa92096a2",
    ),
    JOINT_PROFILE_V42: (
        "medium_v42.json",
        "6d40420c5238849994c2c1f652f08859b84b9f0df9dee5b4e4595ea8b4785606",
    ),
    JOINT_PROFILE_V85: (
        "low_v85.json",
        "48f88c6fcdfa07998c2bab3c4fc62bc3c204d45e0b137003c86fdec41a4c43f1",
    ),
}


def joint_profile_policy(profile: str) -> dict[str, Any]:
    """Return a detached copy of one maintained Stage 1 policy."""

    if profile == JOINT_PROFILE_V86:
        return _v86_router_policy()
    try:
        file_name, expected_sha256 = _PROFILE_FILES[profile]
    except KeyError as exc:
        raise ValueError(f"unsupported Stage 1 profile: {profile}") from exc

    path = _profile_dir() / file_name
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"Stage 1 policy snapshot hash mismatch for {path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    return copy.deepcopy(json.loads(raw.decode("utf-8")))


def _profile_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "stage1_v86"


def _v86_router_policy() -> dict[str, Any]:
    return {
        "runtime_profile": (
            "material_discrete_joint_v86_budget1500_"
            "initial_score_routed_unified"
        ),
        "max_scored_candidates": MAX_SCORED_CANDIDATES,
        "initial_score_metric": "cross_engine_material_score_v3",
        "optimization_score_metric": "cross_engine_foreground_components_v4",
        "score_width": 400,
        "score_height": 0,
        "residual_grid_size": 16,
        "residual_sketch_size": 128,
        "discrete_observation_equivalence": True,
        "proposal_quantization_normalized_step": 0.0001,
        "initial_score_strategy_routes": [
            {
                "route_id": "low_initial_score",
                "minimum_inclusive": 0.0,
                "maximum_exclusive": 0.75,
                "budget_profile": JOINT_PROFILE_V85,
                "score_metric": "cross_engine_foreground_components_v5_strict_core",
                "score_width": 400,
                "score_height": 0,
                "reference_width": 400,
                "reference_height": 0,
                "discrete_observation_equivalence": True,
                "proposal_quantization_normalized_step": 0.0001,
            },
            {
                "route_id": "medium_initial_score",
                "minimum_inclusive": 0.75,
                "maximum_exclusive": 0.85,
                "budget_profile": JOINT_PROFILE_V42,
                "score_metric": "cross_engine_foreground_components_v3",
                "score_width": 720,
                "score_height": 0,
                "reference_width": 400,
                "reference_height": 0,
                "discrete_observation_equivalence": True,
                "proposal_quantization_normalized_step": 0.0001,
            },
            {
                "route_id": "high_initial_score",
                "minimum_inclusive": 0.85,
                "maximum_exclusive": 1.0000001,
                "budget_profile": JOINT_PROFILE_V30,
                "score_metric": "cross_engine_foreground_components_v4",
                "score_width": 544,
                "score_height": 0,
                "reference_width": 544,
                "reference_height": 0,
                "discrete_observation_equivalence": False,
                "proposal_quantization_normalized_step": 0.0,
                "feedback_score_step": 0.0,
                "feedback_residual_step": 0.0,
                "feedback_full_precision_after_final_rescan": True,
                "late_common_state_rescan": True,
            },
        ],
        "planned_proposal_budget": {
            "low_initial_score_path": {
                "selected_child_optimizer": 1498,
                "total": 1498,
            },
            "medium_initial_score_path": {
                "selected_child_optimizer": 998,
                "scene_frozen_material_extension": 500,
                "total": 1498,
            },
            "high_initial_score_path": {
                "selected_child_optimizer": 998,
                "scene_frozen_material_extension": 500,
                "total": 1498,
            },
        },
    }


def _joint_profile_scored_candidate_limit(policy: dict[str, Any]) -> int | None:
    value = policy.get("max_scored_candidates")
    return int(value) if value is not None else None


def _joint_profile_runtime_contract(
    *,
    profile: str,
    policy: dict[str, Any],
    iterations: int,
    score_metric: str,
    score_width: int,
    score_height: int,
    residual_grid_size: int,
    residual_sketch_size: int,
) -> tuple[str, int, int, int, int]:
    max_scored_candidates = _joint_profile_scored_candidate_limit(policy)
    if max_scored_candidates is None:
        return (
            score_metric,
            score_width,
            score_height,
            residual_grid_size,
            residual_sketch_size,
        )

    max_iterations = max_scored_candidates - 1
    if iterations > max_iterations:
        raise ValueError(
            f"{profile} permits at most {max_iterations} optimizer iterations "
            "so the initial material render plus proposals stay within "
            f"{max_scored_candidates} scored candidates"
        )
    return (
        str(policy.get("optimization_score_metric", score_metric)),
        int(policy.get("score_width", score_width)),
        int(policy.get("score_height", score_height)),
        int(policy.get("residual_grid_size", residual_grid_size)),
        int(policy.get("residual_sketch_size", residual_sketch_size)),
    )


def _extend_v86_child_policy_to_1500(
    *,
    selected_profile: str,
    selected_policy: dict[str, Any],
    max_scored_candidates: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    extended = copy.deepcopy(selected_policy)
    original_limit = _joint_profile_scored_candidate_limit(extended)
    if original_limit is None or original_limit >= max_scored_candidates:
        return extended, {
            "applied": False,
            "original_max_scored_candidates": original_limit,
            "extended_max_scored_candidates": original_limit,
            "added_optimizer_proposals": 0,
            "target_params_visible": False,
            "asset_id_visible": False,
        }

    added_proposals = max_scored_candidates - original_limit
    extended["max_scored_candidates"] = int(max_scored_candidates)
    extended["runtime_profile"] = (
        f"{extended.get('runtime_profile', selected_profile)}_v86_1500_extension"
    )

    if selected_profile == JOINT_PROFILE_V42:
        final = extended["post_rescan_branch_race"]["final_continuous"]
        final["profile"] = (
            f"{final.get('profile', 'material_stage1_v42')}_v86_1500_extension"
        )
        final["terminal_pattern_iterations"] = added_proposals
        final["terminal_pattern"] = {
            "initial_step_scale": 0.03125,
            "minimum_step_scale": 0.000244140625,
            "step_growth": 1.15,
            "step_shrink": 0.5,
            "minimum_score_gain": 1.0e-6,
            "pattern_move_scales": [0.5, 1.0],
            "active_coordinate_count": 16,
            "full_refresh_interval": 3,
        }
        for budget in extended["planned_proposal_budget"].values():
            budget["scene_frozen_material_pattern_extension"] = added_proposals
            budget["total"] = int(budget["total"]) + added_proposals
        extension_kind = "scene_frozen_material_pattern_after_active8_jacobian"
    elif selected_profile == JOINT_PROFILE_V30:
        original_final = extended["post_rescan_branch_race"]["final_continuous"]
        original_jacobian = copy.deepcopy(original_final["jacobian"])
        frozen_scene = list(STRUCTURED_SCENE_PARAM_NAMES)
        extended["continuous_after_final_rescan"] = {
            "profile": "material_stage1_v30_v86_1500_extension",
            "strategy": "material_jacobian_cascade",
            "frozen_param_names": frozen_scene,
            "cascade": {
                "profile": "material_v30_v86_scene_frozen_jacobian_pattern",
                "total_max_proposals": 298 + added_proposals,
                "stages": [
                    {
                        "name": "scene_frozen_forward_jacobian",
                        "optimizer": "jacobian",
                        "max_proposals": 298,
                        "minimum_proposals": 0,
                        "switch_score": None,
                        "frozen_param_names": frozen_scene,
                        "jacobian": original_jacobian,
                    },
                    {
                        "name": "scene_frozen_material_pattern_extension",
                        "optimizer": "pattern",
                        "max_proposals": added_proposals,
                        "minimum_proposals": 0,
                        "switch_score": None,
                        "frozen_param_names": frozen_scene,
                        "pattern": {
                            "initial_step_scale": 0.03125,
                            "minimum_step_scale": 0.000244140625,
                            "step_growth": 1.15,
                            "step_shrink": 0.5,
                            "minimum_score_gain": 1.0e-6,
                            "pattern_move_scales": [0.5, 1.0],
                            "active_coordinate_count": 16,
                            "full_refresh_interval": 3,
                        },
                    },
                ],
            },
        }
        budget = extended["planned_proposal_budget"]
        budget["scene_frozen_material_pattern_extension"] = added_proposals
        budget["total"] = int(budget["total"]) + added_proposals
        extension_kind = "scene_frozen_forward_jacobian_then_pattern"
    else:
        raise ValueError(
            "V86 cannot extend an unsupported 1000-budget child profile: "
            f"{selected_profile}"
        )

    return extended, {
        "applied": True,
        "kind": extension_kind,
        "original_max_scored_candidates": original_limit,
        "extended_max_scored_candidates": int(max_scored_candidates),
        "added_optimizer_proposals": added_proposals,
        "scene_coordinates_frozen": True,
        "target_params_visible": False,
        "asset_id_visible": False,
    }


def _configure_v86_high_score_late_common_rescan(
    policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    configured = copy.deepcopy(policy)
    race = configured["post_rescan_branch_race"]
    final_continuous = configured["continuous_after_final_rescan"]
    cascade = final_continuous["cascade"]
    stages = cascade["stages"]
    if len(stages) != 2:
        raise ValueError(
            "V86 high-score late rescan expects the V30 extension to expose "
            "a two-stage final continuous cascade"
        )

    shared_continuous_proposals = 650
    discrete_rescan_proposals = 16
    final_jacobian_proposals = 298
    final_pattern_proposals = 517
    final_proposals = final_jacobian_proposals + final_pattern_proposals

    configured["rescan_at"] = [shared_continuous_proposals]
    configured["max_rescans"] = 1
    configured["restart_continuous_after_rescan"] = True
    race["enabled"] = False
    race.pop("run_at_rescan_counts", None)
    stages[0]["max_proposals"] = final_jacobian_proposals
    stages[1]["max_proposals"] = final_pattern_proposals
    cascade["total_max_proposals"] = final_proposals
    final_continuous["profile"] = (
        "material_stage1_v86_high_late_common_rescan_refine"
    )
    cascade["profile"] = (
        "material_v86_high_late_common_rescan_"
        "scene_frozen_jacobian_pattern"
    )
    configured["planned_proposal_budget"] = {
        "initial_discrete_probes": 15,
        "initial_round_shared_seed_and_probe": 2,
        "shared_continuous_before_final_rescan": shared_continuous_proposals,
        "common_parameter_discrete_rescan": discrete_rescan_proposals,
        "scene_frozen_forward_jacobian_after_final_rescan": (
            final_jacobian_proposals
        ),
        "scene_frozen_material_pattern_after_final_rescan": (
            final_pattern_proposals
        ),
        "total": 1498,
    }
    return configured, {
        "enabled": True,
        "rescan_at": shared_continuous_proposals,
        "candidate_count": discrete_rescan_proposals,
        "comparison_basis": "shared_continuous_params",
        "final_refine_proposals": final_proposals,
        "shared_continuous_warmup_proposals": shared_continuous_proposals,
        "scene_coordinates_frozen": True,
        "target_params_visible": False,
        "asset_id_visible": False,
    }


def _resolve_v86_initial_score_route(
    *,
    policy: dict[str, Any],
    initial_score: float,
    asset_profile: dict[str, Any],
    requested_iterations: int,
    score_metric: str,
    score_width: int,
    score_height: int,
    residual_grid_size: int,
    residual_sketch_size: int,
) -> tuple[str, dict[str, Any], int, str, int, int, int, int, dict[str, Any]]:
    score = float(initial_score)
    if not math.isfinite(score):
        raise ValueError("V86 initial-score routing requires a finite PNG score")
    raw_routes = policy.get("initial_score_strategy_routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("V86 initial-score routing requires configured routes")
    matches = [
        route
        for route in raw_routes
        if score >= float(route["minimum_inclusive"])
        and score < float(route["maximum_exclusive"])
    ]
    if len(matches) != 1:
        raise ValueError(f"V86 initial score {score} matched {len(matches)} routes")
    route = copy.deepcopy(matches[0])
    selected_profile = str(route["budget_profile"])
    selected_policy = _joint_profile_policy(selected_profile)
    parent_limit = _joint_profile_scored_candidate_limit(policy)
    if parent_limit is None:
        raise ValueError("V86 requires a finite scored-candidate limit")
    selected_policy, budget_extension = _extend_v86_child_policy_to_1500(
        selected_profile=selected_profile,
        selected_policy=selected_policy,
        max_scored_candidates=parent_limit,
    )
    for key in (
        "residual_grid_size",
        "residual_sketch_size",
        "discrete_observation_equivalence",
        "proposal_quantization_normalized_step",
    ):
        if key in policy:
            selected_policy[key] = copy.deepcopy(policy[key])
    for key in (
        "discrete_observation_equivalence",
        "proposal_quantization_normalized_step",
        "feedback_score_step",
        "feedback_residual_step",
        "feedback_full_precision_after_final_rescan",
    ):
        if key in route:
            selected_policy[key] = copy.deepcopy(route[key])
    late_common_rescan_report: dict[str, Any] = {}
    if route.get("late_common_state_rescan", False):
        selected_policy, late_common_rescan_report = (
            _configure_v86_high_score_late_common_rescan(selected_policy)
        )
    selected_policy["optimization_score_metric"] = str(route["score_metric"])
    selected_policy["score_width"] = int(route["score_width"])
    selected_policy["score_height"] = int(route["score_height"])
    selected_limit = _joint_profile_scored_candidate_limit(selected_policy)
    selected_iterations = int(requested_iterations)
    if selected_limit is not None:
        selected_iterations = min(selected_iterations, selected_limit - 1)
    (
        selected_metric,
        selected_width,
        selected_height,
        selected_residual_grid,
        selected_residual_sketch,
    ) = _joint_profile_runtime_contract(
        profile=selected_profile,
        policy=selected_policy,
        iterations=selected_iterations,
        score_metric=score_metric,
        score_width=score_width,
        score_height=score_height,
        residual_grid_size=residual_grid_size,
        residual_sketch_size=residual_sketch_size,
    )
    selected_width, selected_height = _optimizer_score_resolution(
        asset_profile,
        requested_width=selected_width,
        requested_height=selected_height,
    )
    reference_width, reference_height = _optimizer_score_resolution(
        asset_profile,
        requested_width=int(route.get("reference_width", selected_width)),
        requested_height=int(route.get("reference_height", selected_height)),
    )
    report = {
        "contract": "material_stage1_initial_png_score_router_v1",
        "profile": JOINT_PROFILE_V86,
        "initial_score": score,
        "route_id": route["route_id"],
        "minimum_inclusive": route["minimum_inclusive"],
        "maximum_exclusive": route["maximum_exclusive"],
        "selected_joint_profile": selected_profile,
        "requested_optimizer_iterations": int(requested_iterations),
        "selected_optimizer_iterations": selected_iterations,
        "selected_max_scored_candidates": selected_limit,
        "budget_extension": budget_extension,
        "selected_score_metric": selected_metric,
        "selected_score_resolution": [selected_width, selected_height],
        "selected_reference_resolution": [reference_width, reference_height],
        "selected_discrete_observation_equivalence": bool(
            selected_policy.get("discrete_observation_equivalence", False)
        ),
        "selected_proposal_quantization_normalized_step": float(
            selected_policy.get("proposal_quantization_normalized_step", 0.0)
        ),
        "selected_feedback_score_step": float(
            selected_policy.get("feedback_score_step", 0.0)
        ),
        "selected_feedback_residual_step": float(
            selected_policy.get("feedback_residual_step", 0.0)
        ),
        "selected_feedback_full_precision_after_final_rescan": bool(
            selected_policy.get(
                "feedback_full_precision_after_final_rescan",
                False,
            )
        ),
        "late_common_state_rescan": late_common_rescan_report,
        "feedback_source": "full_resolution_target_and_original_start_pngs_only",
        "target_params_visible": False,
        "target_discrete_state_visible": False,
        "asset_id_visible": False,
    }
    return (
        selected_profile,
        selected_policy,
        selected_iterations,
        selected_metric,
        selected_width,
        selected_height,
        selected_residual_grid,
        selected_residual_sketch,
        report,
    )


def _joint_profile_policy(profile: str) -> dict[str, Any]:
    return joint_profile_policy(profile)
