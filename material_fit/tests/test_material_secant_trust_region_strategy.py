from __future__ import annotations

from material_fit.fit_cli import parse_fit_args
from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_secant_trust_region_strategy import (
    MaterialSecantTrustRegionStrategy,
)
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def _four_param_shader() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_Contrast", "Range", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_TexPower", "Range", default=1.0, range_min=0.0, range_max=4.0),
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


def _four_param_context(
    iteration: int,
    params: dict[str, float],
    target: dict[str, float],
) -> StrategyContext:
    ranges = {
        "u_GammaPower": 2.9999,
        "u_Saturation": 2.0,
        "u_Contrast": 2.0,
        "u_TexPower": 4.0,
    }
    residual = [
        (params[name] - target[name]) / ranges[name]
        for name in ranges
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


def test_secant_strategy_recovers_coupled_linear_target() -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "design_size": 2,
            "probe_radius": 0.2,
            "trust_radius": 0.8,
            "max_axis_update": 0.8,
            "ridge": 1.0e-8,
            "score_feature_weight": 0.0,
        },
    )

    current = dict(initial)
    best = _context(0, current, target).fit_score
    for iteration in range(16):
        context = _context(iteration, current, target)
        best = max(best, context.fit_score)
        current, decision = strategy.propose(context)
        assert decision["material_secant_trust_region"]["target_params_visible"] is False
    best = max(best, _context(16, current, target).fit_score)

    assert best > 0.999999
    assert strategy.research_summary()["model_builds"] > 0
    assert strategy.research_summary()["accepted_updates"] > 0


def test_one_sided_secant_design_recovers_coupled_linear_target() -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "design_size": 2,
            "antithetic": False,
            "probe_radius": 0.05,
            "trust_radius": 0.8,
            "max_axis_update": 0.8,
            "ridge": 1.0e-8,
            "score_feature_weight": 0.0,
        },
    )

    current = dict(initial)
    best = _context(0, current, target).fit_score
    for iteration in range(24):
        context = _context(iteration, current, target)
        best = max(best, context.fit_score)
        current, _decision = strategy.propose(context)
    best = max(best, _context(24, current, target).fit_score)

    assert best > 0.999999
    assert strategy.research_summary()["accepted_updates"] > 0


def test_secant_discards_inconsistent_residual_shapes() -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "design_size": 2,
            "antithetic": False,
            "score_feature_weight": 0.0,
        },
    )

    current = dict(initial)
    current, _decision = strategy.propose(_context(0, current, target))
    malformed = _context(1, current, target)
    malformed.analysis["structured_residual_features"]["features"].append(0.0)
    for iteration in range(1, 10):
        context = malformed if iteration == 1 else _context(iteration, current, target)
        current, _decision = strategy.propose(context)

    assert strategy.research_summary()["discarded_feature_samples"] == 1


def test_compressed_design_builds_low_rank_updates_below_coordinate_count() -> None:
    initial = {
        "u_GammaPower": 0.5,
        "u_Saturation": 1.6,
        "u_Contrast": 0.4,
        "u_TexPower": 0.5,
    }
    target = {
        "u_GammaPower": 2.2,
        "u_Saturation": 0.4,
        "u_Contrast": 1.5,
        "u_TexPower": 2.8,
    }
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_four_param_shader(),
        search_param_names=list(initial),
        config={
            "design_size": 2,
            "compressed_design": True,
            "antithetic": False,
            "probe_radius": 0.1,
            "trust_radius": 0.8,
            "max_axis_update": 0.8,
            "ridge": 1.0e-6,
            "score_feature_weight": 0.0,
        },
    )

    current = dict(initial)
    initial_score = _four_param_context(0, current, target).fit_score
    best = initial_score
    for iteration in range(16):
        context = _four_param_context(iteration, current, target)
        best = max(best, context.fit_score)
        current, _decision = strategy.propose(context)
    best = max(best, _four_param_context(16, current, target).fit_score)
    summary = strategy.research_summary()

    assert summary["coordinate_count"] == 4
    assert summary["design_size"] == 2
    assert summary["compressed_design"] is True
    assert summary["design_rank_upper_bound"] == 2
    assert summary["model_builds"] > 0
    assert best > initial_score


def test_default_design_remains_full_rank() -> None:
    initial = {
        "u_GammaPower": 0.5,
        "u_Saturation": 1.6,
        "u_Contrast": 0.4,
        "u_TexPower": 0.5,
    }
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_four_param_shader(),
        search_param_names=list(initial),
        config={"design_size": 2},
    )

    summary = strategy.research_summary()
    assert summary["design_size"] == 4
    assert summary["compressed_design"] is False


def test_accepted_update_can_reuse_response_before_rebuilding_design() -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialSecantTrustRegionStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "design_size": 2,
            "antithetic": False,
            "probe_radius": 0.05,
            "trust_radius": 0.2,
            "max_axis_update": 0.2,
            "ridge": 1.0e-8,
            "score_feature_weight": 0.0,
            "model_reuse_updates": 2,
        },
    )

    current = dict(initial)
    roles = []
    for iteration in range(12):
        current, decision = strategy.propose(_context(iteration, current, target))
        roles.append(decision["material_secant_trust_region"]["role"])

    summary = strategy.research_summary()
    assert summary["model_reuse_updates"] == 2
    assert summary["model_reuse_attempts"] > 0
    assert summary["model_reuse_accepts"] > 0
    assert any(
        first == second == "secant_trial"
        for first, second in zip(roles, roles[1:])
    )


def test_factory_and_cli_accept_secant_strategy() -> None:
    initial = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = build_strategy(
        optimizer="material_secant_trust_region",
        initial_params=initial,
        shader_params=_shader_params(),
        policies=[],
        unity_material_params=None,
        search_param_names=list(initial),
        material_secant_trust_region_config={"design_size": 2},
    )
    args = parse_fit_args(
        ["--config", "fit_config.json", "--optimizer", "material_secant_trust_region"]
    )

    assert isinstance(strategy, MaterialSecantTrustRegionStrategy)
    assert args.optimizer == "material_secant_trust_region"
