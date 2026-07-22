"""Build optimizer configurations for the shared Stage 1 experiment."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Sequence

from material_fit.assets.material_stage1 import MaterialStage1AssetSpec
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.stage1_profiles import JOINT_PROFILE_V86, joint_profile_policy
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.dists_score import DISTS_ALIGNED_RGB_METRIC


STAGE1_SEARCH_PARAM_NAMES = (
    *STRUCTURED_MATERIAL_PARAM_NAMES,
    *STRUCTURED_SCENE_PARAM_NAMES,
)
STAGE1_OPTIMIZATION_SCORE_METRIC = DISTS_ALIGNED_RGB_METRIC
STAGE1_VALIDATION_SCORE_METRIC = phase05.SCORE_METRIC
STAGE1_SCORE_READBACK_WIDTH = 720
STAGE1_SCORE_READBACK_HEIGHT = 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_fit_config(
    *,
    asset: MaterialStage1AssetSpec,
    profile_path: Path,
    run_dir: Path,
    start_material_path: Path,
    target_dir: Path,
    optimizer_start_patch: dict[str, Any] | None = None,
    discrete_candidates: list[dict[str, Any]] | None = None,
    discrete_equivalence_report: dict[str, Any] | None = None,
    start_candidate: dict[str, Any] | None = None,
    discrete_round_widths: tuple[int, ...] = (8, 4, 4),
    discrete_round_budgets: tuple[int, ...] = (64, 160, 320),
    discrete_round_sigmas: tuple[float, ...] = (0.18, 0.10, 0.05),
    target_score: float,
    optimizer: str,
    warmup_iterations: int,
    block_iterations: int,
    block_population_size: int,
    refine_iterations: int,
    node_modules: str | Path | None,
    views: list[dict[str, Any]],
    jacobian_search_scope: str = "all",
    jacobian_difference_mode: str = "central",
    jacobian_solve_mode: str = "full_least_squares",
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
    pattern_initial_grid_points: int = 0,
    pattern_active_coordinate_count: int = 12,
    pattern_full_refresh_interval: int = 4,
    spsa_perturbation_scale: float = 0.01,
    spsa_learning_rate: float = 0.03,
    spsa_directions_per_update: int = 8,
    target_patch: dict[str, Any] | None = None,
    joint_profile: str = JOINT_PROFILE_V86,
    joint_policy_override: dict[str, Any] | None = None,
    optimization_score_metric: str = STAGE1_OPTIMIZATION_SCORE_METRIC,
    browser_score_width: int | None = None,
    browser_score_height: int | None = None,
    residual_grid_size: int = 16,
    residual_sketch_size: int = 128,
    material_only: bool = False,
    search_param_names_override: Sequence[str] | None = None,
) -> dict[str, Any]:
    if optimizer_start_patch is None:
        optimizer_start_patch = target_patch
    if optimizer_start_patch is None:
        raise ValueError("Stage 1 fit config requires an optimizer start material patch")
    discrete_candidates = list(discrete_candidates or [])
    discrete_equivalence_report = copy.deepcopy(discrete_equivalence_report or {})
    config = phase05._build_fit_config(
        asset=asset.phase05_spec(target_material_path=start_material_path),
        profile_path=profile_path,
        run_dir=run_dir,
        start_material_path=start_material_path,
        target_dir=target_dir,
        target_defines=optimizer_start_patch["defines"],
        target_render_states=optimizer_start_patch["render_states"],
        target_score=target_score,
        node_modules=node_modules,
        views=views,
    )
    config["search_param_names"] = list(
        STRUCTURED_MATERIAL_PARAM_NAMES if material_only else STAGE1_SEARCH_PARAM_NAMES
    )
    config["search_param_space"] = (
        "structured_material_single_view_40_v1"
        if material_only
        else "structured_material_stage1_40_plus_6_v1"
    )
    if search_param_names_override is not None:
        allowed = set(
            STRUCTURED_MATERIAL_PARAM_NAMES
            if material_only
            else STAGE1_SEARCH_PARAM_NAMES
        )
        requested = list(
            dict.fromkeys(str(name) for name in search_param_names_override)
        )
        invalid = sorted(set(requested) - allowed)
        if invalid or not requested:
            raise ValueError(
                "invalid explicit Stage 1 search parameter names: "
                f"{invalid or requested}"
            )
        config["search_param_names"] = requested
        config["search_param_space"] = "controlled_known_perturbation_subset_v1"
    config["optimizer"] = optimizer
    browser_score = config["laya_capture"]["browser_score"]
    browser_score["residual_grid_size"] = min(
        max(int(residual_grid_size), 1),
        32,
    )
    browser_score["residual_sketch_size"] = min(
        max(int(residual_sketch_size), 16),
        256,
    )
    if optimizer == "cma_cold":
        if not 0.0 < float(cma_sigma) <= 1.0:
            raise ValueError("cma_sigma must be in (0, 1]")
        config["cma_es"] = {
            "mode": "cold",
            "population_size": max(int(cma_population_size), 2),
            "sigma": float(cma_sigma),
            "seed": int(cma_seed),
            "hint_bias_mix_ratio": 0.0,
            "allow_scene_lighting": True,
        }
    profile_payload = _read_json(profile_path)
    render_width = int(profile_payload.get("width", STAGE1_SCORE_READBACK_WIDTH))
    render_height = int(profile_payload.get("height", STAGE1_SCORE_READBACK_HEIGHT))
    score_width = (
        int(browser_score_width)
        if browser_score_width is not None
        else render_width
    )
    score_height = (
        int(browser_score_height)
        if browser_score_height is not None
        else render_height
    )
    config["laya_capture"]["browser_score"].update(
        {
            "metric": optimization_score_metric,
            "readback_width": score_width,
            "readback_height": score_height,
            "render_width": score_width,
            "render_height": score_height,
        }
    )
    if optimizer == "material_stage1_hybrid":
        config["material_stage1_hybrid"] = {
            "profile": "material_stage1_hybrid_v3_scene_frozen_local_jacobian",
            "block_order": ["rim", "specular", "tone_shadow", "base_surface"],
            "warmup_iterations": max(int(warmup_iterations), 1),
            "block_iterations": max(int(block_iterations), 1),
            "refine_iterations": max(int(refine_iterations), 1),
            "late_scene_realign_iterations": 256,
            "late_material_polish_iterations": 800,
            "late_realign_trigger_score": 0.985,
            "local_jacobian_iterations": 800,
            "local_jacobian_trigger_score": 0.995,
            "population_size": max(int(block_population_size), 2),
            "sigma_scale": 1.0,
            "seed": 20260714,
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
        }
    if optimizer == "material_discrete_joint":
        if not discrete_candidates or start_candidate is None:
            raise ValueError("material_discrete_joint requires a target-independent legal state space")
        joint_policy = (
            copy.deepcopy(joint_policy_override)
            if joint_policy_override is not None
            else joint_profile_policy(joint_profile)
        )
        if "continuous" not in joint_policy:
            raise ValueError(
                "material_discrete_joint requires a materialized V86 child policy"
            )
        continuous_policy = copy.deepcopy(joint_policy["continuous"])
        continuous_policy.update(
            {
                "population_size": max(int(block_population_size), 2),
                "seed": 20260714,
                "feedback_source": "target_png_score_and_signed_residuals_only",
                "target_params_visible": False,
            }
        )
        equivalence_groups = discrete_equivalence_report.get("groups", [])
        initial_candidate_ids = [
            str(group["representative_candidate_id"])
            for group in equivalence_groups
            if isinstance(group, dict) and group.get("representative_candidate_id")
        ]
        if not initial_candidate_ids:
            initial_candidate_ids = [
                str(candidate["candidate_id"])
                for candidate in discrete_candidates
            ]
        config["material_discrete_joint"] = {
            "profile": joint_policy["runtime_profile"],
            "budget_profile": joint_profile,
            "candidates": copy.deepcopy(discrete_candidates),
            "discrete_observation_equivalence": discrete_equivalence_report,
            "initial_candidate_ids": initial_candidate_ids,
            "start_candidate": copy.deepcopy(start_candidate),
            "round_widths": list(
                joint_policy.get("round_widths", discrete_round_widths)
            ),
            "round_budgets": list(
                joint_policy.get("round_budgets", discrete_round_budgets)
            ),
            "round_sigmas": list(
                joint_policy.get("round_sigmas", discrete_round_sigmas)
            ),
            "round_seed_mode": str(
                joint_policy.get("round_seed_mode", "shared_best")
            ),
            "conditional_activation_probes": copy.deepcopy(
                joint_policy.get("conditional_activation_probes", [])
            ),
            "activation_selects_initial_winner": bool(
                joint_policy.get("activation_selects_initial_winner", False)
            ),
            "activation_commits_initial_seed": bool(
                joint_policy.get("activation_commits_initial_seed", False)
            ),
            "skip_initial_discrete_probes_when_activation_selects": bool(
                joint_policy.get(
                    "skip_initial_discrete_probes_when_activation_selects",
                    False,
                )
            ),
            "population_size": max(int(block_population_size), 2),
            "branch_strategy": joint_policy.get("branch_strategy", "cmaes"),
            "branch_jacobian": copy.deepcopy(joint_policy.get("branch_jacobian", {})),
            "winner_continuation_budget": int(
                joint_policy.get("winner_continuation_budget", 0)
            ),
            "winner_continuation_sigma": joint_policy.get(
                "winner_continuation_sigma"
            ),
            "diversity_rounds": int(joint_policy["diversity_rounds"]),
            "rescan_interval": int(joint_policy["rescan_interval"]),
            "rescan_at": list(joint_policy.get("rescan_at", ())),
            "rescan_switch_min_margin_after_first": float(
                joint_policy.get(
                    "rescan_switch_min_margin_after_first",
                    0.0,
                )
            ),
            "rescan_candidate_modes": list(
                joint_policy.get("rescan_candidate_modes", ())
            ),
            "rescan_browser_score_overrides": copy.deepcopy(
                joint_policy.get("rescan_browser_score_overrides", ())
            ),
            "minimum_final_refine_proposals": int(
                joint_policy.get("minimum_final_refine_proposals", 0)
            ),
            "initial_score_rescan_schedule": copy.deepcopy(
                joint_policy.get("initial_score_rescan_schedule", {})
            ),
            "max_rescans": int(joint_policy["max_rescans"]),
            "restart_continuous_after_rescan": bool(
                joint_policy.get("restart_continuous_after_rescan", False)
            ),
            "restart_continuous_after_first_rescan": bool(
                joint_policy.get("restart_continuous_after_first_rescan", False)
            ),
            "continuous_after_final_rescan": copy.deepcopy(
                joint_policy.get("continuous_after_final_rescan", {})
            ),
            "max_scored_candidates": joint_policy.get("max_scored_candidates"),
            "planned_proposal_budget": copy.deepcopy(
                joint_policy.get("planned_proposal_budget", {})
            ),
            "initial_continuous_warmup": copy.deepcopy(
                joint_policy.get("initial_continuous_warmup", {})
            ),
            "post_rescan_branch_race": copy.deepcopy(
                joint_policy.get("post_rescan_branch_race", {})
            ),
            "post_rescan_axis_response_scan": copy.deepcopy(
                joint_policy.get("post_rescan_axis_response_scan", {})
            ),
            "seed": 20260714,
            "continuous": continuous_policy,
            "feedback_score_step": float(
                joint_policy.get("feedback_score_step", 0.0)
            ),
            "feedback_residual_step": float(
                joint_policy.get("feedback_residual_step", 0.0)
            ),
            "feedback_residual_projection_size": int(
                joint_policy.get("feedback_residual_projection_size", 0)
            ),
            "feedback_full_precision_after_final_rescan": bool(
                joint_policy.get(
                    "feedback_full_precision_after_final_rescan",
                    False,
                )
            ),
            "feedback_quantization_start_continuous_proposals": int(
                joint_policy.get(
                    "feedback_quantization_start_continuous_proposals",
                    0,
                )
            ),
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_discrete_state_visible": False,
            "target_continuous_params_visible": False,
        }
        proposal_quantization_step = float(
            joint_policy.get("proposal_quantization_normalized_step", 0.0)
        )
        if proposal_quantization_step > 0.0:
            config["proposal_quantization_normalized_step"] = (
                proposal_quantization_step
            )
        for name in (
            "proposal_quantization_pre_final_normalized_step",
            "proposal_quantization_post_final_normalized_step",
        ):
            if name in joint_policy:
                config["material_discrete_joint"][name] = float(
                    joint_policy[name]
                )
    if optimizer == "material_block_hybrid":
        config["material_block_hybrid"] = {
            "profile": "material_block_hybrid_stage1_v1",
            "block_order": ["rim", "specular", "tone_shadow", "base_surface"],
            "block_iterations": max(int(block_iterations), 1),
            "population_size": max(int(block_population_size), 2),
            "sigma_scale": 1.0,
            "seed": 20260714,
            "refine_enabled": True,
            "refine_regularization_weight": 0.02,
            "refine_scene_alignment_rounds": 4,
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
        }
    if search_param_names_override is None and optimizer in {
        "cma_cold",
        "fish_spsa",
        "material_coordinate_pattern",
        "material_inverse_surrogate",
        "material_jacobian_trust_region",
        "material_secant_trust_region",
    }:
        if jacobian_search_scope == "scene":
            config["search_param_names"] = list(STRUCTURED_SCENE_PARAM_NAMES)
            config["search_param_space"] = "structured_material_stage1_scene_only_v1"
        elif jacobian_search_scope == "material":
            config["search_param_names"] = list(STRUCTURED_MATERIAL_PARAM_NAMES)
            config["search_param_space"] = "structured_material_stage1_material_only_v1"
        elif jacobian_search_scope != "all":
            raise ValueError(f"invalid continuous search scope: {jacobian_search_scope}")
    if optimizer == "material_jacobian_trust_region":
        config["material_jacobian_trust_region"] = {
            "profile": "material_jacobian_trust_region_stage1_local_v2",
            "difference_mode": str(jacobian_difference_mode),
            "solve_mode": str(jacobian_solve_mode),
            "acceptance_objective": str(jacobian_acceptance_objective),
            "score_feature_weight": max(float(jacobian_score_feature_weight), 0.0),
            "maximum_score_drop": max(float(jacobian_maximum_score_drop), 0.0),
            "active_coordinate_count": max(int(jacobian_active_coordinate_count), 0),
            "full_refresh_interval": max(int(jacobian_full_refresh_interval), 0),
            "accept_improving_probes": bool(jacobian_accept_improving_probes),
            "minimum_probe_score_gain": max(
                float(jacobian_minimum_probe_score_gain),
                0.0,
            ),
            "shader_default_anchor_enabled": False,
            "probe_step": 0.006,
            "minimum_probe_step": 0.001,
            "ridge": 0.005,
            "trust_radius": 0.04,
            "maximum_trust_radius": 0.10,
            "max_axis_update": 0.08,
            "line_search_scales": [1.0, 0.5, 0.25, 0.125],
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
        }
    if optimizer == "material_secant_trust_region":
        config["material_secant_trust_region"] = {
            "profile": "material_secant_trust_region_stage1_v2_local_hadamard",
            "design_size": 64,
            "antithetic": False,
            "probe_radius": 0.02,
            "minimum_probe_radius": 0.003,
            "maximum_probe_radius": 0.08,
            "radius_growth": 1.20,
            "radius_shrink": 0.70,
            "ridge": 0.0001,
            "trust_radius": 0.12,
            "max_axis_update": 0.25,
            "score_feature_weight": 20.0,
            "maximum_score_drop": 0.01,
            "line_search_scales": [1.0, 0.75, 0.5, 0.25, 0.125],
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
        }
    if optimizer == "material_inverse_surrogate":
        config["material_inverse_surrogate"] = {
            "profile": "material_inverse_surrogate_stage1_v1",
            "sample_count": 512,
            "local_probe_radius": 0.10,
            "global_radii": [0.08, 0.16, 0.32, 0.55],
            "feature_count": 256,
            "feature_selection": "correlation",
            "hidden_features": 128,
            "ridge_values": [0.001, 0.01, 0.1],
            "random_feature_scales": [0.35, 0.75, 1.5],
            "prediction_blend_scales": [0.5, 1.0, 1.5],
            "max_model_cycles": 1,
            "seed": 20260721,
            "feedback_source": "target_png_signed_residuals_only",
            "target_params_visible": False,
        }
    if optimizer == "material_coordinate_pattern":
        if discrete_candidates and start_candidate is None:
            raise ValueError("material_coordinate_pattern candidates require a start state")
        pattern_config = {
            "profile": "mixed_coordinate_pattern_stage1_v2",
            "initial_step_scale": float(pattern_initial_step_scale),
            "initial_grid_points": max(int(pattern_initial_grid_points), 0),
            "minimum_step_scale": 1.0 / 512.0,
            "step_growth": 1.20,
            "step_shrink": 0.5,
            "minimum_score_gain": 1.0e-7,
            "active_coordinate_count": max(int(pattern_active_coordinate_count), 0),
            "full_refresh_interval": max(int(pattern_full_refresh_interval), 0),
            "hard_state_refresh_interval": 4,
            "feedback_source": "target_png_score_only",
            "target_params_visible": False,
            "target_discrete_state_visible": False,
        }
        if discrete_candidates:
            pattern_config["candidates"] = copy.deepcopy(discrete_candidates)
            pattern_config["start_candidate"] = copy.deepcopy(start_candidate)
        config["material_coordinate_pattern"] = pattern_config
    if optimizer == "fish_spsa":
        config["fish_spsa"] = {
            "seed": 20260715,
            "perturbation_scale": float(spsa_perturbation_scale),
            "learning_rate": float(spsa_learning_rate),
            "directions_per_update": max(int(spsa_directions_per_update), 1),
            "reject_patience": 4,
            "reject_decay": 0.5,
            "feedback_source": "target_png_score_only",
            "target_params_visible": False,
        }
    active_names = set(config["search_param_names"])
    active_scene_count = sum(name in active_names for name in STRUCTURED_SCENE_PARAM_NAMES)
    active_material_count = sum(
        coordinate.param_name in active_names
        for coordinate in STRUCTURED_MATERIAL_ONLY_COORDINATES
    )
    contract = {
        "phase": (
            "single_view_material_fit" if material_only else "human_reference_stage1"
        ),
        "asset_independent": True,
        "material_coordinate_count": active_material_count,
        "scene_coordinate_count": active_scene_count,
        "scene_coordinates_searchable": active_scene_count > 0,
        "scene_coordinates_frozen_from_original_start": material_only,
        "known_perturbation_search_subset": search_param_names_override is not None,
        "discrete_render_state": (
            "searched_from_original_start"
            if (
                optimizer == "material_discrete_joint"
                or (optimizer == "material_coordinate_pattern" and bool(discrete_candidates))
            )
            else "copied_from_target_before_optimizer_start"
        ),
        "target_discrete_state_visible_to_optimizer": False,
        "target_params_visible_to_optimizer": False,
        "feedback_source": "target_png_score_and_signed_residuals_only",
        "runtime_optimizer_id": optimizer,
        "optimization_score_metric": optimization_score_metric,
        "validation_score_metric": STAGE1_VALIDATION_SCORE_METRIC,
        "artifact_score_metric": "cross_engine_material_score_v3",
    }
    config["structured_material_contract"] = copy.deepcopy(contract)
    config["material_jacobian_trust_region_contract"] = copy.deepcopy(contract)
    config["stage1_optimizer_contract"] = copy.deepcopy(contract)
    return config
