from __future__ import annotations

import numpy as np

from material_fit.fit_cli import parse_fit_args
from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_inverse_surrogate_strategy import (
    MaterialInverseSurrogateStrategy,
)
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def context(iteration: int, params: dict[str, float], target: dict[str, float]) -> StrategyContext:
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


def test_inverse_surrogate_queries_zero_residual_without_target_params() -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialInverseSurrogateStrategy(
        initial_params=initial,
        shader_params=shader_params(),
        search_param_names=list(initial),
        config={
            "sample_count": 8,
            "feature_count": 8,
            "hidden_features": 8,
            "ridge_values": [1.0e-8],
            "random_feature_scales": [0.5],
            "prediction_blend_scales": [1.0],
            "global_radii": [0.5],
        },
    )

    current = dict(initial)
    best = context(0, current, target).fit_score
    for iteration in range(40):
        current_context = context(iteration, current, target)
        best = max(best, current_context.fit_score)
        current, decision = strategy.propose(current_context)
        assert decision["material_inverse_surrogate"]["target_params_visible"] is False
        if strategy.stop_reason():
            break
    best = max(best, context(40, current, target).fit_score)

    assert best > 0.999
    summary = strategy.research_summary()
    assert summary["models_built"] == 1
    assert summary["prediction_count"] > 0


def test_factory_and_cli_accept_inverse_surrogate() -> None:
    initial = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = build_strategy(
        optimizer="material_inverse_surrogate",
        initial_params=initial,
        shader_params=shader_params(),
        policies=[],
        unity_material_params=None,
        search_param_names=list(initial),
        material_inverse_surrogate_config={"sample_count": 8},
    )
    args = parse_fit_args(
        ["--config", "fit_config.json", "--optimizer", "material_inverse_surrogate"]
    )

    assert isinstance(strategy, MaterialInverseSurrogateStrategy)
    assert args.optimizer == "material_inverse_surrogate"


def test_active_cycles_retrain_after_scoring_previous_predictions(monkeypatch) -> None:
    initial = {"u_GammaPower": 0.5, "u_Saturation": 1.6}
    target = {"u_GammaPower": 2.2, "u_Saturation": 0.4}
    strategy = MaterialInverseSurrogateStrategy(
        initial_params=initial,
        shader_params=shader_params(),
        search_param_names=list(initial),
        config={"sample_count": 4, "max_model_cycles": 2},
    )
    sample_counts: list[int] = []

    def fake_build_predictions() -> list[dict[str, object]]:
        sample_counts.append(len(strategy._samples))
        value = 0.25 if len(sample_counts) == 1 else 0.75
        return [{"vector": np.asarray([value, 1.0 - value]), "model": f"cycle{len(sample_counts)}"}]

    monkeypatch.setattr(strategy, "_build_predictions", fake_build_predictions)
    current = dict(initial)
    for iteration in range(8):
        current, _ = strategy.propose(context(iteration, current, target))
        if strategy.stop_reason():
            break

    assert sample_counts == [5, 6]
    summary = strategy.research_summary()
    assert summary["models_built"] == 2
    assert summary["prediction_count"] == 2
