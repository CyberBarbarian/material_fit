"""Single-view policy shared by Phase 0.5, Stage 1, and Stage 2."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from material_fit.experiments.stage1_fit_config import (
    STAGE1_OPTIMIZATION_SCORE_METRIC,
)
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_METRIC,
    DISTS_ALIGNED_RGB_V3_METRIC,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)


_POLICY_FILE = "single_view_unified.json"
_POLICY_SHA256 = "cf7ecfd35f757d270d89509119fe850c3defa52912b1012a62796ee1f03f31fd"
_SCENE_POLICY_FILE = "single_view_scene_searchable.json"
_SCENE_POLICY_SHA256 = "43215ec972f4ecbf4c244a069b5e2e3525f4a8dcc47dbef597b5a53b3dacf7a2"
_POLICY_CONTRACT = "material_fit_single_view_v86_policy_adaptation_v51"
_MATERIAL_ONLY_FINAL_BUDGET = 892
_SCENE_SEARCHABLE_FINAL_BUDGET = 250


def adapt_v86_policy_for_material_only(
    policy: dict[str, Any],
    *,
    optimization_score_metric: str = STAGE1_OPTIMIZATION_SCORE_METRIC,
    scene_searchable: bool = False,
    initial_score: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the frozen target-blind single-view policy and its audit report."""

    source_runtime_profile = str(
        policy.get("runtime_profile") or policy.get("profile") or "unknown"
    )
    adapted = _load_policy_snapshot(_POLICY_FILE, _POLICY_SHA256)
    adapted["profile"] = (
        "material_discrete_joint_v86_budget1500_single_view_unified_v51"
    )
    adapted["runtime_profile"] = str(adapted["profile"])
    acceptance_score_metric = str(optimization_score_metric)
    adapted["optimization_score_metric"] = acceptance_score_metric
    adapted["max_scored_candidates"] = 1500
    adapted["discrete_observation_equivalence"] = True
    adapted["target_discrete_state_visible"] = False
    adapted["target_continuous_params_visible"] = False
    adapted["feedback_source"] = "target_png_score_and_signed_residuals_only"
    for probe in adapted.get("conditional_activation_probes", []):
        probe["feedback_source"] = "online_target_png_score_only"
        probe["target_params_visible"] = False
    _configure_scene_scope(adapted, scene_searchable=scene_searchable)
    if not scene_searchable:
        _set_material_only_planned_budget(adapted)

    final = adapted["continuous_after_final_rescan"]
    final_budget = (
        _SCENE_SEARCHABLE_FINAL_BUDGET
        if scene_searchable
        else _MATERIAL_ONLY_FINAL_BUDGET
    )
    hard_state_method = (
        "all_legal_hard_state_activation_probe_then_common_parameter_rescan"
        if scene_searchable
        else "target_blind_continuous_warmup_then_common_parameter_rescan"
    )
    representative_count = 16 if scene_searchable else 6
    warmup_proposals = int(
        adapted.get("initial_continuous_warmup", {}).get("max_proposals", 0)
    )
    initial_optimization_score_metric = str(
        adapted["optimization_score_metric"]
    )
    report = {
        "contract": _POLICY_CONTRACT,
        "source_runtime_profile": source_runtime_profile,
        "adapted_runtime_profile": adapted["profile"],
        "selected_child_profile": adapted["budget_profile"],
        "unified_child_budget_extension": {
            "applied": True,
            "kind": "hard_state_rescan_then_joint_and_scene_frozen_refine",
            "original_max_scored_candidates": 1000,
            "extended_max_scored_candidates": 1500,
            "added_optimizer_proposals": 500,
            "scene_coordinates_frozen_before_final_material_refine": True,
            "target_params_visible": False,
            "asset_id_visible": False,
        },
        "snapshot_file": _POLICY_FILE,
        "snapshot_sha256": _POLICY_SHA256,
        "scene_policy_snapshot_file": (
            _SCENE_POLICY_FILE if scene_searchable else None
        ),
        "scene_policy_snapshot_sha256": (
            _SCENE_POLICY_SHA256 if scene_searchable else None
        ),
        "selected_child_policy_preserved": False,
        "optimization_score_metric": initial_optimization_score_metric,
        "initial_optimization_score_metric": initial_optimization_score_metric,
        "acceptance_score_metric": acceptance_score_metric,
        "objective_changes_during_search": bool(scene_searchable),
        "runtime_score_override": (
            {
                "after_continuous_proposals": 1200,
                "metric": acceptance_score_metric,
                "reset_global_score_domain": True,
            }
            if scene_searchable
            else None
        ),
        "single_view_spatial_residual_override": False,
        "target_information_used": False,
        "target_params_visible": False,
        "target_discrete_state_visible": False,
        "asset_id_used": False,
        "initial_score": initial_score,
        "continuation_route": (
            "inverse_search_then_acceptance_polish"
            if scene_searchable
            else "fixed_target_blind_unified"
        ),
        "hard_state_selection": {
            "method": (
                hard_state_method
            ),
            "legal_candidate_count": 16,
            "observational_representative_count": representative_count,
            "target_params_visible": False,
        },
        "scene_coordinates_searchable": bool(scene_searchable),
        "scene_coordinates_searchable_stage": (
            "pre_rescan_dedicated_scene_and_post_rescan_joint_then_frozen_material"
            if scene_searchable
            else None
        ),
        "scene_coordinates_frozen_before_material_refine": True,
        "scene_coordinate_names": list(STRUCTURED_SCENE_PARAM_NAMES),
        "material_coordinate_count": len(STRUCTURED_MATERIAL_PARAM_NAMES),
        "scene_coordinate_count": len(STRUCTURED_SCENE_PARAM_NAMES),
        "joint_coordinate_count": (
            len(STRUCTURED_MATERIAL_PARAM_NAMES)
            + len(STRUCTURED_SCENE_PARAM_NAMES)
        ),
        "hard_state_frozen_before_final_continuous_refine": True,
        "initial_continuous_warmup_proposals": warmup_proposals,
        "rescan_at": list(adapted["rescan_at"]),
        "rescan_candidate_modes": list(adapted["rescan_candidate_modes"]),
        "post_rescan_branch_race_enabled": bool(
            adapted["post_rescan_branch_race"]["enabled"]
        ),
        "final_refiner": str(final["strategy"]),
        "final_refine_proposals": final_budget,
        "planned_proposal_budget": copy.deepcopy(
            adapted["planned_proposal_budget"]
        ),
    }
    return adapted, report


def _load_policy_snapshot(file_name: str, expected_sha256: str) -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "stage1_v86"
        / file_name
    )
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"single-view policy snapshot hash mismatch for {path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    return copy.deepcopy(json.loads(raw.decode("utf-8")))


def _configure_scene_scope(
    policy: dict[str, Any],
    *,
    scene_searchable: bool,
) -> None:
    frozen = [] if scene_searchable else list(STRUCTURED_SCENE_PARAM_NAMES)
    policy["initial_continuous_warmup"]["frozen_param_names"] = list(frozen)

    if scene_searchable:
        scene_policy = _load_policy_snapshot(
            _SCENE_POLICY_FILE,
            _SCENE_POLICY_SHA256,
        )
        policy["continuous"] = copy.deepcopy(scene_policy["continuous"])
        policy["continuous"]["frozen_param_names"] = []
        policy["continuous_after_final_rescan"] = copy.deepcopy(
            scene_policy["continuous_after_final_rescan"]
        )
        policy["continuous_after_final_rescan"]["frozen_param_names"] = []
        _configure_v45_scene_schedule(policy)
    else:
        policy["continuous"]["frozen_param_names"] = list(frozen)
        policy["continuous_after_final_rescan"]["frozen_param_names"] = list(
            STRUCTURED_SCENE_PARAM_NAMES
        )

    race = policy.get("post_rescan_branch_race")
    if isinstance(race, dict):
        race["frozen_param_names"] = list(frozen)
        final_continuous = race.get("final_continuous")
        if isinstance(final_continuous, dict):
            final_continuous["frozen_param_names"] = list(frozen)


def _configure_v45_scene_schedule(policy: dict[str, Any]) -> None:
    policy["budget_profile"] = "v85_budget1500_v4_portfolio_scene_refine"
    policy["discrete_observation_equivalence"] = False
    policy["conditional_activation_probes"] = [
        {
            "name": "rim_and_normal_hard_state_response",
            "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
            "normalized_values": [0.3],
            "only_if_all_at_lower_bound": True,
            "feedback_source": "online_target_png_score_only",
            "target_params_visible": False,
        }
    ]
    policy["activation_selects_initial_winner"] = True
    policy["activation_commits_initial_seed"] = True
    policy["skip_initial_discrete_probes_when_activation_selects"] = True
    policy["initial_continuous_warmup"] = {}
    historical_final = copy.deepcopy(policy["continuous_after_final_rescan"])
    between_rescans = _cascade_with_budgets(
        historical_final,
        budgets=(734, 100),
        profile="material_stage1_single_view_v51_inverse_continuation",
    )
    final_acceptance = _cascade_with_budgets(
        historical_final,
        budgets=(200, 50),
        profile="material_stage1_single_view_v51_acceptance_polish",
    )
    policy["continuous_after_final_rescan"] = final_acceptance
    policy["rescan_at"] = [366, 1200]
    policy["rescan_candidate_modes"] = ["all", "all"]
    policy["rescan_browser_score_overrides"] = [
        {},
        {"metric": DISTS_ALIGNED_RGB_METRIC},
    ]
    policy["minimum_final_refine_proposals"] = 250
    policy["initial_score_rescan_schedule"] = {}
    policy["max_rescans"] = 2
    policy["restart_continuous_after_rescan"] = True
    policy["restart_continuous_after_first_rescan"] = True
    policy["post_rescan_branch_race"] = {
        "enabled": False,
        "final_continuous": between_rescans,
    }
    policy["post_rescan_axis_response_scan"] = {}
    policy["feedback_score_step"] = 0.0
    policy["feedback_residual_step"] = 0.0
    policy["feedback_residual_projection_size"] = 0
    policy["feedback_full_precision_after_final_rescan"] = True
    policy["feedback_quantization_start_continuous_proposals"] = 0
    policy["optimization_score_metric"] = DISTS_ALIGNED_RGB_V3_METRIC
    policy["planned_proposal_budget"] = {
        "initial_activation_probes": 16,
        "initial_round_seed": 1,
        "initial_inverse_continuous": 366,
        "first_common_parameter_discrete_rescan": 16,
        "inverse_continuation": 834,
        "acceptance_metric_common_parameter_rescan": 16,
        "acceptance_polish": 250,
        "total": 1499,
    }


def _cascade_with_budgets(
    config: dict[str, Any],
    *,
    budgets: tuple[int, int],
    profile: str,
) -> dict[str, Any]:
    result = copy.deepcopy(config)
    stages = result["cascade"]["stages"]
    if len(stages) != 2:
        raise ValueError("scene-searchable continuation requires two cascade stages")
    for stage, budget in zip(stages, budgets, strict=True):
        stage["max_proposals"] = int(budget)
        stage["minimum_proposals"] = int(budget)
    result["cascade"]["total_max_proposals"] = int(sum(budgets))
    result["cascade"]["profile"] = f"{profile}_cascade"
    result["profile"] = profile
    return result


def _set_material_only_planned_budget(policy: dict[str, Any]) -> None:
    schedule = {
        "initial_continuous_warmup": 110,
        "hard_state_activation_and_round": 8,
        "first_continuous_refine": 110,
        "first_common_hard_state_rescan": 6,
        "second_continuous_refine": 366,
        "second_common_hard_state_rescan": 6,
        "final_continuous_refine": _MATERIAL_ONLY_FINAL_BUDGET,
        "total": 1498,
    }
    policy["planned_proposal_budget"] = {
        "high_initial_score_path": copy.deepcopy(schedule),
        "low_initial_score_path": copy.deepcopy(schedule),
    }


__all__ = ["adapt_v86_policy_for_material_only"]
