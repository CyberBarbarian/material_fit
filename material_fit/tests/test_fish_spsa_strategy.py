from __future__ import annotations

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.fish_spsa_strategy import FishSpsaStrategy
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def _params() -> dict[str, float]:
    return {"u_GammaPower": 0.3, "u_Saturation": 0.2}


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def _score(params: dict[str, float]) -> float:
    gamma_error = (params["u_GammaPower"] - 2.2) / 3.0
    saturation_error = (params["u_Saturation"] - 1.5) / 2.0
    return 1.0 - 0.5 * (gamma_error * gamma_error + saturation_error * saturation_error)


def _context(iteration: int, params: dict[str, float], score: float) -> StrategyContext:
    return StrategyContext(
        iteration=iteration,
        current_params=params,
        analysis={},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(),
    )


def test_fish_spsa_uses_antithetic_pair_then_adam_update() -> None:
    params = _params()
    strategy = FishSpsaStrategy(
        initial_params=params,
        shader_params=_shader_params(),
        search_param_names=list(params),
        config={"seed": 7, "directions_per_update": 1},
    )

    plus, plus_decision = strategy.propose(_context(0, params, _score(params)))
    minus, minus_decision = strategy.propose(_context(1, plus, _score(plus)))
    update, update_decision = strategy.propose(_context(2, minus, _score(minus)))

    assert strategy.trainable_dim == 2
    assert plus_decision["fish_spsa"]["role"] == "plus"
    assert minus_decision["fish_spsa"]["role"] == "minus"
    assert update_decision["fish_spsa"]["role"] == "update"
    assert update != params


def test_strategy_factory_builds_fish_spsa_with_explicit_whitelist() -> None:
    strategy = build_strategy(
        optimizer="fish_spsa",
        initial_params=_params(),
        shader_params=_shader_params(),
        policies=(),
        unity_material_params=None,
        search_param_names=["u_GammaPower"],
        fish_spsa_config={"seed": 3},
    )

    assert isinstance(strategy, FishSpsaStrategy)
    assert strategy.trainable_dim == 1


def test_fish_spsa_averages_multiple_antithetic_directions_before_update() -> None:
    current = _params()
    strategy = FishSpsaStrategy(
        initial_params=current,
        shader_params=_shader_params(),
        search_param_names=list(current),
        config={"seed": 5, "directions_per_update": 2},
    )
    roles = []
    for iteration in range(4):
        current, decision = strategy.propose(_context(iteration, current, _score(current)))
        roles.append(decision["fish_spsa"]["role"])

    assert roles == ["plus", "minus", "plus", "minus"]
    current, decision = strategy.propose(_context(4, current, _score(current)))
    assert decision["fish_spsa"]["role"] == "update"
    assert decision["fish_spsa"]["directions_per_update"] == 2


def test_fish_spsa_improves_unknown_coupled_quadratic_from_scores_only() -> None:
    current = _params()
    initial_score = _score(current)
    best_score = initial_score
    strategy = FishSpsaStrategy(
        initial_params=current,
        shader_params=_shader_params(),
        search_param_names=list(current),
        config={
            "seed": 11,
            "perturbation_scale": 0.08,
            "learning_rate": 0.25,
            "stability_constant": 2.0,
            "directions_per_update": 1,
        },
    )

    for iteration in range(360):
        score = _score(current)
        best_score = max(best_score, score)
        current, _decision = strategy.propose(_context(iteration, current, score))

    best_score = max(best_score, _score(current))
    assert best_score > initial_score + 0.25
    assert best_score > 0.99
