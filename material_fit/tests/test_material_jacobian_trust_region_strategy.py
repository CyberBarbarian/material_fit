from __future__ import annotations

import math

import pytest

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_jacobian_trust_region_strategy import (
    MaterialJacobianTrustRegionStrategy,
)
from material_fit.optimizer.material_block_trust_region_strategy import MaterialBlockTrustRegionStrategy
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def _context(iteration: int, params: dict[str, float], target: dict[str, float]) -> StrategyContext:
    residual = [
        (params["u_GammaPower"] - target["u_GammaPower"]) / 2.9999,
        (params["u_Saturation"] - target["u_Saturation"]) / 2.0,
    ]
    score = 1.0 - min(sum(value * value for value in residual), 1.0)
    return StrategyContext(
        iteration=iteration,
        current_params=params,
        analysis={"structured_residual_features": {"profile": "synthetic", "features": residual}},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=params),
    )


def test_trust_region_recovers_unknown_linear_target_from_residuals() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "probe_step": 0.04,
            "ridge": 1.0e-8,
            "trust_radius": 0.6,
            "maximum_trust_radius": 0.8,
            "max_axis_update": 0.8,
        },
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    decisions = []
    for iteration in range(20):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, decision = strategy.propose(context)
        decisions.append(decision)

    best_score = max(best_score, _context(20, current, target).fit_score)
    assert best_score > 0.999999
    assert any(item["material_jacobian_trust_region"]["role"] == "trust_region_trial" for item in decisions)
    assert all(item["material_jacobian_trust_region"]["target_params_visible"] is False for item in decisions)
    assert all(item["material_jacobian_trust_region"]["coordinate_count"] == 2 for item in decisions)


def test_trust_region_evaluates_generic_shader_defaults_before_jacobian() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={"shader_default_anchor_enabled": True},
    )

    candidate, decision = strategy.propose(_context(0, initial, target))

    assert candidate == target
    assert decision["material_jacobian_trust_region"]["role"] == "shader_default_anchor"
    assert decision["material_jacobian_trust_region"]["target_params_visible"] is False


def test_log_coordinate_uses_multiplicative_probe_scale() -> None:
    initial = {"u_EmissionPow": 0.0}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=[ShaderParam("u_EmissionPow", "Float", default=0.0)],
        search_param_names=["u_EmissionPow"],
        config={"log_coordinate_ids": ["u_EmissionPow"]},
    )
    coordinate = strategy._coordinates[0]

    candidate = strategy._write_coordinate_normalized_value(
        coordinate,
        initial,
        0.05,
    )

    assert candidate["u_EmissionPow"] == pytest.approx(
        math.expm1(0.05 * math.log1p(64.0))
    )
    assert candidate["u_EmissionPow"] < 0.25


def test_linear_coordinate_preserves_legacy_probe_arithmetic() -> None:
    initial = {"u_GammaPower": 1.0}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0001,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={"shader_default_anchor_enabled": False},
    )
    coordinate = strategy._round_coordinates[0]
    span = max(coordinate.high - coordinate.low, 1.0e-12)
    before = coordinate.read(initial)
    positive_room = (coordinate.high - before) / span
    negative_room = (before - coordinate.low) / span
    direction = 1.0 if positive_room >= negative_room else -1.0
    expected = coordinate.write(initial, before + direction * strategy._probe_step * span)
    expected_delta = (coordinate.read(expected) - before) / span

    candidate, decision = strategy._jacobian_probe_candidate()

    assert candidate == expected
    assert decision["material_jacobian_trust_region"]["delta_normalized"] == (
        expected_delta
    )


def test_residual_merit_can_cross_a_temporary_score_valley() -> None:
    initial = {"u_GammaPower": 0.3, "u_Saturation": 0.2}
    target = {"u_GammaPower": 2.7, "u_Saturation": 1.8}
    initial_residual_norm = math.sqrt(
        ((initial["u_GammaPower"] - target["u_GammaPower"]) / 2.9999) ** 2
        + ((initial["u_Saturation"] - target["u_Saturation"]) / 2.0) ** 2
    )

    def valley_context(iteration: int, params: dict[str, float]) -> StrategyContext:
        residual = [
            (params["u_GammaPower"] - target["u_GammaPower"]) / 2.9999,
            (params["u_Saturation"] - target["u_Saturation"]) / 2.0,
        ]
        residual_norm = math.sqrt(sum(value * value for value in residual))
        progress = min(max(1.0 - residual_norm / initial_residual_norm, 0.0), 1.0)
        score = 0.99 + 0.01 * progress - 0.025 * math.sin(math.pi * progress)
        return StrategyContext(
            iteration=iteration,
            current_params=params,
            analysis={
                "structured_residual_features": {
                    "profile": "synthetic_score_valley",
                    "features": residual,
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=AdjustmentState(best_params=params),
        )

    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "acceptance_objective": "residual_merit",
            "score_feature_weight": 0.0,
            "maximum_score_drop": 0.03,
            "probe_step": 0.04,
            "ridge": 1.0e-8,
            "trust_radius": 0.20,
            "maximum_trust_radius": 0.25,
            "max_axis_update": 0.25,
            "line_search_scales": [1.0],
        },
    )

    current = dict(initial)
    observed_scores: list[float] = []
    for iteration in range(24):
        context = valley_context(iteration, current)
        observed_scores.append(context.fit_score)
        current, _decision = strategy.propose(context)

    observed_scores.append(valley_context(24, current).fit_score)
    summary = strategy.research_summary()
    assert min(observed_scores) < observed_scores[0]
    assert max(observed_scores) > 0.999
    assert summary["acceptance_objective"] == "residual_merit"
    assert summary["accepted_score_regressions"] >= 1


def test_active_subspace_reuses_only_online_sensitive_coordinates() -> None:
    initial = {
        "u_GammaPower": 0.55,
        "u_Saturation": 1.65,
        "u_Contrast": 0.3,
        "u_HueShift": 0.2,
    }
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}
    shader_params = [
        *_shader_params(),
        ShaderParam("u_Contrast", "Range", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_HueShift", "Range", default=0.0, range_min=0.0, range_max=1.0),
    ]
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=list(initial),
        config={
            "shader_default_anchor_enabled": False,
            "active_coordinate_count": 2,
            "full_refresh_interval": 0,
            "probe_step": 0.04,
            "ridge": 1.0e-8,
            "trust_radius": 0.6,
            "maximum_trust_radius": 0.8,
            "max_axis_update": 0.8,
        },
    )

    current = dict(initial)
    coordinate_counts = []
    for iteration in range(20):
        current, decision = strategy.propose(_context(iteration, current, target))
        coordinate_counts.append(
            decision["material_jacobian_trust_region"]["coordinate_count"]
        )

    summary = strategy.research_summary()
    assert coordinate_counts[:4] == [4, 4, 4, 4]
    assert 2 in coordinate_counts[4:]
    assert set(summary["selected_coordinate_ids"]) == {
        "u_GammaPower",
        "u_Saturation",
    }
    assert summary["total_coordinate_count"] == 4


def test_improving_probe_can_become_the_next_center_without_extra_render() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}

    def conflicting_context(
        iteration: int,
        params: dict[str, float],
    ) -> StrategyContext:
        score_residual = [
            (params["u_GammaPower"] - target["u_GammaPower"]) / 2.9999,
            (params["u_Saturation"] - target["u_Saturation"]) / 2.0,
        ]
        score = 1.0 - min(sum(value * value for value in score_residual), 1.0)
        misleading_residual = [
            params["u_GammaPower"] / 2.9999,
            (params["u_Saturation"] - 2.0) / 2.0,
        ]
        return StrategyContext(
            iteration=iteration,
            current_params=params,
            analysis={
                "structured_residual_features": {
                    "profile": "synthetic_conflicting_direction",
                    "features": misleading_residual,
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=AdjustmentState(best_params=params),
        )
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "shader_default_anchor_enabled": False,
            "accept_improving_probes": True,
            "minimum_probe_score_gain": 1.0e-8,
            "probe_step": 0.10,
            "ridge": 1.0e-8,
            "trust_radius": 0.6,
            "maximum_trust_radius": 0.8,
            "max_axis_update": 0.8,
        },
    )

    current = dict(initial)
    for iteration in range(12):
        current, _decision = strategy.propose(conflicting_context(iteration, current))

    summary = strategy.research_summary()
    assert summary["accept_improving_probes"] is True
    assert summary["accepted_probe_moves"] >= 1
    assert summary["best_fit_score"] > conflicting_context(0, initial).fit_score


def test_score_gradient_mode_uses_scalar_feedback_for_the_update_direction() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "shader_default_anchor_enabled": False,
            "solve_mode": "score_gradient",
            "probe_step": 0.04,
            "trust_radius": 0.2,
            "maximum_trust_radius": 0.4,
            "max_axis_update": 0.4,
        },
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    for iteration in range(24):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, _decision = strategy.propose(context)

    best_score = max(best_score, _context(24, current, target).fit_score)
    assert best_score > 0.999
    assert strategy.research_summary()["solve_mode"] == "score_gradient"


def test_groupwise_least_squares_is_a_target_blind_solver_mode() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}
    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "shader_default_anchor_enabled": False,
            "solve_mode": "groupwise_least_squares",
            "probe_step": 0.04,
            "ridge": 1.0e-8,
            "group_weight_ridge": 1.0e-8,
            "trust_radius": 0.6,
            "maximum_trust_radius": 0.8,
            "max_axis_update": 0.8,
        },
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    for iteration in range(24):
        current_context = _context(iteration, current, target)
        best_score = max(best_score, current_context.fit_score)
        current, decision = strategy.propose(current_context)
        assert decision["material_jacobian_trust_region"]["target_params_visible"] is False

    best_score = max(best_score, _context(24, current, target).fit_score)
    summary = strategy.research_summary()
    assert best_score > 0.999
    assert summary["solve_mode"] == "groupwise_least_squares"


def test_high_score_jacobian_reuse_freezes_configured_parameters() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65, "u_Contrast": 0.4}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7, "u_Contrast": 1.4}
    shader_params = [
        *_shader_params(),
        ShaderParam("u_Contrast", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]

    def context(iteration: int, params: dict[str, float]) -> StrategyContext:
        residual = [
            (params["u_GammaPower"] - target["u_GammaPower"]) / 2.9999,
            (params["u_Saturation"] - target["u_Saturation"]) / 2.0,
            (params["u_Contrast"] - target["u_Contrast"]) / 2.0,
        ]
        score = 1.0 - min(sum(value * value for value in residual), 1.0)
        return StrategyContext(
            iteration=iteration,
            current_params=params,
            analysis={
                "structured_residual_features": {
                    "profile": "synthetic",
                    "features": residual,
                }
            },
            diff_score=1.0 - score,
            fit_score=score,
            state=AdjustmentState(best_params=params),
        )

    strategy = MaterialJacobianTrustRegionStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=list(initial),
        config={
            "shader_default_anchor_enabled": False,
            "probe_step": 0.04,
            "ridge": 1.0e-8,
            "trust_radius": 0.2,
            "maximum_trust_radius": 0.4,
            "max_axis_update": 0.4,
            "model_reuse_updates": 2,
            "model_reuse_min_score": 0.0,
            "model_reuse_frozen_param_names": ["u_Saturation"],
        },
    )

    current = dict(initial)
    reused_decision = None
    previous_role = None
    for iteration in range(16):
        current, decision = strategy.propose(context(iteration, current))
        role = decision["material_jacobian_trust_region"]["role"]
        if previous_role == "trust_region_trial" and role == "trust_region_trial":
            reused_decision = decision
            break
        previous_role = role

    assert reused_decision is not None
    changed_names = {change["param"] for change in reused_decision["changes"]}
    assert changed_names
    assert changed_names <= {"u_GammaPower", "u_Contrast"}
    assert "u_Saturation" not in changed_names
    summary = strategy.research_summary()
    assert summary["model_reuse_activated"] is True
    assert summary["model_reuse_attempts"] > 0
    assert summary["model_reuse_accepts"] > 0
    assert summary["model_reuse_frozen_param_names"] == ["u_Saturation"]


def test_strategy_factory_builds_material_jacobian_trust_region() -> None:
    initial = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = build_strategy(
        optimizer="material_jacobian_trust_region",
        initial_params=initial,
        shader_params=_shader_params(),
        policies=(),
        unity_material_params=None,
        search_param_names=list(initial),
        material_jacobian_trust_region_config={"probe_step": 0.05},
    )

    assert isinstance(strategy, MaterialJacobianTrustRegionStrategy)


def test_block_trust_region_recovers_target_without_asset_specific_branch() -> None:
    initial = {"u_GammaPower": 0.55, "u_Saturation": 1.65}
    target = {"u_GammaPower": 1.9, "u_Saturation": 0.7}
    strategy = MaterialBlockTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "block_iterations": 10,
            "full_iterations": 20,
            "ridge": 1.0e-6,
            "trust_radius": 0.6,
            "maximum_trust_radius": 0.8,
            "max_axis_update": 0.8,
        },
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    decisions = []
    for iteration in range(30):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, decision = strategy.propose(context)
        decisions.append(decision)

    best_score = max(best_score, _context(30, current, target).fit_score)
    assert best_score > 0.999999
    assert any(item["material_block_trust_region"]["active_name"] == "base_surface" for item in decisions)
    assert all(item["material_block_trust_region"]["target_params_visible"] is False for item in decisions)
