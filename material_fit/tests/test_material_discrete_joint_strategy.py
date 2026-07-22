from __future__ import annotations

import math

import pytest

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_discrete_joint_strategy import (
    MaterialDiscreteJointStrategy,
    _quantize_optimizer_feedback,
)
from material_fit.optimizer.material_discrete_space import (
    BROWSER_SCORE_OVERRIDE_PARAM,
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    split_discrete_candidate,
)
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def _space() -> tuple[list[dict], dict, dict]:
    start_patch = {
        "defines": {
            "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
            "enabled": ["NORMALMAP_Y_INVERT"],
        },
        "render_states": {"s_BlendSrc": 1},
    }
    candidates = build_legal_discrete_candidates(start_patch)
    start = next(
        row
        for row in candidates
        if row["defines"]["enabled"] == ["NORMALMAP_Y_INVERT"]
        and row["render_states"]["s_BlendSrc"] == 1
    )
    target = next(
        row
        for row in candidates
        if row["defines"]["enabled"] == ["NORMALMAP", "RIMSMOOTHNESS"]
        and row["render_states"]["s_BlendSrc"] == 0
    )
    return candidates, start, target


def _context(iteration: int, params: dict, target_id: str) -> StrategyContext:
    _continuous, candidate = split_discrete_candidate(params)
    assert candidate is not None
    axes = candidate["axes"]
    score = 0.95 if candidate["candidate_id"] == target_id else 0.30
    score += 0.01 if axes["normal_mode"] == "normal" else 0.0
    score += 0.005 if axes["rim_smooth"] else 0.0
    return StrategyContext(
        iteration=iteration,
        current_params=params,
        analysis={
            "browser_score": {
                "metric": "cross_engine_foreground_components_v3",
                "fit_score": score,
                "views": [
                    {
                        "view_id": "v000_yaw0_pitch0",
                        "fit_score": score,
                        "material_components": {
                            "foreground_rgb": score,
                            "detail_texture": score - 0.01,
                        },
                    }
                ],
            },
            "structured_residual_features": {
                "profile": "synthetic_discrete",
                "features": [1.0 - score, 0.0],
            }
        },
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=params),
    )


def test_successive_halving_observes_all_states_before_selecting_winner() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [2],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "continuous": {
                "warmup_iterations": 1,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )

    current = initial
    shared_seeds: list[dict] = []
    for iteration in range(24):
        current, decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        nested = decision.get("material_discrete_joint", {}).get("nested", {})
        if nested.get("stage", {}).get("name") == "material_discrete_joint_shared_seed":
            continuous, _candidate = split_discrete_candidate(current)
            shared_seeds.append(continuous)
        if strategy.research_summary()["winner_candidate_id"] is not None:
            break

    summary = strategy.research_summary()
    branch_scores = {
        row["candidate_id"]: row["best_fit_score"] for row in summary["branches"]
    }
    assert len(branch_scores) == 16
    assert all(score > float("-inf") for score in branch_scores.values())
    assert summary["winner_candidate_id"] == target["candidate_id"]
    assert summary["target_discrete_state_visible"] is False
    assert summary["target_continuous_params_visible"] is False
    target_summary = next(
        row for row in summary["branches"] if row["candidate_id"] == target["candidate_id"]
    )["observable_score_summary"]
    assert target_summary["metric"] == "cross_engine_foreground_components_v3"
    assert target_summary["component_means"]["foreground_rgb"] == 0.965
    assert target_summary["component_means"]["detail_texture"] == 0.955
    assert len(shared_seeds) == 2
    assert shared_seeds[0] == shared_seeds[1]


def test_initial_continuous_warmup_precedes_hard_state_search() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "initial_continuous_warmup": {
                "enabled": True,
                "max_proposals": 2,
                "strategy": "material_coordinate_pattern",
                "pattern": {"active_coordinate_count": 1},
            },
        },
    )

    assert strategy.allows_target_distance_stop() is True
    current = initial
    warmup_phases: list[str] = []
    for iteration in range(2):
        current, decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        _continuous, candidate = split_discrete_candidate(current)
        assert candidate is not None
        assert candidate["candidate_id"] == start["candidate_id"]
        warmup_phases.append(decision["material_discrete_joint"]["phase"])

    current, decision = strategy.propose(
        _context(2, current, target["candidate_id"])
    )
    summary = strategy.research_summary()

    assert warmup_phases == [
        "initial_continuous_warmup",
        "initial_continuous_warmup",
    ]
    assert decision["material_discrete_joint"]["phase"] == "discrete_probe"
    assert summary["initial_continuous_warmup"] == {
        "enabled": True,
        "max_proposals": 2,
        "proposals": 2,
        "completed": True,
        "stop_reason": "budget_exhausted",
        "strategy": "material_coordinate_pattern",
        "target_information_used": False,
        "start_hard_state_only": True,
    }
    assert strategy.allows_target_distance_stop() is False


@pytest.mark.parametrize(
    ("initial_score", "expected_route", "expected_rescan"),
    [
        (0.90, "at_or_above", [150]),
        (0.80, "below", [110]),
    ],
)
def test_initial_online_score_routes_the_rescan_schedule(
    initial_score: float,
    expected_route: str,
    expected_rescan: list[int],
) -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "rescan_at": [110],
            "initial_score_rescan_schedule": {
                "threshold": 0.85,
                "at_or_above": [150],
                "below": [110],
            },
        },
    )
    context = StrategyContext(
        iteration=0,
        current_params=initial,
        analysis={},
        diff_score=1.0 - initial_score,
        fit_score=initial_score,
        state=AdjustmentState(best_params=initial),
    )

    strategy.propose(context)
    summary = strategy.research_summary()

    assert summary["rescan_at"] == expected_rescan
    assert summary["initial_score_rescan_schedule"] == {
        "initial_fit_score": initial_score,
        "threshold": 0.85,
        "route": expected_route,
        "rescan_at": expected_rescan,
        "feedback_source": "initial_online_target_png_score_only",
        "target_params_visible": False,
    }


def test_strategy_factory_builds_joint_discrete_strategy() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 1.0, "u_Saturation": 1.0},
        start,
    )
    strategy = build_strategy(
        optimizer="material_discrete_joint",
        initial_params=initial,
        shader_params=_shader_params(),
        policies=(),
        unity_material_params=None,
        search_param_names=["u_GammaPower", "u_Saturation"],
        material_discrete_joint_config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [2],
            "round_budgets": [1],
            "round_sigmas": [0.05],
        },
    )

    assert isinstance(strategy, MaterialDiscreteJointStrategy)


def test_optimizer_feedback_quantization_collapses_renderer_scale_noise() -> None:
    params = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    state = AdjustmentState(best_params=params)
    contexts = [
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={
                "structured_residual_features": {
                    "features": [0.12342, -0.22241, 0.0],
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=state,
        )
        for score in (0.7328115542990835, 0.7328115752252184)
    ]
    contexts[1].analysis["structured_residual_features"]["features"] = [
        0.12349,
        -0.22238,
        0.00021,
    ]

    left, left_audit = _quantize_optimizer_feedback(
        contexts[0],
        score_step=1.0e-6,
        residual_step=1.0e-3,
    )
    right, right_audit = _quantize_optimizer_feedback(
        contexts[1],
        score_step=1.0e-6,
        residual_step=1.0e-3,
    )

    assert left.fit_score == right.fit_score == pytest.approx(0.732812)
    assert left.diff_score == right.diff_score == pytest.approx(0.267188)
    assert left.analysis["structured_residual_features"]["features"] == [
        0.123,
        -0.222,
        0.0,
    ]
    assert left.analysis == right.analysis
    assert left_audit["enabled"] is True
    assert right_audit["maximum_residual_delta"] <= 0.0005


def test_optimizer_feedback_can_project_high_dimensional_residuals() -> None:
    params = {"u_GammaPower": 1.0}
    context = StrategyContext(
        iteration=0,
        current_params=params,
        analysis={
            "structured_residual_features": {
                "features": [float(index) / 100.0 for index in range(64)],
            }
        },
        diff_score=0.2,
        fit_score=0.8,
        state=AdjustmentState(best_params=params),
    )

    projected, audit = _quantize_optimizer_feedback(
        context,
        score_step=1.0e-6,
        residual_step=1.0e-4,
        residual_projection_size=8,
    )

    features = projected.analysis["structured_residual_features"]["features"]
    assert len(features) == 8
    assert all(isinstance(value, float) for value in features)
    assert audit["original_residual_count"] == 64
    assert audit["projected_residual_count"] == 8
    assert audit["residual_projection_size"] == 8


def test_feedback_quantization_disables_after_final_rescan() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "max_rescans": 2,
            "feedback_score_step": 1.0e-6,
            "feedback_residual_step": 1.0e-3,
            "feedback_full_precision_after_final_rescan": True,
            "proposal_quantization_pre_final_normalized_step": 0.001,
            "proposal_quantization_post_final_normalized_step": 0.0001,
        },
    )

    _candidate, before_decision = strategy.propose(
        _context(0, initial, target["candidate_id"])
    )
    before = strategy.research_summary()["feedback_quantization"]
    assert before["enabled"] is True
    assert before["final_rescan_complete"] is False
    assert before_decision["proposal_quantization_normalized_step"] == pytest.approx(
        0.001
    )

    strategy._rescan_count = strategy._max_rescans
    _candidate, after_decision = strategy.propose(
        _context(1, initial, target["candidate_id"])
    )
    after = strategy.research_summary()["feedback_quantization"]
    assert after["enabled"] is False
    assert after_decision["proposal_quantization_normalized_step"] == pytest.approx(
        0.0001
    )
    assert after["score_step"] == 0.0
    assert after["residual_step"] == 0.0
    assert after["configured_score_step"] == pytest.approx(1.0e-6)
    assert after["configured_residual_step"] == pytest.approx(1.0e-3)
    assert after["final_rescan_complete"] is True


def test_feedback_quantization_can_start_after_continuous_warmup() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "feedback_score_step": 1.0e-6,
            "feedback_residual_step": 1.0e-3,
            "feedback_quantization_start_continuous_proposals": 2,
        },
    )

    strategy.propose(_context(0, initial, target["candidate_id"]))
    before = strategy.research_summary()["feedback_quantization"]
    assert before["enabled"] is False
    assert before["quantization_started"] is False
    assert before["continuous_proposals"] == 0
    assert before["quantization_start_continuous_proposals"] == 2

    strategy._continuous_proposals = 2
    strategy.propose(_context(1, initial, target["candidate_id"]))
    after = strategy.research_summary()["feedback_quantization"]
    assert after["enabled"] is True
    assert after["quantization_started"] is True
    assert after["continuous_proposals"] == 2
    assert after["score_step"] == pytest.approx(1.0e-6)
    assert after["residual_step"] == pytest.approx(1.0e-3)


def test_joint_continuous_refine_can_freeze_named_coordinates_for_jacobian() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "max_rescans": 0,
            "continuous": {
                "strategy": "material_jacobian_trust_region",
                "frozen_param_names": ["u_GammaPower"],
                "jacobian": {
                    "difference_mode": "central",
                    "shader_default_anchor_enabled": False,
                },
            },
        },
    )

    current = initial
    for iteration in range(32):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if summary["phase"] == "continuous_refine" and summary["continuous"]:
            break

    summary = strategy.research_summary()
    assert summary["continuous_strategy"] == "material_jacobian_trust_region"
    assert summary["continuous"]["coordinate_count"] == 1
    assert summary["continuous"]["difference_mode"] == "central"


def test_joint_branch_race_can_use_target_blind_forward_jacobians() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [4],
            "round_budgets": [2],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 1,
            "rescan_interval": 0,
            "max_rescans": 0,
            "branch_strategy": "material_jacobian_trust_region",
            "branch_jacobian": {
                "difference_mode": "forward",
                "shader_default_anchor_enabled": False,
            },
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 1,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )

    current = initial
    for iteration in range(80):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if summary["winner_candidate_id"] is not None:
            break

    summary = strategy.research_summary()
    assert summary["branch_strategy"] == "material_jacobian_trust_region"
    assert summary["winner_candidate_id"] == target["candidate_id"]
    assert summary["round_summaries"][0]["budget_per_candidate"] == 2


def test_joint_can_continue_the_observed_winner_without_restarting_cma() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "max_rescans": 0,
            "winner_continuation_budget": 3,
            "winner_continuation_sigma": 0.03,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 1,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )

    current = initial
    for iteration in range(80):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if summary["phase"] == "continuous_refine":
            break

    summary = strategy.research_summary()
    assert summary["winner_candidate_id"] == target["candidate_id"]
    assert summary["winner_continuation_budget"] == 3
    assert summary["winner_continuation_sigma"] == 0.03
    assert summary["winner_continuation_proposals"] == 3


def test_periodic_rescan_can_replace_the_provisional_hard_state() -> None:
    candidates, start, provisional = _space()
    replacement = next(
        row
        for row in candidates
        if row["axes"]["normal_mode"] == "normal_y_invert"
        and row["axes"]["rim_smooth"] is True
        and row["axes"]["blend_src"] == 0
    )
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 1,
            "max_rescans": 1,
            "continuous": {
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )

    current = initial
    for iteration in range(80):
        _continuous, candidate = split_discrete_candidate(current)
        assert candidate is not None
        rescan_active = strategy.research_summary()["phase"] == "discrete_rescan"
        preferred_id = (
            replacement["candidate_id"] if rescan_active else provisional["candidate_id"]
        )
        score = 0.98 if candidate["candidate_id"] == preferred_id else 0.30
        context = StrategyContext(
            iteration=iteration,
            current_params=current,
            analysis={
                "structured_residual_features": {
                    "profile": "synthetic_discrete_rescan",
                    "features": [1.0 - score, 0.0],
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=AdjustmentState(best_params=current),
        )
        current, _decision = strategy.propose(context)
        summary = strategy.research_summary()
        if summary["rescan_count"] == 1:
            break

    summary = strategy.research_summary()
    assert summary["rescan_count"] == 1
    assert summary["winner_candidate_id"] == replacement["candidate_id"]
    assert summary["rescan_summaries"][0]["winner_changed"] is True
    assert (
        summary["rescan_summaries"][0]["winner_candidate_id"]
        == replacement["candidate_id"]
    )


@pytest.mark.parametrize(
    ("replacement_score", "previous_score", "expected_switch"),
    [
        (0.870836, 0.870652, False),
        (0.929879, 0.908354, True),
    ],
)
def test_later_rescan_switch_requires_configured_score_margin(
    replacement_score: float,
    previous_score: float,
    expected_switch: bool,
) -> None:
    candidates, start, previous = _space()
    replacement = next(
        row
        for row in candidates
        if row["axes"]["normal_mode"] == "flat"
        and row["axes"]["rim_smooth"] is True
        and row["axes"]["blend_src"] == 0
    )
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_switch_min_margin_after_first": 0.002,
            "continuous": {
                "warmup_iterations": 1,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )
    continuous, _candidate = split_discrete_candidate(initial)
    strategy._winner_id = previous["candidate_id"]
    strategy._rescan_count = 1
    strategy._rescan_params = continuous
    strategy._rescan_candidate_ids = [
        previous["candidate_id"],
        replacement["candidate_id"],
    ]
    strategy._rescan_scores = {
        previous["candidate_id"]: previous_score,
        replacement["candidate_id"]: replacement_score,
    }
    strategy._rescan_analyses = {
        previous["candidate_id"]: {},
        replacement["candidate_id"]: {},
    }
    strategy._pending_branch_id = None

    strategy._finish_rescan(
        StrategyContext(
            iteration=0,
            current_params=initial,
            analysis={},
            diff_score=1.0 - previous_score,
            fit_score=previous_score,
            state=AdjustmentState(best_params=initial),
        )
    )

    summary = strategy.research_summary()
    rescan = summary["rescan_summaries"][-1]
    expected_id = (
        replacement["candidate_id"]
        if expected_switch
        else previous["candidate_id"]
    )
    assert summary["winner_candidate_id"] == expected_id
    assert rescan["observed_winner_candidate_id"] == replacement["candidate_id"]
    assert rescan["switch_suppressed"] is (not expected_switch)
    assert rescan["winner_margin"] == pytest.approx(
        replacement_score - previous_score
    )


def test_post_rescan_race_adapts_one_candidate_per_normal_mode() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 1,
            "max_rescans": 1,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axis": "normal_mode",
                "width": 4,
                "budget_per_candidate": 2,
                "sigma": 0.05,
                "frozen_param_names": ["u_GammaPower"],
                "final_continuous": {
                    "structured_only": True,
                    "frozen_param_names": ["u_GammaPower"],
                    "warmup_iterations": 1,
                    "block_iterations": 1,
                    "refine_iterations": 1,
                    "late_scene_realign_iterations": 1,
                    "late_material_polish_iterations": 1,
                    "local_jacobian_iterations": 1,
                },
            },
        },
    )

    current = initial
    race_candidate_ids: set[str] = set()
    for iteration in range(100):
        current, decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        joint_decision = decision.get("material_discrete_joint", {})
        if joint_decision.get("phase") == "post_rescan_branch_race":
            race_candidate_ids.add(str(joint_decision["candidate_id"]))
        summary = strategy.research_summary()
        if (
            summary["post_rescan_branch_race"]["completed"]
            and summary["phase"] == "continuous_refine"
        ):
            break

    summary = strategy.research_summary()
    race = summary["post_rescan_branch_race"]
    rows = race["summaries"][0]["candidates"]
    assert race["completed"] is True
    assert race["adaptive_fallback_applied"] is False
    assert race["frozen_param_names"] == ["u_GammaPower"]
    assert len(rows) == len(race_candidate_ids) == 4
    assert {row["axes"]["normal_mode"] for row in rows} == {
        "flat",
        "normal",
        "normal_y_invert",
        "legacy_y_invert_only",
    }
    assert all(row["proposals"] == 2 for row in rows)
    assert summary["winner_candidate_id"] == target["candidate_id"]
    assert summary["target_discrete_state_visible"] is False
    assert summary["target_continuous_params_visible"] is False


def test_post_rescan_race_can_be_scheduled_only_after_final_rescan() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_at": [1, 3],
            "max_rescans": 2,
            "restart_continuous_after_rescan": True,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "post_rescan_branch_race": {
                "enabled": True,
                "run_at_rescan_counts": [2],
                "group_axis": "normal_mode",
                "width": 4,
                "budget_per_candidate": 1,
                "sigma": 0.05,
                "final_continuous": {
                    "structured_only": True,
                    "warmup_iterations": 1,
                    "block_iterations": 1,
                    "refine_iterations": 1,
                    "late_scene_realign_iterations": 1,
                    "late_material_polish_iterations": 1,
                    "local_jacobian_iterations": 1,
                },
            },
        },
    )

    current = initial
    race_rescan_counts: list[int] = []
    for iteration in range(160):
        current, decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        joint = decision.get("material_discrete_joint", {})
        if joint.get("phase") == "post_rescan_branch_race":
            race_rescan_counts.append(int(joint["rescan_count"]))
        summary = strategy.research_summary()
        if summary["post_rescan_branch_race"]["completed"]:
            break

    summary = strategy.research_summary()
    assert summary["rescan_count"] == 2
    assert summary["post_rescan_branch_race"]["run_at_rescan_counts"] == [2]
    assert race_rescan_counts
    assert set(race_rescan_counts) == {2}
    assert len(summary["post_rescan_branch_race"]["summaries"]) == 1


def test_post_rescan_axis_response_scan_disambiguates_a_coupled_hard_state() -> None:
    candidates, start, target = _space()
    shader_params = [
        *_shader_params(),
        ShaderParam(
            "u_NormalScale",
            "Range",
            default=0.0,
            range_min=0.0,
            range_max=1.5,
        ),
    ]
    initial = attach_discrete_candidate(
        {
            "u_GammaPower": 0.7,
            "u_Saturation": 1.4,
            "u_NormalScale": 0.0,
        },
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=["u_GammaPower", "u_Saturation", "u_NormalScale"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 1,
            "max_rescans": 1,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "post_rescan_branch_race": {
                "enabled": False,
                "final_continuous": {
                    "structured_only": True,
                    "warmup_iterations": 1,
                    "block_iterations": 1,
                    "refine_iterations": 2,
                    "late_scene_realign_iterations": 1,
                    "late_material_polish_iterations": 1,
                    "local_jacobian_iterations": 1,
                },
            },
            "post_rescan_axis_response_scan": {
                "enabled": True,
                "group_axis": "normal_mode",
                "param_name": "u_NormalScale",
                "values": [0.0, 0.3, 0.6, 0.9, 1.2],
                "fixed_axes_from_rescan_winner": ["rim_smooth", "blend_src"],
                "continuous_seed_mode": "common_rescan",
                "activation_tiebreak": {
                    "enabled": True,
                    "minimum_response_range": 0.0001,
                    "maximum_peak_score_gap": 0.0005,
                    "require_peak_above_minimum_probe": True,
                },
            },
        },
    )

    def context(iteration: int, params: dict) -> StrategyContext:
        continuous, candidate = split_discrete_candidate(params)
        assert candidate is not None
        axes = candidate["axes"]
        normal_scale = float(continuous["u_NormalScale"])
        mode = axes["normal_mode"]
        if mode == "flat":
            score = 0.90
        elif mode == "normal":
            score = 0.8995 + 0.00045 * max(
                1.0 - abs(normal_scale - 0.6) / 0.6,
                0.0,
            )
        else:
            score = 0.89
        score += 0.01 if axes["rim_smooth"] else 0.0
        score += 0.005 if axes["blend_src"] == 0 else 0.0
        return StrategyContext(
            iteration=iteration,
            current_params=params,
            analysis={
                "browser_score": {
                    "metric": "cross_engine_foreground_components_v3",
                    "fit_score": score,
                    "views": [
                        {
                            "view_id": "v000_yaw0_pitch0",
                            "fit_score": score,
                            "material_components": {"detail_texture": score},
                        }
                    ],
                },
                "structured_residual_features": {
                    "profile": "synthetic_axis_response",
                    "features": [1.0 - score, 0.0],
                },
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=AdjustmentState(best_params=params),
        )

    current = initial
    for iteration in range(100):
        current, _decision = strategy.propose(context(iteration, current))
        summary = strategy.research_summary()
        if (
            summary["post_rescan_axis_response_scan"]["completed"]
            and summary["phase"] == "continuous_refine"
        ):
            break

    summary = strategy.research_summary()
    scan = summary["post_rescan_axis_response_scan"]
    scan_summary = scan["summaries"][0]
    assert scan["completed"] is True
    assert scan_summary["probe_count"] == 20
    assert scan_summary["raw_peak_winner_candidate_id"].startswith("normal=flat|")
    assert scan_summary["winner_candidate_id"] == target["candidate_id"]
    assert scan_summary["winner_param_value"] == pytest.approx(0.6)
    assert scan_summary["selection_reason"] == "responsive_near_peak_candidate"
    assert scan_summary["continuous_seed_mode"] == "common_rescan"
    assert scan_summary["continuous_seed_param_value"] == pytest.approx(
        summary["rescan_summaries"][0]["common_continuous_params"]["u_NormalScale"]
    )
    assert summary["winner_candidate_id"] == target["candidate_id"]
    assert scan_summary["target_params_visible"] is False
    flat = next(
        row
        for row in scan_summary["candidates"]
        if row["axes"]["normal_mode"] == "flat"
    )
    normal = next(
        row
        for row in scan_summary["candidates"]
        if row["axes"]["normal_mode"] == "normal"
    )
    assert flat["response_range"] == pytest.approx(0.0)
    assert normal["response_range"] > 0.0001
    assert normal["best_fit_score"] < flat["best_fit_score"]
    assert normal["activation_tiebreak_eligible"] is True


def test_post_rescan_race_can_cover_normal_and_rim_with_jacobian() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 1,
            "max_rescans": 1,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth"],
                "width": 8,
                "budget_per_candidate": 1,
                "strategy": "material_jacobian_trust_region",
                "jacobian": {
                    "difference_mode": "forward",
                    "shader_default_anchor_enabled": False,
                },
                "final_continuous": {
                    "structured_only": True,
                    "warmup_iterations": 1,
                    "block_iterations": 1,
                    "refine_iterations": 1,
                    "late_scene_realign_iterations": 1,
                    "late_material_polish_iterations": 1,
                    "local_jacobian_iterations": 1,
                },
            },
        },
    )

    current = initial
    for iteration in range(120):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if (
            summary["post_rescan_branch_race"]["completed"]
            and summary["phase"] == "continuous_refine"
        ):
            break

    race = strategy.research_summary()["post_rescan_branch_race"]
    rows = race["summaries"][0]["candidates"]
    assert race["group_axes"] == ["normal_mode", "rim_smooth"]
    assert race["strategy"] == "material_jacobian_trust_region"
    assert len(rows) == 8
    assert {
        (row["axes"]["normal_mode"], row["axes"]["rim_smooth"])
        for row in rows
    } == {
        (normal_mode, rim_smooth)
        for normal_mode in ("flat", "normal", "normal_y_invert", "legacy_y_invert_only")
        for rim_smooth in (False, True)
    }
    assert all(row["proposals"] == 1 for row in rows)


def test_adaptive_post_rescan_fallback_uses_eight_branches_then_four_state_rescan() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "population_size": 4,
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "rescan_at": [1],
            "max_rescans": 2,
            "restart_continuous_after_rescan": True,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "sigma": 0.05,
                "final_continuous": {
                    "structured_only": True,
                    "warmup_iterations": 100,
                    "block_iterations": 1,
                    "refine_iterations": 1,
                    "late_scene_realign_iterations": 1,
                    "late_material_polish_iterations": 1,
                    "local_jacobian_iterations": 1,
                },
                "adaptive_fallback": {
                    "trigger_axis": "normal_mode",
                    "preferred_value": "normal",
                    "group_axes": ["normal_mode", "rim_smooth"],
                    "width": 8,
                    "budget_per_candidate": 1,
                    "strategy": "material_jacobian_trust_region",
                    "jacobian": {
                        "difference_mode": "forward",
                        "shader_default_anchor_enabled": False,
                    },
                    "final_continuous": {
                        "strategy": "material_jacobian_trust_region",
                        "jacobian": {
                            "difference_mode": "forward",
                            "shader_default_anchor_enabled": False,
                        },
                    },
                    "final_grouped_rescan": {
                        "enabled": True,
                        "group_axes": ["normal_mode"],
                        "after_continuous_proposals": 3,
                        "apply_browser_score_override_to_rescan": False,
                        "browser_score_override": {
                            "metric": "cross_engine_foreground_components_v4",
                        },
                    },
                },
            },
        },
    )

    current = initial
    observed_score_overrides: list[dict] = []
    grouped_rescan_used_override: list[bool] = []
    shared_state = AdjustmentState(
        best_score=0.01,
        best_params=current,
        best_fit_score=0.99,
        best_fit_params=current,
    )
    for iteration in range(120):
        if isinstance(current.get(BROWSER_SCORE_OVERRIDE_PARAM), dict):
            observed_score_overrides.append(current[BROWSER_SCORE_OVERRIDE_PARAM])
        _continuous, candidate = split_discrete_candidate(current)
        assert candidate is not None
        summary = strategy.research_summary()
        if summary["phase"] == "discrete_rescan" and summary["rescan_count"] == 1:
            grouped_rescan_used_override.append(
                isinstance(current.get(BROWSER_SCORE_OVERRIDE_PARAM), dict)
            )
        axes = candidate["axes"]
        if summary["phase"] == "discrete_rescan" and summary["rescan_count"] == 1:
            score = 0.99 if axes["normal_mode"] == "normal" else 0.80
        else:
            score = 0.95 if axes["normal_mode"] == "normal_y_invert" else 0.85
            score += 0.01 if axes["rim_smooth"] else 0.0
        context = StrategyContext(
            iteration=iteration,
            current_params=current,
            analysis={
                "structured_residual_features": {
                    "profile": "synthetic_adaptive_discrete",
                    "features": [1.0 - score, 0.0],
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=shared_state,
        )
        current, _decision = strategy.propose(context)
        if isinstance(current.get(BROWSER_SCORE_OVERRIDE_PARAM), dict):
            observed_score_overrides.append(current[BROWSER_SCORE_OVERRIDE_PARAM])
        if strategy.research_summary()["rescan_count"] == 2:
            break

    summary = strategy.research_summary()
    race = summary["post_rescan_branch_race"]
    assert race["adaptive_fallback_applied"] is True
    assert race["adaptive_trigger"]["observed_value"] == "normal_y_invert"
    assert race["group_axes"] == ["normal_mode", "rim_smooth"]
    assert len(race["summaries"][0]["candidates"]) == 8
    assert summary["rescan_count"] == 2
    final_rescan = summary["rescan_summaries"][1]
    assert final_rescan["group_axes"] == ["normal_mode"]
    assert final_rescan["candidate_count"] == 4
    assert summary["phase"] == "continuous_refine"
    assert summary["continuous"]["profile"] == "material_jacobian_trust_region_v1"
    assert observed_score_overrides
    assert grouped_rescan_used_override and not any(grouped_rescan_used_override)
    assert {
        override["metric"] for override in observed_score_overrides
    } == {"cross_engine_foreground_components_v4"}
    assert shared_state.best_score == float("inf")
    assert shared_state.best_fit_score == float("-inf")
    assert shared_state.best_params == {}
    assert shared_state.best_fit_params == {}
    assert {row["axes"]["normal_mode"] for row in final_rescan["candidates"]} == {
        "flat",
        "normal",
        "normal_y_invert",
        "legacy_y_invert_only",
    }
    winner_id = summary["winner_candidate_id"]
    winner = next(row for row in candidates if row["candidate_id"] == winner_id)
    assert winner["axes"]["normal_mode"] == "normal"


def test_adaptive_post_rescan_fallback_treats_a_narrow_preferred_lead_as_ambiguous() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "adaptive_fallback": {
                    "trigger_axis": "normal_mode",
                    "preferred_value": "normal",
                    "minimum_preferred_margin": 0.0002,
                    "group_axes": ["normal_mode", "rim_smooth"],
                    "width": 8,
                    "budget_per_candidate": 1,
                    "ambiguous_preferred": {
                        "group_axes": ["normal_mode"],
                        "width": 4,
                        "budget_per_candidate": 3,
                        "final_grouped_rescan": {"enabled": False},
                    },
                },
            },
        },
    )
    scores = {}
    for candidate in candidates:
        normal_mode = candidate["axes"]["normal_mode"]
        scores[candidate["candidate_id"]] = {
            "normal": 0.90010,
            "normal_y_invert": 0.90000,
            "flat": 0.88,
            "legacy_y_invert_only": 0.87,
        }[normal_mode]

    strategy._select_post_rescan_race_policy(scores)

    trigger = strategy.research_summary()["post_rescan_branch_race"]["adaptive_trigger"]
    assert trigger["observed_value"] == "normal"
    assert trigger["best_competing_value"] == "normal_y_invert"
    assert trigger["preferred_margin"] == pytest.approx(0.0001)
    assert trigger["ambiguous_preferred_winner"] is True
    race = strategy.research_summary()["post_rescan_branch_race"]
    assert trigger["fallback_variant"] == "ambiguous_preferred_winner"
    assert race["adaptive_fallback_applied"] is True
    assert race["group_axes"] == ["normal_mode"]
    assert race["width"] == 4
    assert race["budget_per_candidate"] == 3


def test_post_rescan_cma_seeds_are_stable_by_hard_state_not_score_rank() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "seed": 100,
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "strategy": "cmaes",
            },
        },
    )
    scores = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        scores[candidate["candidate_id"]] = {
            "flat": 0.99,
            "legacy_y_invert_only": 0.98,
            "normal_y_invert": 0.97,
            "normal": 0.96,
        }[mode] + (0.01 if candidate["axes"]["rim_smooth"] else 0.0)
    analyses = {candidate_id: {} for candidate_id in scores}

    strategy._start_post_rescan_branch_race(
        common_params={"u_GammaPower": 0.7, "u_Saturation": 1.4},
        scores=scores,
        analyses=analyses,
    )

    seeds = {
        strategy._branches[candidate_id].candidate["axes"]["normal_mode"]:
        strategy._branches[candidate_id].race_seed
        for candidate_id in strategy._active_ids
    }
    assert seeds == {
        "normal": 12100,
        "normal_y_invert": 12101,
        "flat": 12102,
        "legacy_y_invert_only": 12103,
    }


def test_post_rescan_branch_race_can_use_initial_and_common_continuous_seeds() -> None:
    candidates, start, target = _space()
    initial_continuous = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
    common_continuous = {"u_GammaPower": 1.7, "u_Saturation": 0.4}
    initial = attach_discrete_candidate(initial_continuous, start)
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                "width": 1,
                "budget_per_candidate": 2,
                "strategy": "material_jacobian_trust_region",
                "continuous_seed_modes": ["initial", "common_rescan"],
                "jacobian": {
                    "difference_mode": "forward",
                    "shader_default_anchor_enabled": False,
                },
            },
        },
    )
    scores = {
        candidate["candidate_id"]: (
            0.9 if candidate["candidate_id"] == target["candidate_id"] else 0.1
        )
        for candidate in candidates
    }
    analyses = {
        candidate_id: {
            "structured_residual_features": {
                "profile": "synthetic_discrete",
                "features": [1.0 - score, 0.0],
            }
        }
        for candidate_id, score in scores.items()
    }
    strategy._start_post_rescan_branch_race(
        common_params=common_continuous,
        scores=scores,
        analyses=analyses,
    )

    current = initial
    for iteration in range(8):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        if strategy.research_summary()["post_rescan_branch_race"]["summaries"]:
            break

    race = strategy.research_summary()["post_rescan_branch_race"]
    candidate_summary = race["summaries"][0]["candidates"][0]
    assert race["continuous_seed_modes"] == ["initial", "common_rescan"]
    assert candidate_summary["proposals"] == 2
    assert candidate_summary["continuous_seed_history"] == [
        {
            "source": "initial",
            "proposal_start": 0,
            "seed_evaluation_required": True,
        },
        {
            "source": "common_rescan",
            "proposal_start": 1,
            "seed_evaluation_required": False,
        },
    ]


def test_post_rescan_race_prioritizes_png_activation_and_uses_rank_budgets() -> None:
    candidates, start, target = _space()
    initial_continuous = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(initial_continuous, start),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_activation", "rim_smooth"],
                "width": 4,
                "budget_per_candidate": 1,
                "ranking_signal": "conditional_activation_peak",
                "allocation_order": "ranked_sequential",
                "budgets_by_rank": [2, 1, 1, 1],
                "strategy": "cmaes",
            },
        },
    )
    scores = {
        candidate["candidate_id"]: (
            0.2 if candidate["candidate_id"] == target["candidate_id"] else 0.8
        )
        for candidate in candidates
    }
    strategy._conditional_activation_results = [
        {
            "probe_name": "rim_response_activation",
            "normalized_value": 0.5,
            "candidate_id": candidate["candidate_id"],
            "fit_score": (
                0.95 if candidate["candidate_id"] == target["candidate_id"] else 0.4
            ),
        }
        for candidate in candidates
    ]

    strategy._start_post_rescan_branch_race(
        common_params=initial_continuous,
        scores=scores,
        analyses={candidate_id: {} for candidate_id in scores},
    )

    assert strategy._active_ids[0] == target["candidate_id"]
    first = strategy._next_post_rescan_branch()
    assert first is not None
    assert first.candidate_id == target["candidate_id"]
    assert strategy._post_rescan_branch_budget_limit(first) == 2
    first.proposals = 2
    second = strategy._next_post_rescan_branch()
    assert second is not None
    assert second.candidate_id != target["candidate_id"]
    assert strategy._post_rescan_branch_budget_limit(second) == 1
    evidence = strategy._post_rescan_ranking_evidence[target["candidate_id"]]
    assert evidence["source"] == "conditional_activation_peak"
    assert evidence["fit_score"] == pytest.approx(0.95)


def test_post_rescan_activation_ranking_falls_back_to_rescan_score() -> None:
    candidates, start, target = _space()
    initial_continuous = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(initial_continuous, start),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                "width": 1,
                "budget_per_candidate": 1,
                "ranking_signal": "conditional_activation_peak",
            },
        },
    )
    scores = {
        candidate["candidate_id"]: (
            0.95 if candidate["candidate_id"] == target["candidate_id"] else 0.2
        )
        for candidate in candidates
    }

    strategy._start_post_rescan_branch_race(
        common_params=initial_continuous,
        scores=scores,
        analyses={candidate_id: {} for candidate_id in scores},
    )

    assert strategy._active_ids == [target["candidate_id"]]
    evidence = strategy._post_rescan_ranking_evidence[target["candidate_id"]]
    assert evidence == {"source": "rescan_score", "fit_score": 0.95}


def test_post_rescan_activation_ranking_does_not_mix_missing_rows_with_rescan() -> None:
    candidates, start, target = _space()
    initial_continuous = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(initial_continuous, start),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_activation", "rim_smooth"],
                "width": 4,
                "budget_per_candidate": 1,
                "ranking_signal": "conditional_activation_peak",
            },
        },
    )
    unobserved_high_rescan = next(
        candidate
        for candidate in candidates
        if candidate["candidate_id"] != target["candidate_id"]
        and candidate["axes"]["rim_smooth"]
    )
    scores = {
        candidate["candidate_id"]: (
            0.99
            if candidate["candidate_id"] == unobserved_high_rescan["candidate_id"]
            else 0.2
        )
        for candidate in candidates
    }
    strategy._conditional_activation_results = [
        {
            "probe_name": "rim_response_activation",
            "normalized_value": 0.5,
            "candidate_id": target["candidate_id"],
            "fit_score": 0.7,
        }
    ]
    assert strategy._post_rescan_branch_ranking_score(
        strategy._branches[unobserved_high_rescan["candidate_id"]],
        scores,
    ) == -math.inf

    strategy._start_post_rescan_branch_race(
        common_params=initial_continuous,
        scores=scores,
        analyses={candidate_id: {} for candidate_id in scores},
    )

    assert strategy._active_ids[0] == target["candidate_id"]


def test_activation_score_can_select_initial_continuous_winner() -> None:
    candidates, start, target = _space()
    initial_continuous = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(initial_continuous, start),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "initial_candidate_ids": [
                start["candidate_id"],
                target["candidate_id"],
            ],
            "activation_selects_initial_winner": True,
            "round_widths": [2],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "continuous": {
                "strategy": "material_coordinate_pattern",
                "pattern": {"active_coordinate_count": 1},
            },
        },
    )
    start_branch = strategy._branches[start["candidate_id"]]
    target_branch = strategy._branches[target["candidate_id"]]
    start_branch.best_score = 0.95
    start_branch.selection_score = 0.5
    target_branch.best_score = 0.75
    target_branch.selection_score = 0.8
    strategy._active_ids = [start["candidate_id"], target["candidate_id"]]
    strategy._conditional_activation_results = [
        {
            "probe_name": "rim_response_activation",
            "normalized_value": 0.5,
            "candidate_id": target["candidate_id"],
            "fit_score": 0.8,
        }
    ]

    strategy._start_continuous_refine()

    assert strategy.research_summary()["winner_candidate_id"] == target["candidate_id"]


def test_activation_selection_can_skip_redundant_raw_discrete_probes() -> None:
    candidates, start, target = _space()
    initial_continuous = {
        "u_GammaPower": 0.7,
        "u_Saturation": 1.4,
        "u_RimIntensity": 0.0,
        "u_RimWidth": 0.0,
    }
    shader_params = [
        *_shader_params(),
        ShaderParam("u_RimIntensity", "Float", default=0.0),
        ShaderParam("u_RimWidth", "Float", default=0.0),
    ]
    initial = attach_discrete_candidate(initial_continuous, start)
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=list(initial_continuous),
        config={
            "candidates": candidates,
            "start_candidate": start,
            "initial_candidate_ids": [
                start["candidate_id"],
                target["candidate_id"],
            ],
            "activation_selects_initial_winner": True,
            "skip_initial_discrete_probes_when_activation_selects": True,
            "conditional_activation_probes": [
                {
                    "name": "rim_response_activation",
                    "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
                    "normalized_values": [0.5],
                    "only_if_all_at_lower_bound": True,
                }
            ],
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
        },
    )

    _candidate, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=initial,
            analysis={},
            diff_score=0.2,
            fit_score=0.8,
            state=AdjustmentState(),
        )
    )

    assert decision["stage"]["name"] == (
        "material_discrete_joint_conditional_activation_probe"
    )
    summary = strategy.research_summary()
    assert summary["conditional_activation"]["skips_initial_discrete_probes"] is True
    assert strategy._probed_ids == {
        start["candidate_id"],
        target["candidate_id"],
    }


def test_initial_warmup_rebases_conditional_activation_probes() -> None:
    candidates, start, target = _space()
    initial_continuous = {
        "u_GammaPower": 0.7,
        "u_Saturation": 1.4,
        "u_RimIntensity": 0.0,
        "u_RimWidth": 0.0,
    }
    shader_params = [
        *_shader_params(),
        ShaderParam("u_RimIntensity", "Float", default=0.0),
        ShaderParam("u_RimWidth", "Float", default=0.0),
    ]
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(initial_continuous, start),
        shader_params=shader_params,
        search_param_names=list(initial_continuous),
        config={
            "candidates": candidates,
            "start_candidate": start,
            "initial_candidate_ids": [
                start["candidate_id"],
                target["candidate_id"],
            ],
            "conditional_activation_probes": [
                {
                    "name": "rim_response_activation",
                    "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
                    "normalized_values": [0.25, 0.5],
                    "only_if_all_at_lower_bound": True,
                }
            ],
            "initial_continuous_warmup": {
                "enabled": True,
                "max_proposals": 1,
                "strategy": "material_coordinate_pattern",
                "pattern": {"active_coordinate_count": 1},
            },
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
        },
    )
    warm_seed = attach_discrete_candidate(
        {
            **initial_continuous,
            "u_GammaPower": 1.3,
        },
        start,
    )
    strategy._branches[start["candidate_id"]].best_params = warm_seed

    strategy._finish_initial_continuous_warmup("budget_exhausted")

    assert strategy.research_summary()["conditional_activation"][
        "rebased_after_initial_warmup"
    ] is True
    assert strategy._conditional_activation_queue
    for probe in strategy._conditional_activation_queue:
        assert probe["params"]["u_GammaPower"] == pytest.approx(1.3)
        for coordinate_id in ("u_RimIntensity", "u_RimWidth"):
            coordinate = strategy._coordinates_by_id[coordinate_id]
            expected = coordinate.low + probe["normalized_value"] * (
                coordinate.high - coordinate.low
            )
            assert probe["params"][coordinate_id] == pytest.approx(expected)


def test_post_rescan_skips_branch_race_for_a_confident_visual_state_tier() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 10,
                "strategy": "cmaes",
                "skip_race_if_score_margin_at_least": 0.005,
                "confident_score_tie_tolerance": 1.0e-8,
                "confident_winner_continuous": {
                    "strategy": "material_coordinate_pattern",
                    "pattern": {"active_coordinate_count": 1},
                },
            },
        },
    )
    mode_scores = {
        "flat": 0.95,
        "legacy_y_invert_only": 0.95,
        "normal": 0.93,
        "normal_y_invert": 0.92,
    }
    scores = {
        candidate["candidate_id"]: mode_scores[candidate["axes"]["normal_mode"]]
        for candidate in candidates
    }

    strategy._start_post_rescan_branch_race(
        common_params={"u_GammaPower": 0.7, "u_Saturation": 1.4},
        scores=scores,
        analyses={candidate_id: {} for candidate_id in scores},
    )

    race = strategy.research_summary()["post_rescan_branch_race"]
    assert strategy._phase == "continuous_refine"
    assert race["completed"] is True
    assert race["summaries"][0]["skipped_due_to_confident_margin"] is True
    assert race["summaries"][0]["confidence_margin"] == pytest.approx(0.02)
    assert race["summaries"][0]["winner_candidate_id"].startswith("normal=flat|")


def test_post_rescan_race_prefers_simpler_hard_state_within_score_tolerance() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "prefer_lower_complexity_within_score": 0.002,
            },
        },
    )
    representatives = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        representatives.setdefault(mode, candidate)
    scores = {
        "flat": 0.95745,
        "legacy_y_invert_only": 0.95745,
        "normal": 0.95877,
        "normal_y_invert": 0.954,
    }
    strategy._active_ids = []
    for mode, score in scores.items():
        branch = strategy._branches[representatives[mode]["candidate_id"]]
        branch.best_score = score
        branch.best_params = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
        strategy._active_ids.append(branch.candidate_id)

    strategy._finish_post_rescan_branch_race(
        _context(0, strategy._best_params, start["candidate_id"])
    )

    summary = strategy.research_summary()["post_rescan_branch_race"]["summaries"][0]
    assert summary["raw_winner_candidate_id"] == representatives["normal"]["candidate_id"]
    assert summary["winner_candidate_id"] == representatives["flat"]["candidate_id"]
    assert summary["complexity_regularization"]["changed_winner"] is True


def test_post_rescan_group_representative_prefers_simpler_near_tie() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["rim_smooth"],
                "width": 2,
                "budget_per_candidate": 1,
                "prefer_lower_complexity_within_score": 0.002,
            },
        },
    )
    rim_off = [
        branch
        for branch in strategy._branches.values()
        if branch.candidate["axes"]["rim_smooth"] is False
        and branch.candidate["axes"]["blend_src"] == 0
    ]
    scores = {
        branch.candidate_id: {
            "flat": 0.909,
            "legacy_y_invert_only": 0.908,
            "normal": 0.907,
            "normal_y_invert": 0.910,
        }[branch.candidate["axes"]["normal_mode"]]
        for branch in rim_off
    }

    selected = strategy._post_rescan_group_representative(rim_off, scores)

    assert selected.candidate["axes"]["normal_mode"] == "flat"


def test_post_rescan_normal_activation_groups_equivalent_normal_modes() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
        },
    )
    grouped = {}
    for branch in strategy._branches.values():
        key = (
            strategy._post_rescan_group_axis_value(branch, "normal_activation"),
            strategy._post_rescan_group_axis_value(branch, "rim_smooth"),
        )
        grouped.setdefault(key, set()).add(
            branch.candidate["axes"]["normal_mode"]
        )

    assert grouped[(False, False)] == {"flat", "legacy_y_invert_only"}
    assert grouped[(True, False)] == {"normal", "normal_y_invert"}
    assert len(grouped) == 4


def test_post_rescan_race_keeps_materially_better_complex_hard_state() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "prefer_lower_complexity_within_score": 0.002,
            },
        },
    )
    representatives = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        representatives.setdefault(mode, candidate)
    scores = {
        "flat": 0.957,
        "legacy_y_invert_only": 0.956,
        "normal": 0.961,
        "normal_y_invert": 0.954,
    }
    strategy._active_ids = []
    for mode, score in scores.items():
        branch = strategy._branches[representatives[mode]["candidate_id"]]
        branch.best_score = score
        branch.best_params = {"u_GammaPower": 0.7, "u_Saturation": 1.4}
        strategy._active_ids.append(branch.candidate_id)

    strategy._finish_post_rescan_branch_race(
        _context(0, strategy._best_params, start["candidate_id"])
    )

    summary = strategy.research_summary()["post_rescan_branch_race"]["summaries"][0]
    assert summary["raw_winner_candidate_id"] == representatives["normal"]["candidate_id"]
    assert summary["winner_candidate_id"] == representatives["normal"]["candidate_id"]
    assert summary["complexity_regularization"]["changed_winner"] is False


def test_observed_mapped_normal_value_uses_the_specialized_fallback() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth"],
                "width": 8,
                "budget_per_candidate": 1,
                "adaptive_fallback": {
                    "trigger_axis": "normal_mode",
                    "preferred_value": "normal",
                    "mapped_normal_trigger_values": ["normal_y_invert"],
                    "mapped_normal_fallback": {
                        "group_axes": ["normal_mode"],
                        "allowed_axis_values": {
                            "normal_mode": ["normal", "normal_y_invert"]
                        },
                        "width": 2,
                        "budget_per_candidate": 3,
                    },
                },
            },
        },
    )
    scores = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        scores[candidate["candidate_id"]] = {
            "normal_y_invert": 0.91,
            "normal": 0.90,
            "flat": 0.80,
            "legacy_y_invert_only": 0.79,
        }[mode] + (0.001 if candidate["axes"]["rim_smooth"] else 0.0)

    strategy._select_post_rescan_race_policy(scores)
    race = strategy.research_summary()["post_rescan_branch_race"]

    assert race["adaptive_fallback_applied"] is True
    assert race["adaptive_trigger"]["fallback_variant"] == (
        "mapped_normal_observed_value"
    )
    assert race["group_axes"] == ["normal_mode"]
    assert race["allowed_axis_values"] == {
        "normal_mode": ("normal", "normal_y_invert")
    }
    assert race["width"] == 2
    assert race["budget_per_candidate"] == 3


def test_confident_nonpreferred_winner_selects_full_hard_state_multirestart() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth"],
                "width": 8,
                "budget_per_candidate": 1,
                "adaptive_fallback": {
                    "trigger_axis": "normal_mode",
                    "preferred_value": "normal",
                    "minimum_nonpreferred_margin": 0.0002,
                    "confident_nonpreferred": {
                        "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                        "width": 1,
                        "budget_per_candidate": 288,
                        "strategy": "cmaes",
                        "restart_count": 4,
                        "restart_budget": 72,
                    },
                },
            },
        },
    )
    scores = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        scores[candidate["candidate_id"]] = {
            "normal_y_invert": 0.9104,
            "normal": 0.9100,
            "flat": 0.80,
            "legacy_y_invert_only": 0.79,
        }[mode] + (0.001 if candidate["axes"]["rim_smooth"] else 0.0)

    strategy._select_post_rescan_race_policy(scores)
    race = strategy.research_summary()["post_rescan_branch_race"]

    assert race["adaptive_fallback_applied"] is True
    assert race["adaptive_trigger"]["fallback_variant"] == (
        "confident_nonpreferred_winner"
    )
    assert race["adaptive_trigger"]["winner_margin_over_preferred"] == pytest.approx(
        0.0004
    )
    assert race["group_axes"] == ["normal_mode", "rim_smooth", "blend_src"]
    assert race["width"] == 1
    assert race["budget_per_candidate"] == 288
    assert race["strategy"] == "cmaes"
    assert race["restart_count"] == 4
    assert race["restart_budget"] == 72


def test_narrow_nonpreferred_lead_keeps_the_diverse_state_race() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode"],
                "width": 4,
                "budget_per_candidate": 1,
                "adaptive_fallback": {
                    "trigger_axis": "normal_mode",
                    "preferred_value": "normal",
                    "minimum_nonpreferred_margin": 0.0003,
                    "group_axes": ["normal_mode", "rim_smooth"],
                    "width": 8,
                    "budget_per_candidate": 44,
                    "strategy": "material_jacobian_trust_region",
                    "confident_nonpreferred": {
                        "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                        "width": 1,
                        "budget_per_candidate": 192,
                        "strategy": "cmaes",
                        "restart_count": 4,
                        "restart_budget": 48,
                    },
                },
            },
        },
    )
    scores = {}
    for candidate in candidates:
        mode = candidate["axes"]["normal_mode"]
        scores[candidate["candidate_id"]] = {
            "normal_y_invert": 0.9102,
            "normal": 0.9100,
            "flat": 0.80,
            "legacy_y_invert_only": 0.79,
        }[mode]

    strategy._select_post_rescan_race_policy(scores)
    race = strategy.research_summary()["post_rescan_branch_race"]

    assert race["adaptive_trigger"]["fallback_variant"] == "nonpreferred_winner"
    assert race["adaptive_trigger"]["winner_margin_over_preferred"] == pytest.approx(
        0.0002
    )
    assert race["group_axes"] == ["normal_mode", "rim_smooth"]
    assert race["width"] == 8
    assert race["budget_per_candidate"] == 44
    assert race["strategy"] == "material_jacobian_trust_region"


def test_post_rescan_cma_multirestart_uses_fresh_deterministic_seeds() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                "width": 1,
                "budget_per_candidate": 4,
                "strategy": "cmaes",
                "restart_count": 2,
                "restart_budget": 2,
                "final_continuous": {
                    "strategy": "material_jacobian_trust_region",
                    "jacobian": {"difference_mode": "forward"},
                },
            },
        },
    )
    scores = {
        candidate["candidate_id"]: (
            0.95 if candidate["candidate_id"] == target["candidate_id"] else 0.30
        )
        for candidate in candidates
    }
    analyses = {
        candidate_id: {
            "browser_score": {
                "metric": "cross_engine_foreground_components_v3",
                "fit_score": score,
            }
        }
        for candidate_id, score in scores.items()
    }
    strategy._start_post_rescan_branch_race(
        common_params={"u_GammaPower": 0.7, "u_Saturation": 1.4},
        scores=scores,
        analyses=analyses,
    )

    current = initial
    for iteration in range(8):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        if strategy.research_summary()["post_rescan_branch_race"]["summaries"]:
            break

    race = strategy.research_summary()["post_rescan_branch_race"]
    candidate_summary = race["summaries"][0]["candidates"][0]
    assert candidate_summary["proposals"] == 4
    assert len(candidate_summary["seeds"]) == 2
    assert len(set(candidate_summary["seeds"])) == 2
    assert candidate_summary["seeds"][1] - candidate_summary["seeds"][0] == 1009


def test_score_domain_override_rebaselines_before_continuous_refine() -> None:
    candidates, start, _target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": True,
                "group_axes": ["normal_mode", "rim_smooth", "blend_src"],
                "width": 1,
                "budget_per_candidate": 0,
                "final_continuous": {
                    "strategy": "material_jacobian_trust_region",
                    "jacobian": {"difference_mode": "forward"},
                },
            },
        },
    )
    scores = {
        candidate["candidate_id"]: (
            0.91 if candidate["axes"]["normal_mode"] == "normal_y_invert" else 0.8
        )
        for candidate in candidates
    }
    analyses = {
        candidate_id: {
            "browser_score": {
                "metric": "cross_engine_foreground_components_v3",
                "fit_score": score,
            }
        }
        for candidate_id, score in scores.items()
    }
    strategy._post_rescan_effective_final_score_override = {
        "metric": "cross_engine_foreground_components_v4",
        "readback_width": 544,
        "readback_height": 423,
    }
    strategy._start_post_rescan_branch_race(
        common_params={"u_GammaPower": 0.7, "u_Saturation": 1.4},
        scores=scores,
        analyses=analyses,
    )

    warmup_params, warmup_decision = strategy.propose(
        _context(0, initial, "not-a-candidate")
    )
    assert warmup_decision["material_discrete_joint"]["phase"] == (
        "continuous_score_domain_warmup"
    )
    assert warmup_decision["reset_global_score_domain"] is True
    assert warmup_params[BROWSER_SCORE_OVERRIDE_PARAM]["metric"] == (
        "cross_engine_foreground_components_v4"
    )
    warmup_ctx = _context(1, warmup_params, "not-a-candidate")
    warmup_ctx.fit_score = 0.82
    warmup_ctx.diff_score = 0.18
    warmup_ctx.analysis["browser_score"]["metric"] = (
        "cross_engine_foreground_components_v4"
    )
    warmup_ctx.analysis["browser_score"]["fit_score"] = 0.82

    next_params, _next_decision = strategy.propose(warmup_ctx)
    summary = strategy.research_summary()

    assert summary["phase"] == "continuous_refine"
    assert summary["best_fit_score"] == pytest.approx(0.82)
    assert next_params[BROWSER_SCORE_OVERRIDE_PARAM]["metric"] == (
        "cross_engine_foreground_components_v4"
    )


def test_base_post_rescan_config_can_request_a_final_score_domain() -> None:
    candidates, start, _target = _space()
    strategy = MaterialDiscreteJointStrategy(
        initial_params=attach_discrete_candidate(
            {"u_GammaPower": 0.7, "u_Saturation": 1.4},
            start,
        ),
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "post_rescan_branch_race": {
                "enabled": False,
                "budget_per_candidate": 0,
                "final_continuous_browser_score_override": {
                    "metric": "cross_engine_foreground_components_v4"
                },
            },
        },
    )

    override = strategy.research_summary()["post_rescan_branch_race"][
        "final_continuous_score_override"
    ]
    assert override["metric"] == "cross_engine_foreground_components_v4"


def test_explicit_rescan_schedule_advances_without_using_fixed_interval() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "rescan_at": [1, 3],
            "max_rescans": 2,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
        },
    )

    current = initial
    for iteration in range(160):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        if strategy.research_summary()["rescan_count"] == 2:
            break

    summary = strategy.research_summary()
    assert summary["rescan_at"] == [1, 3]
    assert summary["rescan_count"] == 2
    assert summary["post_rescan_branch_race"]["completed"] is False


def test_final_rescan_can_switch_to_a_dedicated_continuous_strategy() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "rescan_at": [1, 3],
            "max_rescans": 2,
            "restart_continuous_after_rescan": True,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "continuous_after_final_rescan": {
                "strategy": "material_jacobian_trust_region",
                "jacobian": {
                    "difference_mode": "forward",
                    "active_coordinate_count": 1,
                    "full_refresh_interval": 2,
                    "shader_default_anchor_enabled": False,
                },
            },
        },
    )

    current = initial
    for iteration in range(180):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if summary["rescan_count"] == 2 and summary["continuous"].get(
            "active_coordinate_count"
        ) == 1:
            break

    summary = strategy.research_summary()
    assert summary["rescan_count"] == 2
    assert summary["continuous"]["active_coordinate_count"] == 1
    assert summary["continuous"]["full_refresh_interval"] == 2


def test_only_rescan_can_restart_with_dedicated_continuous_strategy() -> None:
    candidates, start, target = _space()
    initial = attach_discrete_candidate(
        {"u_GammaPower": 0.7, "u_Saturation": 1.4},
        start,
    )
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        config={
            "candidates": candidates,
            "start_candidate": start,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.05],
            "diversity_rounds": 0,
            "rescan_interval": 0,
            "rescan_at": [1],
            "max_rescans": 1,
            "restart_continuous_after_rescan": True,
            "restart_continuous_after_first_rescan": True,
            "continuous": {
                "structured_only": True,
                "warmup_iterations": 100,
                "block_iterations": 1,
                "refine_iterations": 1,
                "late_scene_realign_iterations": 1,
                "late_material_polish_iterations": 1,
                "local_jacobian_iterations": 1,
            },
            "continuous_after_final_rescan": {
                "strategy": "material_jacobian_trust_region",
                "jacobian": {
                    "difference_mode": "forward",
                    "active_coordinate_count": 1,
                    "full_refresh_interval": 2,
                    "shader_default_anchor_enabled": False,
                },
            },
        },
    )

    current = initial
    for iteration in range(120):
        current, _decision = strategy.propose(
            _context(iteration, current, target["candidate_id"])
        )
        summary = strategy.research_summary()
        if summary["rescan_count"] == 1 and summary["continuous"].get(
            "active_coordinate_count"
        ) == 1:
            break

    summary = strategy.research_summary()
    assert summary["rescan_count"] == 1
    assert summary["restart_continuous_after_first_rescan"] is True
    assert summary["continuous"]["active_coordinate_count"] == 1
