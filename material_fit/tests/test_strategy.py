"""Tests for :mod:`tools.material_fit.optimizer.strategy`.

These pin down the strategy contract that
``fit_material._run_auto_adjustment`` now relies on:

* ``HeuristicStrategy`` proposes parameter changes consistent with
  the legacy ``propose_next_params`` behaviour, and tags decisions
  with ``optimizer == "heuristic"``.
* ``CmaesStrategy`` falls back to cold when warm history is empty,
  exposes ``warm_started`` correctly, and emits ``optimizer == "cma_es"``
  decisions whose ``cma_es.evaluations`` counter advances after each
  ``propose`` call.
* ``build_strategy`` rejects unknown optimizer names rather than
  silently falling back to heuristic — silent fallbacks would corrupt
  experiment comparisons.
* The fit_score → CMA-ES loss conversion is monotone (higher fit_score
  ↔ lower loss), so CMA-ES actually minimizes the right thing.

Run with::

    python -m pytest tools/material_fit/tests/test_strategy.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.optimizer.adjustment_algorithm import (  # noqa: E402
    AdjustmentState,
    build_adjustment_policies,
)
from tools.material_fit.optimizer.effective_bounds import effective_bounds_for_param  # noqa: E402
from tools.material_fit.optimizer.parameter_search import build_zero_searchable_initial_params  # noqa: E402
from tools.material_fit.optimizer.strategy import (  # noqa: E402
    CmaesStrategy,
    CmaesStrategyConfig,
    CrossEngineHybridStrategy,
    HeuristicStrategy,
    OptimizerUnavailableError,
    Pattern16Strategy,
    StrategyContext,
    build_strategy,
    cmaes_strategy_config_from_dict,
    cmaes_strategy_config_to_dict,
)
from tools.material_fit.optimizer.pattern16_strategy import (  # noqa: E402
    PATTERN16_PARAM_ORDER,
    pattern16_search_param_names,
)
from tools.material_fit.shared.models import ShaderParam  # noqa: E402


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_OcclusionStrength", "Range", default=1.0, range_min=0.0, range_max=10.0),
        ShaderParam("u_DiffuseThreshold", "Range", default=0.5, range_min=0.0, range_max=1.0),
        ShaderParam("u_DiffuseSmoothness", "Range", default=0.1, range_min=0.0, range_max=1.0),
        ShaderParam("u_ShadowColor", "Color", default=[0, 0, 0, 1]),
        ShaderParam("u_SpecularColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_SpecularIntensity", "Float", default=1.0),
        ShaderParam("u_FresnelColor", "Color", default=[1, 0, 0, 0]),
        ShaderParam("u_FresnelIntensity", "Float", default=1.0),
        ShaderParam("u_AdjustHue", "Float", default=0.0),
        ShaderParam("u_AdjustSaturation", "Float", default=0.0),
        ShaderParam("u_AdjustLightness", "Float", default=0.0),
        ShaderParam("u_ContrastScale", "Float", default=0.0),
    ]


def _initial_params() -> dict[str, object]:
    return {
        "u_BaseColor": [0.32, 0.27, 0.07, 1.0],
        "u_Gamma_Power": 2.2,
        "u_Metallic": 0.0,
        "u_Smoothness": 1.0,
        "u_OcclusionStrength": 1.0,
        "u_DiffuseThreshold": 0.5,
        "u_DiffuseSmoothness": 0.1,
        "u_ShadowColor": [0, 0, 0, 1],
        "u_SpecularColor": [1, 1, 1, 1],
        "u_SpecularIntensity": 1.0,
        "u_FresnelColor": [1, 0, 0, 0],
        "u_FresnelIntensity": 1.0,
        "u_AdjustHue": 0.0,
        "u_AdjustSaturation": 0.0,
        "u_AdjustLightness": 0.0,
        "u_ContrastScale": 0.0,
    }


def _zero_params() -> dict[str, object]:
    params = dict(_initial_params())
    for name, value in list(params.items()):
        if isinstance(value, (int, float)):
            params[name] = 0.0
        elif isinstance(value, list):
            params[name] = [0.0, 0.0, 0.0, value[3] if len(value) > 3 else 0.0]
    return params


def _normalized_distance_for_test(
    left: dict[str, object],
    right: dict[str, object],
    shader_params: list[ShaderParam],
) -> float:
    param_info = {param.name: param for param in shader_params}
    deltas: list[float] = []
    for name, left_value in left.items():
        right_value = right.get(name)
        if isinstance(left_value, (int, float)) and not isinstance(left_value, bool):
            if not isinstance(right_value, (int, float)) or isinstance(right_value, bool):
                continue
            bounds = effective_bounds_for_param(name)
            if bounds is None:
                param = param_info.get(name)
                if param is not None and param.range_min is not None and param.range_max is not None:
                    bounds = (float(param.range_min), float(param.range_max))
            if bounds is None:
                low = min(float(left_value), float(right_value), 0.0) - 1.0
                high = max(float(left_value), float(right_value), 0.0) + 1.0
            else:
                low, high = float(bounds[0]), float(bounds[1])
            width = max(high - low, 1.0e-9)
            deltas.append((float(left_value) - float(right_value)) / width)
            continue
        if isinstance(left_value, list) and isinstance(right_value, list):
            for index in range(min(3, len(left_value), len(right_value))):
                left_item = left_value[index]
                right_item = right_value[index]
                if (
                    isinstance(left_item, bool)
                    or isinstance(right_item, bool)
                    or not isinstance(left_item, (int, float))
                    or not isinstance(right_item, (int, float))
                ):
                    continue
                deltas.append(float(left_item) - float(right_item))
    if not deltas:
        return 0.0
    return math.sqrt(sum(delta * delta for delta in deltas) / len(deltas))


def _channel_analysis(rgb_bias: tuple[float, float, float] = (0.05, 0.0, -0.05), luma_bias: float = 0.04) -> dict:
    """A minimal fake material_channels dict good enough to drive choose_stage."""
    channel = {
        "rgb_bias_candidate_minus_reference": list(rgb_bias),
        "luma_bias_candidate_minus_reference": luma_bias,
        "saturation_bias_candidate_minus_reference": 0.0,
        "contrast_bias_candidate_minus_reference": 0.0,
        "rgb_mae": 0.10,
    }
    edge_channel = dict(channel)
    edge_channel["edge_minus_center_luma_bias"] = 0.0
    return {
        "score": 0.10,
        "material_channels": {
            "base_color_main_texture": channel,
            "shadow_occlusion": channel,
            "metallic_smoothness_specular": channel,
            "environment_reflection_matcap": channel,
            "fresnel_rim": channel,
            "emission": channel,
            "color_grading_hsv_contrast": channel,
            "center_vs_edge_balance": edge_channel,
        },
    }


# --------------------------------------------------------------------
# build_strategy


def test_build_strategy_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown optimizer"):
        build_strategy(
            optimizer="bogus",
            initial_params=_initial_params(),
            shader_params=_shader_params(),
            policies=[],
            unity_material_params={},
        )


def test_build_strategy_returns_heuristic_by_default():
    policies = build_adjustment_policies(_shader_params())
    strategy = build_strategy(
        optimizer="heuristic",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=policies,
        unity_material_params={},
    )
    assert isinstance(strategy, HeuristicStrategy)
    assert strategy.name == "heuristic"


def test_build_strategy_cma_cold():
    policies = build_adjustment_policies(_shader_params())
    strategy = build_strategy(
        optimizer="cma_cold",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=policies,
        unity_material_params={},
        cma_es_config=CmaesStrategyConfig(seed=7),
    )
    assert isinstance(strategy, CmaesStrategy)
    assert strategy.warm_started is False


def test_build_strategy_cma_cold_respects_explicit_search_param_names():
    policies = build_adjustment_policies(_shader_params())
    strategy = build_strategy(
        optimizer="cma_cold",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=policies,
        unity_material_params={},
        cma_es_config=CmaesStrategyConfig(seed=7),
        search_param_names=["u_Gamma_Power"],
    )

    assert isinstance(strategy, CmaesStrategy)
    assert strategy.trainable_dim == 1


def test_build_strategy_cma_warm_falls_back_to_cold_when_no_history():
    policies = build_adjustment_policies(_shader_params())
    strategy = build_strategy(
        optimizer="cma_warm",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=policies,
        unity_material_params={},
        cma_es_config=CmaesStrategyConfig(seed=7),
        warm_start_history=[],
    )
    assert isinstance(strategy, CmaesStrategy)
    assert strategy.warm_started is False


def test_build_strategy_cma_warm_uses_provided_history():
    policies = build_adjustment_policies(_shader_params())
    history = [
        (_initial_params(), 0.65),
        ({**_initial_params(), "u_Gamma_Power": 1.8}, 0.70),
        ({**_initial_params(), "u_Gamma_Power": 2.4, "u_BaseColor": [0.4, 0.3, 0.1, 1.0]}, 0.55),
    ]
    strategy = build_strategy(
        optimizer="cma_warm",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=policies,
        unity_material_params={},
        cma_es_config=CmaesStrategyConfig(seed=7, warm_start_iters=12),
        warm_start_history=history,
    )
    assert isinstance(strategy, CmaesStrategy)
    assert strategy.warm_started is True


def test_build_strategy_cold_start_hybrid():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )

    assert strategy.name == "cold_start_hybrid"
    assert strategy.wants_global_no_improve_check() is False


def _pattern16_params() -> dict[str, object]:
    values = {
        "u_GammaPower": 1.55,
        "u_Saturation": 0.85,
        "u_TexPower": 1.35,
        "u_AoPower": 0.55,
        "u_EmissionPow": 0.214,
        "u_IndirectStrength": 0.928,
        "u_NormalScale": 0.529,
        "u_ShadowSmoothness": 0.162,
        "u_ShadowThreshold1": 0.30,
        "u_ShadowThreshold2": 0.40,
        "u_SpecularIntensity": 0.898,
        "u_SpecularPower": 8.0,
        "u_SpecularThreshold": 0.332,
        "u_SpecularSmoothness": 0.68,
        "u_RimIntensity": 1.183,
        "u_RimWidth": 4.619,
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_AlphaTestValue": 0.5,
        "u_SkyRotateX": 231.0,
    }
    return {name: values[name] for name in values}


def _pattern16_shader_params() -> list[ShaderParam]:
    params = [
        ShaderParam(name, "Range", default=0.0, range_min=0.0, range_max=8.0)
        for name in PATTERN16_PARAM_ORDER
    ]
    params.extend(
        [
            ShaderParam("u_MainTex_ST", "Vector4", default=[1.0, 1.0, 0.0, 0.0]),
            ShaderParam("u_AlphaTestValue", "Float", default=0.5),
            ShaderParam("u_SkyRotateX", "Float", default=231.0),
        ]
    )
    return params


def test_build_strategy_pattern16_mainline():
    initial = _pattern16_params()
    strategy = build_strategy(
        optimizer="pattern16",
        initial_params=initial,
        shader_params=_pattern16_shader_params(),
        policies=build_adjustment_policies(_pattern16_shader_params()),
        unity_material_params={},
    )

    assert isinstance(strategy, Pattern16Strategy)
    assert strategy.name == "pattern16"
    assert strategy.wants_global_no_improve_check() is False


def test_build_strategy_cross_engine_hybrid_is_blackbox_mainline():
    initial = _pattern16_params()
    strategy = build_strategy(
        optimizer="cross_engine_hybrid",
        initial_params=initial,
        shader_params=_pattern16_shader_params(),
        policies=build_adjustment_policies(_pattern16_shader_params()),
        unity_material_params={},
    )

    assert isinstance(strategy, CrossEngineHybridStrategy)
    assert strategy.name == "cross_engine_hybrid"
    assert strategy.wants_global_no_improve_check() is False
    summary = strategy.research_summary()
    assert summary["phase"] == "calibration"
    assert summary["selected_params"] == list(PATTERN16_PARAM_ORDER)
    assert "human_target" not in summary


def test_cross_engine_hybrid_calibrates_then_runs_broad_pass_before_ranking():
    initial = _pattern16_params()
    strategy = build_strategy(
        optimizer="cross_engine_hybrid",
        initial_params=initial,
        shader_params=_pattern16_shader_params(),
        policies=build_adjustment_policies(_pattern16_shader_params()),
        unity_material_params={},
        search_param_names=["u_GammaPower", "u_Saturation"],
    )
    state = AdjustmentState(best_params=dict(initial))

    first_params, first_decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=dict(initial),
            analysis=_channel_analysis(),
            diff_score=0.25,
            fit_score=0.75,
            state=state,
        )
    )
    assert first_decision["cross_engine_hybrid"]["phase"] == "calibration"
    assert first_decision["cross_engine_hybrid"]["param"] == "u_GammaPower"
    assert first_decision["cross_engine_hybrid"]["direction"] == pytest.approx(-1.0)

    second_params, second_decision = strategy.propose(
        StrategyContext(
            iteration=1,
            current_params=first_params,
            analysis=_channel_analysis(),
            diff_score=0.27,
            fit_score=0.73,
            state=state,
        )
    )
    assert second_decision["cross_engine_hybrid"]["param"] == "u_GammaPower"
    assert second_decision["cross_engine_hybrid"]["direction"] == pytest.approx(1.0)

    third_params, third_decision = strategy.propose(
        StrategyContext(
            iteration=2,
            current_params=second_params,
            analysis=_channel_analysis(),
            diff_score=0.20,
            fit_score=0.80,
            state=state,
        )
    )
    assert third_decision["cross_engine_hybrid"]["param"] == "u_Saturation"

    fourth_params, fourth_decision = strategy.propose(
        StrategyContext(
            iteration=3,
            current_params=third_params,
            analysis=_channel_analysis(),
            diff_score=0.19,
            fit_score=0.81,
            state=state,
        )
    )
    assert fourth_decision["cross_engine_hybrid"]["param"] == "u_Saturation"

    fifth_params, fifth_decision = strategy.propose(
        StrategyContext(
            iteration=4,
            current_params=fourth_params,
            analysis=_channel_analysis(),
            diff_score=0.24,
            fit_score=0.76,
            state=state,
        )
    )
    assert fifth_decision["cross_engine_hybrid"]["phase"] == "broad_pattern"
    assert fifth_decision["cross_engine_hybrid"]["param"] == "u_GammaPower"
    assert fifth_decision["cross_engine_hybrid"]["direction"] == pytest.approx(-1.0)
    assert fifth_params["u_GammaPower"] != initial["u_GammaPower"]


def test_cross_engine_hybrid_shrinks_stale_ranked_param_immediately():
    initial = _pattern16_params()
    strategy = CrossEngineHybridStrategy(
        initial_params=initial,
        shader_params=_pattern16_shader_params(),
        search_param_names=["u_GammaPower"],
        fixed_rounds_before_ranking=2,
    )
    state = AdjustmentState(best_params=dict(initial))

    first_params, _ = strategy.propose(
        StrategyContext(0, dict(initial), _channel_analysis(), 0.25, 0.75, state)
    )
    second_params, _ = strategy.propose(
        StrategyContext(1, first_params, _channel_analysis(), 0.20, 0.80, state)
    )
    third_params, third_decision = strategy.propose(
        StrategyContext(2, second_params, _channel_analysis(), 0.26, 0.74, state)
    )
    assert third_decision["cross_engine_hybrid"]["phase"] == "broad_pattern"

    fourth_params, _ = strategy.propose(
        StrategyContext(3, third_params, _channel_analysis(), 0.21, 0.79, state)
    )
    fifth_params, fifth_decision = strategy.propose(
        StrategyContext(4, fourth_params, _channel_analysis(), 0.22, 0.78, state)
    )
    assert fifth_decision["cross_engine_hybrid"]["phase"] == "ranked_pattern"
    sixth_params, _ = strategy.propose(
        StrategyContext(5, fifth_params, _channel_analysis(), 0.21, 0.79, state)
    )
    strategy.propose(
        StrategyContext(6, sixth_params, _channel_analysis(), 0.22, 0.78, state)
    )

    summary = strategy.research_summary()
    assert summary["steps"]["u_GammaPower"] == pytest.approx(
        summary["min_steps"]["u_GammaPower"] * 4.0
    )


def test_build_strategy_rejects_human_target_teacher_optimizer():
    with pytest.raises(ValueError, match="unknown optimizer"):
        build_strategy(
            optimizer="human_target",
            initial_params=_initial_params(),
            shader_params=_shader_params(),
            policies=build_adjustment_policies(_shader_params()),
            unity_material_params={},
        )


def test_pattern16_search_param_names_excludes_material_validity_params():
    names = pattern16_search_param_names(_pattern16_params(), _pattern16_shader_params())

    assert names == list(PATTERN16_PARAM_ORDER)
    assert "u_MainTex_ST" not in names
    assert "u_AlphaTestValue" not in names
    assert "u_SkyRotateX" not in names


def test_pattern16_zero_start_is_hard_but_not_destructive():
    baseline = _pattern16_params()
    baseline["u_Contrast"] = 1.25
    shader_params = _pattern16_shader_params()
    shader_params.append(ShaderParam("u_Contrast", "Float", default=1.0))
    names = pattern16_search_param_names(baseline, shader_params)

    zero_start = build_zero_searchable_initial_params(
        baseline,
        shader_params,
        search_param_names=names,
    )

    assert names == list(PATTERN16_PARAM_ORDER)
    for name in PATTERN16_PARAM_ORDER:
        assert zero_start[name] == pytest.approx(0.0)

    assert zero_start["u_Contrast"] == pytest.approx(1.25)
    assert zero_start["u_MainTex_ST"] == [1.0, 1.0, 0.0, 0.0]
    assert zero_start["u_AlphaTestValue"] == pytest.approx(0.5)
    assert zero_start["u_SkyRotateX"] == pytest.approx(231.0)

    strategy = build_strategy(
        optimizer="pattern16",
        initial_params=zero_start,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    first_params, first_decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=dict(zero_start),
            analysis=_channel_analysis(),
            diff_score=0.50,
            fit_score=0.50,
            state=AdjustmentState(best_params=dict(zero_start)),
        )
    )

    assert first_decision["pattern16"]["param"] == "u_GammaPower"
    assert first_params["u_GammaPower"] > 0.0


def test_pattern16_coordinate_search_accepts_best_direction_before_next_param():
    initial = _pattern16_params()
    strategy = build_strategy(
        optimizer="pattern16",
        initial_params=initial,
        shader_params=_pattern16_shader_params(),
        policies=build_adjustment_policies(_pattern16_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial))
    first_params, first_decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=dict(initial),
            analysis=_channel_analysis(),
            diff_score=0.18,
            fit_score=0.82,
            state=state,
        )
    )
    assert first_decision["optimizer"] == "pattern16"
    assert first_decision["pattern16"]["param"] == "u_GammaPower"
    assert first_decision["pattern16"]["direction"] == pytest.approx(-1.0)
    assert first_params["u_GammaPower"] == pytest.approx(1.20)

    second_params, second_decision = strategy.propose(
        StrategyContext(
            iteration=1,
            current_params=first_params,
            analysis=_channel_analysis(),
            diff_score=0.20,
            fit_score=0.80,
            state=state,
        )
    )
    assert second_decision["pattern16"]["param"] == "u_GammaPower"
    assert second_decision["pattern16"]["direction"] == pytest.approx(1.0)
    assert second_params["u_GammaPower"] == pytest.approx(1.90)

    third_params, third_decision = strategy.propose(
        StrategyContext(
            iteration=2,
            current_params=second_params,
            analysis=_channel_analysis(),
            diff_score=0.17,
            fit_score=0.83,
            state=state,
        )
    )
    assert third_decision["pattern16"]["param"] == "u_Saturation"
    assert third_decision["pattern16"]["previous_candidate"]["improved_local"] is True
    assert third_params["u_GammaPower"] == pytest.approx(1.90)
    assert third_params["u_Saturation"] == pytest.approx(0.65)


def test_cold_start_hybrid_locks_material_validity_params_out_of_search_space():
    initial_params = {
        "u_Color": [0.0, 0.0, 0.0, 1.0],
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_NormalTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_AlphaTestValue": 0.5,
        "u_SkyRotateX": 231.0,
        "u_GammaPower": 0.0,
        "u_SpecularIntensity": 0.0,
    }
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1.0, 1.0, 1.0, 1.0]),
        ShaderParam("u_MainTex_ST", "Vector4", default=[1.0, 1.0, 0.0, 0.0]),
        ShaderParam("u_NormalTex_ST", "Vector4", default=[1.0, 1.0, 0.0, 0.0]),
        ShaderParam("u_AlphaTestValue", "Float", default=0.5),
        ShaderParam("u_SkyRotateX", "Float", default=231.0),
        ShaderParam("u_GammaPower", "Float", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_SpecularIntensity", "Float", default=0.0, range_min=0.0, range_max=2.0),
    ]

    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )

    assert "u_GammaPower" in strategy._numeric_names  # type: ignore[attr-defined]
    assert "u_SpecularIntensity" in strategy._numeric_names  # type: ignore[attr-defined]
    assert "u_Color" in strategy._vector_names  # type: ignore[attr-defined]
    assert "u_AlphaTestValue" not in strategy._numeric_names  # type: ignore[attr-defined]
    assert "u_SkyRotateX" not in strategy._numeric_names  # type: ignore[attr-defined]
    assert "u_MainTex_ST" not in strategy._vector_names  # type: ignore[attr-defined]
    assert "u_NormalTex_ST" not in strategy._vector_names  # type: ignore[attr-defined]


def test_cold_start_hybrid_respects_explicit_search_param_names():
    initial_params = {
        "u_GammaPower": 0.0,
        "u_SpecularIntensity": 0.0,
        "u_RimIntensity": 0.0,
    }
    shader_params = [
        ShaderParam("u_GammaPower", "Float", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_SpecularIntensity", "Float", default=0.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_RimIntensity", "Float", default=0.0, range_min=0.0, range_max=3.0),
    ]

    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=["u_GammaPower"],
    )

    assert strategy._numeric_names == ["u_GammaPower"]  # type: ignore[attr-defined]


def test_cold_start_hybrid_bootstrap_uses_nonlocal_semantic_anchors():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_zero_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_zero_params()),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    batch = strategy.propose_many(ctx, count=6)  # type: ignore[attr-defined]

    proposals = [params for params, _decision in batch]
    decisions = [decision for _params, decision in batch]
    assert len(proposals) == 6
    assert {decision["stage"]["name"] for decision in decisions} == {"cold_start_bootstrap"}
    assert all(proposal != _zero_params() for proposal in proposals)
    assert any(float(proposal["u_Gamma_Power"]) >= 1.0 for proposal in proposals)
    assert any(float(proposal["u_SpecularIntensity"]) >= 0.5 for proposal in proposals)
    assert any(float(proposal["u_FresnelIntensity"]) >= 0.5 for proposal in proposals)
    assert any(
        sum(1 for value in proposal.values() if isinstance(value, (int, float)) and float(value) > 0.25) >= 4
        for proposal in proposals
    )


def test_cold_start_hybrid_bootstrap_can_use_exact_parameter_prior_anchor():
    selected_names = [
        "u_GammaPower",
        "u_Saturation",
        "u_TexPower",
        "u_AoPower",
        "u_EmissionPow",
        "u_IndirectStrength",
        "u_NormalScale",
        "u_ShadowSmoothness",
        "u_ShadowThreshold1",
        "u_ShadowThreshold2",
        "u_SpecularIntensity",
        "u_SpecularPower",
        "u_SpecularThreshold",
        "u_SpecularSmoothness",
        "u_RimIntensity",
        "u_RimWidth",
    ]
    initial_params = {name: 0.0 for name in selected_names}
    shader_params = [ShaderParam(name, "Range", default=0.0, range_min=0.0, range_max=8.0) for name in selected_names]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_params, first_decision = strategy.propose_many(ctx, count=1)[0]  # type: ignore[attr-defined]

    assert first_decision["cold_start_hybrid"]["meta"]["anchor"] == "pattern_prior_fish16"
    assert first_params["u_ShadowThreshold1"] == pytest.approx(0.24)
    assert first_params["u_ShadowThreshold2"] == pytest.approx(0.40)
    assert first_params["u_SpecularIntensity"] == pytest.approx(0.5855)
    assert first_params["u_RimWidth"] == pytest.approx(4.319)


def test_fish_standard_gamma_effective_bounds_keep_high_prior_reachable():
    assert effective_bounds_for_param("u_GammaPower") == pytest.approx((0.05, 10.0))


def test_cold_start_hybrid_prefers_external_prior_anchors_before_builtin_fallbacks():
    selected_names = [
        "u_GammaPower",
        "u_Saturation",
        "u_TexPower",
        "u_ShadowThreshold1",
        "u_ShadowThreshold2",
    ]
    initial_params = {name: 0.0 for name in selected_names}
    shader_params = [ShaderParam(name, "Range", default=0.0, range_min=0.0, range_max=8.0) for name in selected_names]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": {
                    "u_GammaPower": 2.25,
                    "u_Saturation": 1.10,
                    "u_TexPower": 1.75,
                    "u_ShadowThreshold1": 0.18,
                    "u_ShadowThreshold2": 0.42,
                },
            }
        ],
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_params, first_decision = strategy.propose_many(ctx, count=1)[0]  # type: ignore[attr-defined]

    assert first_decision["cold_start_hybrid"]["meta"]["anchor"] == "external_case_prior"
    assert first_params["u_GammaPower"] == pytest.approx(2.25)
    assert first_params["u_Saturation"] == pytest.approx(1.10)
    assert first_params["u_TexPower"] == pytest.approx(1.75)
    assert first_params["u_ShadowThreshold1"] == pytest.approx(0.18)
    assert first_params["u_ShadowThreshold2"] == pytest.approx(0.42)


def test_cold_start_hybrid_external_prior_anchor_can_pin_vector_param_values():
    initial_params = {
        "u_GammaPower": 0.0,
        "u_Color": [0.0, 0.0, 0.0, 1.0],
        "u_RimColor": [0.0, 0.0, 0.0, 0.5],
    }
    shader_params = [
        ShaderParam("u_GammaPower", "Range", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_Color", "Color", default=[0.0, 0.0, 0.0, 1.0]),
        ShaderParam("u_RimColor", "Color", default=[0.0, 0.0, 0.0, 0.5]),
    ]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": {
                    "u_GammaPower": 2.25,
                    "u_Color": [0.86, 0.84, 0.70, 0.25],
                    "u_RimColor": [0.10, 1.00, 0.96, 0.25],
                },
            }
        ],
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_params, first_decision = strategy.propose_many(ctx, count=1)[0]  # type: ignore[attr-defined]

    assert first_decision["cold_start_hybrid"]["meta"]["anchor"] == "external_case_prior"
    assert first_params["u_GammaPower"] == pytest.approx(2.25)
    assert first_params["u_Color"] == pytest.approx([0.86, 0.84, 0.70, 1.0])
    assert first_params["u_RimColor"] == pytest.approx([0.10, 1.00, 0.96, 0.5])


def test_cold_start_hybrid_external_param_values_do_not_apply_missing_semantic_defaults():
    initial_params = {
        "u_GammaPower": 0.0,
        "u_Metallic": 0.75,
        "u_BaseColor": [0.10, 0.20, 0.30, 1.0],
    }
    shader_params = [
        ShaderParam("u_GammaPower", "Range", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_Metallic", "Range", default=0.75, range_min=0.0, range_max=1.0),
        ShaderParam("u_BaseColor", "Color", default=[0.10, 0.20, 0.30, 1.0]),
    ]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": {"u_GammaPower": 2.25},
            }
        ],
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_params, first_decision = strategy.propose_many(ctx, count=1)[0]  # type: ignore[attr-defined]

    assert first_decision["cold_start_hybrid"]["meta"]["anchor"] == "external_case_prior"
    assert first_params["u_GammaPower"] == pytest.approx(2.25)
    assert first_params["u_Metallic"] == pytest.approx(0.75)
    assert first_params["u_BaseColor"] == pytest.approx([0.10, 0.20, 0.30, 1.0])


def test_cold_start_hybrid_bootstrap_maps_plain_u_color_to_base_color_anchor():
    initial_params = {"u_Color": [0.0, 0.0, 0.0, 1.0]}
    shader_params = [ShaderParam("u_Color", "Color", default=[0.0, 0.0, 0.0, 1.0])]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_params, first_decision = strategy.propose_many(ctx, count=1)[0]  # type: ignore[attr-defined]

    assert first_decision["stage"]["name"] == "cold_start_bootstrap"
    assert first_params["u_Color"][:3] == pytest.approx([
        0.8565891472868217,
        0.8565891472868217,
        0.8565891472868217,
    ])
    assert first_params["u_Color"][3] == pytest.approx(1.0)


def test_cold_start_hybrid_uses_bootstrap_winner_for_group_sweep():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_zero_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_zero_params()),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )
    first_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    best_bootstrap = first_batch[1][0]

    strategy.tell_many_scores([(0.68, 0.32), (0.82, 0.18), (0.74, 0.26), (0.70, 0.30)])  # type: ignore[attr-defined]
    second_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert second_batch
    assert {decision["stage"]["name"] for _params, decision in second_batch} == {"cold_start_group_sweep"}
    assert all(params != _zero_params() for params, _decision in second_batch)
    assert all(float(params["u_Gamma_Power"]) == pytest.approx(float(best_bootstrap["u_Gamma_Power"])) for params, _decision in second_batch)
    assert any(
        params["u_SpecularIntensity"] != best_bootstrap["u_SpecularIntensity"]
        or params["u_FresnelIntensity"] != best_bootstrap["u_FresnelIntensity"]
        for params, _decision in second_batch
    )


def test_cold_start_hybrid_can_continue_after_first_group_batch():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_zero_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_zero_params()),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )
    first_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.70 + i * 0.01, 0.30 - i * 0.01) for i in range(len(first_batch))])  # type: ignore[attr-defined]

    group_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.80 + i * 0.001, 0.20 - i * 0.001) for i in range(len(group_batch))])  # type: ignore[attr-defined]
    next_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]

    assert next_batch
    assert all(
        decision["stage"]["name"] in {
            "cold_start_group_sweep",
            "cold_start_archive_recombine",
            "cold_start_refine",
        }
        for _params, decision in next_batch
    )


def test_cold_start_hybrid_recombines_archive_after_group_sweep_before_refine():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    base = dict(_initial_params())
    donor = {
        **base,
        "u_Gamma_Power": 1.15,
        "u_SpecularIntensity": 1.85,
        "u_FresnelIntensity": 1.55,
        "u_BaseColor": [0.58, 0.40, 0.18, 1.0],
    }
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=0,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "group_sweep"  # type: ignore[attr-defined]
    strategy._group_queue = []  # type: ignore[attr-defined]
    strategy._group_queue_built = True  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._archive = [  # type: ignore[attr-defined]
        {
            "phase": "bootstrap",
            "meta": {"anchor": "best"},
            "params": base,
            "fit_score": 0.90,
            "diff_score": 0.10,
        },
        {
            "phase": "group_sweep",
            "meta": {"group": "rim"},
            "params": donor,
            "fit_score": 0.89,
            "diff_score": 0.11,
        },
    ]

    batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_archive_recombine"}
    assert strategy.research_summary()["phase"] == "archive_recombine"
    assert any(
        params["u_Gamma_Power"] == pytest.approx(base["u_Gamma_Power"])
        and params["u_SpecularIntensity"] == pytest.approx(donor["u_SpecularIntensity"])
        for params, _decision in batch
    )
    assert any(
        params["u_BaseColor"][:3] != base["u_BaseColor"][:3]
        for params, _decision in batch
    )


def test_cold_start_hybrid_runs_short_recombine_before_cma_when_external_prior_archive_is_high():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": dict(_initial_params()),
            }
        ],
    )
    base = dict(_initial_params())
    archive = [
        {
            "phase": "bootstrap",
            "meta": {"anchor": "external_case_prior"},
            "params": base,
            "fit_score": 0.895,
            "diff_score": 0.105,
        }
    ]
    for index in range(8):
        donor = {
            **base,
            "u_Gamma_Power": 2.0 + index * 0.08,
            "u_SpecularIntensity": 0.85 + index * 0.03,
            "u_FresnelIntensity": 0.75 + index * 0.02,
            "u_BaseColor": [0.32 + index * 0.01, 0.27, 0.07, 1.0],
        }
        archive.append(
            {
                "phase": "group_sweep",
                "meta": {"group": f"near_elite_{index}"},
                "params": donor,
                "fit_score": 0.894 - index * 0.0005,
                "diff_score": 0.106 + index * 0.0005,
            }
        )
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=64,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.105,
        fit_score=0.895,
        state=state,
    )

    strategy._phase = "group_sweep"  # type: ignore[attr-defined]
    strategy._group_queue = []  # type: ignore[attr-defined]
    strategy._group_queue_built = True  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.895  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.105  # type: ignore[attr-defined]
    strategy._archive = archive  # type: ignore[attr-defined]

    batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_archive_recombine"}
    assert strategy.research_summary()["phase"] == "archive_recombine"
    assert strategy.research_summary()["archive_recombine_next_phase"] == "cma_refine"

    strategy._archive_recombine_queue = []  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.890, 0.110) for _params, _decision in batch])  # type: ignore[attr-defined]
    cma_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert cma_batch
    assert {decision["stage"]["name"] for _params, decision in cma_batch} == {"cold_start_cma_refine"}
    assert all("cma_es" in decision for _params, decision in cma_batch)
    assert strategy.research_summary()["phase"] == "cma_refine"


def test_cold_start_hybrid_fast_track_recombine_total_budget_stops_after_improvement():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": dict(_initial_params()),
            }
        ],
    )
    base = dict(_initial_params())
    archive = [
        {
            "phase": "bootstrap",
            "meta": {"anchor": "external_case_prior"},
            "params": base,
            "fit_score": 0.895,
            "diff_score": 0.105,
        }
    ]
    for index in range(8):
        donor = {
            **base,
            "u_Gamma_Power": 2.0 + index * 0.08,
            "u_SpecularIntensity": 0.85 + index * 0.03,
            "u_FresnelIntensity": 0.75 + index * 0.02,
            "u_BaseColor": [0.32 + index * 0.01, 0.27, 0.07, 1.0],
        }
        archive.append(
            {
                "phase": "group_sweep",
                "meta": {"group": f"near_elite_{index}"},
                "params": donor,
                "fit_score": 0.894 - index * 0.0005,
                "diff_score": 0.106 + index * 0.0005,
            }
        )
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=64,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.105,
        fit_score=0.895,
        state=state,
    )

    strategy._phase = "group_sweep"  # type: ignore[attr-defined]
    strategy._group_queue = []  # type: ignore[attr-defined]
    strategy._group_queue_built = True  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.895  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.105  # type: ignore[attr-defined]
    strategy._archive = archive  # type: ignore[attr-defined]
    batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    strategy._archive_recombine_fast_track_evaluations = 60  # type: ignore[attr-defined]
    strategy._archive_recombine_queue = [{"params": base, "meta": {"left": "over"}}]  # type: ignore[attr-defined]

    strategy.tell_many_scores([(0.901, 0.099) for _params, _decision in batch])  # type: ignore[attr-defined]
    cma_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert cma_batch
    assert {decision["stage"]["name"] for _params, decision in cma_batch} == {"cold_start_cma_refine"}
    assert strategy.research_summary()["phase"] == "cma_refine"


def test_cold_start_hybrid_fast_track_accepts_conservative_lower_quartile_scores():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        cold_start_prior_anchors=[
            {
                "label": "external_case_prior",
                "param_values": dict(_initial_params()),
            }
        ],
    )
    base = dict(_initial_params())
    archive = [
        {
            "phase": "bootstrap",
            "meta": {"anchor": "external_case_prior"},
            "params": base,
            "fit_score": 0.875,
            "diff_score": 0.125,
        }
    ]
    for index in range(8):
        donor = {
            **base,
            "u_Gamma_Power": 2.0 + index * 0.08,
            "u_SpecularIntensity": 0.85 + index * 0.03,
            "u_FresnelIntensity": 0.75 + index * 0.02,
            "u_BaseColor": [0.32 + index * 0.01, 0.27, 0.07, 1.0],
        }
        archive.append(
            {
                "phase": "group_sweep",
                "meta": {"group": f"near_elite_{index}"},
                "params": donor,
                "fit_score": 0.874 - index * 0.0005,
                "diff_score": 0.126 + index * 0.0005,
            }
        )
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=64,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.125,
        fit_score=0.875,
        state=state,
    )

    strategy._phase = "group_sweep"  # type: ignore[attr-defined]
    strategy._group_queue = []  # type: ignore[attr-defined]
    strategy._group_queue_built = True  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.875  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.125  # type: ignore[attr-defined]
    strategy._archive = archive  # type: ignore[attr-defined]

    batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_archive_recombine"}
    assert strategy.research_summary()["archive_recombine_fast_track"] is True
    assert strategy.research_summary()["archive_recombine_next_phase"] == "cma_refine"


def test_cold_start_hybrid_archive_recombine_queue_is_budget_capped():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    base = dict(_initial_params())
    archive = [
        {
            "phase": "bootstrap",
            "meta": {},
            "params": base,
            "fit_score": 0.90,
            "diff_score": 0.10,
        }
    ]
    for index in range(10):
        donor = {
            **base,
            "u_Gamma_Power": 1.0 + index * 0.22,
            "u_SpecularIntensity": 0.55 + index * 0.08,
            "u_FresnelIntensity": 0.35 + index * 0.06,
            "u_OcclusionStrength": 0.45 + index * 0.05,
            "u_DiffuseThreshold": 0.20 + index * 0.035,
            "u_BaseColor": [0.30 + index * 0.03, 0.25 + index * 0.02, 0.10 + index * 0.01, 1.0],
        }
        archive.append(
            {
                "phase": "refine",
                "meta": {},
                "params": donor,
                "fit_score": 0.899 - index * 0.001,
                "diff_score": 0.101 + index * 0.001,
            }
        )
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._archive = archive  # type: ignore[attr-defined]

    queue = strategy._build_archive_recombine_queue()  # type: ignore[attr-defined]

    assert queue
    assert len(queue) <= strategy._max_archive_recombine_candidates  # type: ignore[attr-defined]


def test_cold_start_hybrid_group_sweep_includes_balanced_energy_lift_probe():
    selected_names = [
        "u_GammaPower",
        "u_Saturation",
        "u_TexPower",
        "u_AoPower",
        "u_IndirectStrength",
        "u_NormalScale",
        "u_SpecularIntensity",
        "u_SpecularPower",
        "u_SpecularThreshold",
        "u_RimIntensity",
        "u_RimWidth",
    ]
    initial_params = {name: 0.0 for name in selected_names}
    shader_params = [ShaderParam(name, "Range", default=0.0, range_min=0.0, range_max=10.0) for name in selected_names]
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.90 - i * 0.01, 0.10 + i * 0.01) for i in range(len(first_batch))])  # type: ignore[attr-defined]
    group_batch = strategy.propose_many(ctx, count=32)  # type: ignore[attr-defined]

    lift = next(
        (
            (params, decision)
            for params, decision in group_batch
            if decision["cold_start_hybrid"]["meta"].get("group") == "balanced_energy_lift"
        ),
        None,
    )

    assert lift is not None
    params, decision = lift
    base = first_batch[0][0]
    changed = set(decision["cold_start_hybrid"]["meta"].get("changed_params", []))
    assert {"u_IndirectStrength", "u_SpecularIntensity", "u_SpecularThreshold", "u_RimIntensity"} <= changed
    assert params["u_IndirectStrength"] > base["u_IndirectStrength"]
    assert params["u_SpecularIntensity"] > base["u_SpecularIntensity"]
    assert params["u_SpecularThreshold"] > base["u_SpecularThreshold"]
    assert params["u_RimIntensity"] > base["u_RimIntensity"]
    assert params["u_SpecularPower"] < base["u_SpecularPower"]


def test_cold_start_hybrid_uses_diversity_probe_before_cma_after_archive_recombine():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_zero_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_zero_params()),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )
    strategy._phase = "archive_recombine"  # type: ignore[attr-defined]
    strategy._archive_recombine_round = strategy._max_archive_recombine_rounds  # type: ignore[attr-defined]
    strategy._archive_recombine_next_phase = "cma_refine"  # type: ignore[attr-defined]
    strategy._archive_recombine_queue = []  # type: ignore[attr-defined]
    strategy._best_params = dict(_initial_params())  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    donor = {
        **dict(_initial_params()),
        "u_Gamma_Power": 2.32,
        "u_SpecularIntensity": 1.12,
        "u_FresnelIntensity": 0.88,
    }
    strategy._archive = [  # type: ignore[attr-defined]
        {
            "phase": "refine",
            "meta": {},
            "params": dict(_initial_params()),
            "fit_score": 0.90,
            "diff_score": 0.10,
        },
        {
            "phase": "refine",
            "meta": {},
            "params": donor,
            "fit_score": 0.899,
            "diff_score": 0.101,
        },
    ]

    diversity_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert diversity_batch
    assert {decision["stage"]["name"] for _params, decision in diversity_batch} == {"cold_start_diversity_probe"}
    assert strategy.research_summary()["diversity_probe_next_phase"] == "cma_refine"

    strategy._diversity_probe_queue = []  # type: ignore[attr-defined]
    strategy._diversity_probe_round = strategy._max_diversity_probe_rounds - 1  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.80, 0.20) for _params, _decision in diversity_batch])  # type: ignore[attr-defined]
    cma_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert cma_batch
    assert {decision["stage"]["name"] for _params, decision in cma_batch} == {"cold_start_cma_refine"}
    assert all("cma_es" in decision for _params, decision in cma_batch)
    assert strategy.research_summary()["phase"] == "cma_refine"


def test_cold_start_hybrid_uses_best_anchor_extension_after_refine_plateau():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_zero_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_zero_params()),
        analysis=_channel_analysis(),
        diff_score=0.35,
        fit_score=0.65,
        state=state,
    )

    first_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.70 + i * 0.001, 0.30 - i * 0.001) for i in range(len(first_batch))])  # type: ignore[attr-defined]
    group_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]
    strategy.tell_many_scores([(0.80 + i * 0.001, 0.20 - i * 0.001) for i in range(len(group_batch))])  # type: ignore[attr-defined]

    strategy._phase = "refine"  # type: ignore[attr-defined]
    strategy._refine_step_ratio = 0.001  # type: ignore[attr-defined]
    strategy._refine_queue = []  # type: ignore[attr-defined]

    extension_batch = strategy.propose_many(ctx, count=8)  # type: ignore[attr-defined]

    assert strategy.stop_reason() is None
    assert extension_batch
    assert {decision["stage"]["name"] for _params, decision in extension_batch} == {"cold_start_best_anchor_refine"}
    assert all(
        1 <= len(decision["cold_start_hybrid"]["meta"].get("changed_params", [])) <= 2
        for _params, decision in extension_batch
    )
    assert all(
        decision["cold_start_hybrid"]["meta"].get("center") == "best"
        for _params, decision in extension_batch
    )


def test_cold_start_hybrid_best_anchor_keeps_remaining_queue_before_shrinking():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "best_anchor_refine"  # type: ignore[attr-defined]
    strategy._best_params = dict(_initial_params())  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._best_anchor_step_ratio = 0.012  # type: ignore[attr-defined]
    strategy._best_anchor_round = 0  # type: ignore[attr-defined]

    first_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    first_changes = [
        tuple(decision["cold_start_hybrid"]["meta"].get("changed_params", []))
        for _params, decision in first_batch
    ]
    strategy.tell_many_scores([(0.80, 0.20) for _params, _decision in first_batch])  # type: ignore[attr-defined]
    second_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    second_changes = [
        tuple(decision["cold_start_hybrid"]["meta"].get("changed_params", []))
        for _params, decision in second_batch
    ]

    summary = strategy.research_summary()
    assert summary["best_anchor_step_ratio"] == pytest.approx(0.012)
    assert summary["best_anchor_round"] == 0
    assert second_changes != first_changes


def test_cold_start_hybrid_uses_correlated_refine_after_best_anchor_plateau():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "best_anchor_refine"  # type: ignore[attr-defined]
    strategy._best_params = dict(_initial_params())  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._best_anchor_round = strategy._max_best_anchor_rounds  # type: ignore[attr-defined]

    batch = strategy.propose_many(ctx, count=6)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_correlated_refine"}
    assert any(
        len(decision["cold_start_hybrid"]["meta"].get("changed_params", [])) >= 3
        for _params, decision in batch
    )
    summary = strategy.research_summary()
    assert summary["phase"] == "correlated_refine"
    assert summary["correlated_step_ratio"] > 0.0


def test_cold_start_hybrid_diversity_probe_escapes_elite_plateau():
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    base = dict(_initial_params())
    near_a = {
        **base,
        "u_Gamma_Power": 2.23,
        "u_SpecularIntensity": 1.03,
        "u_FresnelIntensity": 0.97,
    }
    near_b = {
        **base,
        "u_Gamma_Power": 2.17,
        "u_OcclusionStrength": 1.04,
        "u_DiffuseThreshold": 0.48,
    }
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=0,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "diversity_probe"  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._archive = [  # type: ignore[attr-defined]
        {"phase": "bootstrap", "meta": {}, "params": base, "fit_score": 0.90, "diff_score": 0.10},
        {"phase": "refine", "meta": {}, "params": near_a, "fit_score": 0.899, "diff_score": 0.101},
        {"phase": "refine", "meta": {}, "params": near_b, "fit_score": 0.898, "diff_score": 0.102},
    ]

    batch = strategy.propose_many(ctx, count=10)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_diversity_probe"}
    assert any(
        len(decision["cold_start_hybrid"]["meta"].get("changed_params", [])) >= 4
        for _params, decision in batch
    )
    archive_params = [record["params"] for record in strategy._archive]  # type: ignore[attr-defined]
    min_distances = [
        min(_normalized_distance_for_test(params, reference, shader_params) for reference in archive_params)
        for params, _decision in batch
    ]
    assert min(min_distances) >= 0.045


def test_cold_start_hybrid_diversity_probe_is_budget_capped_before_refine():
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    base = dict(_initial_params())
    near = {
        **base,
        "u_Gamma_Power": 2.17,
        "u_OcclusionStrength": 1.04,
        "u_DiffuseThreshold": 0.48,
    }
    state = AdjustmentState(best_params=base)
    ctx = StrategyContext(
        iteration=0,
        current_params=base,
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "diversity_probe"  # type: ignore[attr-defined]
    strategy._best_params = base  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._archive = [  # type: ignore[attr-defined]
        {"phase": "bootstrap", "meta": {}, "params": base, "fit_score": 0.90, "diff_score": 0.10},
        {"phase": "refine", "meta": {}, "params": near, "fit_score": 0.899, "diff_score": 0.101},
    ]
    diversity_queue = strategy._build_diversity_probe_queue()  # type: ignore[attr-defined]
    assert len(diversity_queue) <= strategy._max_diversity_probe_candidates  # type: ignore[attr-defined]
    strategy._diversity_probe_queue = diversity_queue  # type: ignore[attr-defined]

    batch = strategy.propose_many(ctx, count=64)  # type: ignore[attr-defined]
    stages = [decision["stage"]["name"] for _params, decision in batch]

    assert stages.count("cold_start_diversity_probe") <= strategy._max_diversity_probe_candidates  # type: ignore[attr-defined]
    assert "cold_start_refine" in stages


def test_cold_start_hybrid_refine_keeps_remaining_queue_before_shrinking():
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=_zero_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "refine"  # type: ignore[attr-defined]
    strategy._best_params = dict(_initial_params())  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._refine_step_ratio = 0.04  # type: ignore[attr-defined]
    strategy._refine_round = 0  # type: ignore[attr-defined]

    first_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    first_changes = [
        tuple(decision["cold_start_hybrid"]["meta"].get("changed_params", []))
        for _params, decision in first_batch
    ]
    strategy.tell_many_scores([(0.80, 0.20) for _params, _decision in first_batch])  # type: ignore[attr-defined]
    second_batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]
    second_changes = [
        tuple(decision["cold_start_hybrid"]["meta"].get("changed_params", []))
        for _params, decision in second_batch
    ]

    summary = strategy.research_summary()
    assert summary["refine_step_ratio"] == pytest.approx(0.04)
    assert second_changes != first_changes


def test_cold_start_hybrid_refine_can_search_color_vectors():
    shader_params = [
        ShaderParam("u_BaseColor", "Color", default=[0.0, 0.0, 0.0, 1.0]),
        ShaderParam("u_SpecularColor", "Color", default=[0.0, 0.0, 0.0, 1.0]),
    ]
    initial_params = {
        "u_BaseColor": [0.40, 0.35, 0.20, 1.0],
        "u_SpecularColor": [0.65, 0.62, 0.55, 0.75],
    }
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "refine"  # type: ignore[attr-defined]
    strategy._best_params = dict(initial_params)  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._refine_step_ratio = 0.10  # type: ignore[attr-defined]

    batch = strategy.propose_many(ctx, count=6)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_refine"}
    assert any(params["u_BaseColor"] != initial_params["u_BaseColor"] for params, _decision in batch)
    assert any(params["u_SpecularColor"] != initial_params["u_SpecularColor"] for params, _decision in batch)
    assert all(params["u_BaseColor"][3] == pytest.approx(1.0) for params, _decision in batch)
    assert all(params["u_SpecularColor"][3] == pytest.approx(0.75) for params, _decision in batch)
    assert all(
        decision["cold_start_hybrid"]["meta"].get("changed_params")
        for _params, decision in batch
    )


def test_cold_start_hybrid_cma_refine_includes_color_vectors():
    shader_params = [
        ShaderParam("u_BaseColor", "Color", default=[0.0, 0.0, 0.0, 1.0]),
        ShaderParam("u_SpecularColor", "Color", default=[0.0, 0.0, 0.0, 1.0]),
    ]
    initial_params = {
        "u_BaseColor": [0.40, 0.35, 0.20, 1.0],
        "u_SpecularColor": [0.65, 0.62, 0.55, 0.75],
    }
    strategy = build_strategy(
        optimizer="cold_start_hybrid",
        initial_params=initial_params,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
    )
    state = AdjustmentState(best_params=dict(initial_params))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial_params),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.90,
        state=state,
    )

    strategy._phase = "cma_refine"  # type: ignore[attr-defined]
    strategy._best_params = dict(initial_params)  # type: ignore[attr-defined]
    strategy._best_fit_score = 0.90  # type: ignore[attr-defined]
    strategy._best_diff_score = 0.10  # type: ignore[attr-defined]
    strategy._archive = [  # type: ignore[attr-defined]
        {
            "phase": "bootstrap",
            "meta": {"anchor": "seed"},
            "params": dict(initial_params),
            "fit_score": 0.90,
            "diff_score": 0.10,
        },
        {
            "phase": "refine",
            "meta": {"param": "u_BaseColor"},
            "params": {**initial_params, "u_BaseColor": [0.45, 0.35, 0.20, 1.0]},
            "fit_score": 0.89,
            "diff_score": 0.11,
        },
    ]

    batch = strategy.propose_many(ctx, count=4)  # type: ignore[attr-defined]

    assert batch
    assert {decision["stage"]["name"] for _params, decision in batch} == {"cold_start_cma_refine"}
    assert strategy.research_summary()["cma_refine_active"] is True
    assert strategy._cma_refine_strategy.trainable_dim == 6  # type: ignore[attr-defined]


def test_cma_initial_design_precedes_cma_and_warm_starts_from_scores():
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=CmaesStrategyConfig(
            mode="warm",
            seed=7,
            population_size=4,
            initial_design_samples=3,
            initial_design_method="latin_hypercube",
            initial_design_include_current=True,
        ),
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.80,
        fit_score=0.20,
        state=state,
    )

    first_batch = strategy.propose_many(ctx, count=2)

    assert len(first_batch) == 2
    assert first_batch[0][0] == _initial_params()
    assert [decision["stage"]["name"] for _, decision in first_batch] == [
        "cma_initial_design",
        "cma_initial_design",
    ]
    assert first_batch[0][1]["cma_es"]["initial_design"] == {
        "enabled": True,
        "method": "latin_hypercube",
        "requested_samples": 3,
        "include_current": True,
        "evaluated_samples": 0,
        "pending_samples": 2,
        "remaining_samples": 1,
        "completed": False,
    }

    strategy.tell_many_scores([(0.20, 0.80), (0.70, 0.30)])
    second_batch = strategy.propose_many(ctx, count=2)

    assert len(second_batch) == 1
    assert second_batch[0][1]["stage"]["name"] == "cma_initial_design"

    strategy.tell_many_scores([(0.55, 0.45)])
    cma_batch = strategy.propose_many(ctx, count=2)

    assert len(cma_batch) == 2
    assert [decision["stage"]["name"] for _, decision in cma_batch] == [
        "cma_warm",
        "cma_warm",
    ]
    cma_info = cma_batch[0][1]["cma_es"]
    assert cma_info["warm_started"] is True
    assert cma_info["warm_start_iters_used"] == 3
    assert cma_info["initial_design"]["completed"] is True
    assert cma_info["initial_design"]["best_fit_score"] == pytest.approx(0.70)


def test_cma_initial_design_local_coordinate_probe_samples_near_current():
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=CmaesStrategyConfig(
            mode="warm",
            seed=7,
            population_size=4,
            initial_design_samples=5,
            initial_design_method="local_coordinate_probe",
            initial_design_include_current=True,
            initial_design_local_step_ratio=0.05,
        ),
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.80,
        fit_score=0.20,
        state=state,
    )

    batch = strategy.propose_many(ctx, count=5)

    proposals = [params for params, _decision in batch]
    decisions = [decision for _params, decision in batch]
    assert proposals[0] == _initial_params()
    assert proposals[1]["u_BaseColor"] == pytest.approx([0.37, 0.27, 0.07, 1.0])
    assert proposals[2]["u_BaseColor"] == pytest.approx([0.27, 0.27, 0.07, 1.0])
    assert proposals[3]["u_BaseColor"] == pytest.approx([0.32, 0.32, 0.07, 1.0])
    assert proposals[4]["u_BaseColor"] == pytest.approx([0.32, 0.22, 0.07, 1.0])
    assert decisions[0]["cma_es"]["initial_design"]["method"] == "local_coordinate_probe"
    assert decisions[0]["cma_es"]["initial_design"]["local_step_ratio"] == pytest.approx(0.05)


def test_build_strategy_preserves_local_coordinate_probe_step_ratio():
    strategy = build_strategy(
        optimizer="cma_warm",
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        cma_es_config=CmaesStrategyConfig(
            seed=7,
            population_size=4,
            initial_design_samples=3,
            initial_design_method="local_coordinate_probe",
            initial_design_local_step_ratio=0.03,
        ),
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.80,
        fit_score=0.20,
        state=state,
    )

    batch = strategy.propose_many(ctx, count=3)  # type: ignore[attr-defined]

    assert batch[0][1]["cma_es"]["initial_design"]["local_step_ratio"] == pytest.approx(0.03)


# --------------------------------------------------------------------
# HeuristicStrategy


def test_heuristic_strategy_marks_decision_with_optimizer():
    policies = build_adjustment_policies(_shader_params())
    strategy = HeuristicStrategy(policies, _shader_params(), unity_material_params={})
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.20,
        state=state,
    )
    next_params, decision = strategy.propose(ctx)

    assert decision["optimizer"] == "heuristic"
    assert isinstance(next_params, dict)
    # Heuristic should at least have considered/changed *something* on a
    # non-trivial channel bias input.
    assert "stage" in decision
    assert decision["stage"]["name"] is not None


def test_heuristic_strategy_with_no_policies_returns_unchanged_params():
    strategy = HeuristicStrategy([], _shader_params(), unity_material_params={})
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.20,
        state=state,
    )
    next_params, decision = strategy.propose(ctx)
    assert decision["stop_reason"] == "no_policies"
    assert decision["optimizer"] == "heuristic"
    assert next_params == _initial_params()


# --------------------------------------------------------------------
# CmaesStrategy


def test_cmaes_strategy_propose_advances_evaluations_after_each_iteration():
    """Each propose() call must (a) tell back the previous fitness if any,
    and (b) ask for a new candidate. Over N iterations the optimizer's
    ``evaluations`` counter must equal N - 1 (the very first propose has
    no previous fitness to tell)."""
    config = CmaesStrategyConfig(mode="cold", seed=11)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    fit_scores = [0.20, 0.32, 0.41, 0.55, 0.62]
    last_decision = None
    current = dict(_initial_params())
    for i, fit in enumerate(fit_scores):
        ctx = StrategyContext(
            iteration=i,
            current_params=current,
            analysis=_channel_analysis(),
            diff_score=1.0 - fit,
            fit_score=fit,
            state=state,
        )
        next_params, decision = strategy.propose(ctx)
        current = next_params
        last_decision = decision

    assert last_decision is not None
    assert last_decision["optimizer"] == "cma_es"
    cma_info = last_decision["cma_es"]
    assert cma_info["trainable_dim"] >= 8  # ~25 axes for our slice
    assert cma_info["evaluations"] == len(fit_scores) - 1  # last ask not yet told
    # In each propose() call we tell back the fitness of the *current*
    # context — which corresponds to the candidate proposed in the
    # previous iteration. So after the final propose, the most recent
    # tell was for fit_scores[-1] (the last fit_score we observed before
    # asking again).
    assert cma_info["last_loss_fed"] == pytest.approx(1.0 - fit_scores[-1])


def test_cmaes_strategy_propose_many_tell_many_scores_advances_batch():
    """Batch mode separates candidate generation from observation.

    This is the strategy-level contract the auto-adjust loop needs before
    it can render/analyse several CMA-ES candidates in parallel.
    """
    config = CmaesStrategyConfig(mode="cold", seed=31, population_size=4)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.60,
        fit_score=0.40,
        state=state,
    )

    batch = strategy.propose_many(ctx, count=4)

    assert len(batch) == 4
    assert all(decision["optimizer"] == "cma_es" for _, decision in batch)
    assert [decision["cma_es"]["batch"]["index"] for _, decision in batch] == [0, 1, 2, 3]
    assert all(decision["cma_es"]["batch"]["size"] == 4 for _, decision in batch)
    assert all(decision["cma_es"]["evaluations"] == 0 for _, decision in batch)

    strategy.tell_many_scores(
        [
            (0.10, 0.90),
            (0.25, 0.75),
            (0.45, 0.55),
            (0.35, 0.65),
        ]
    )

    next_batch = strategy.propose_many(ctx, count=2)
    _, decision = next_batch[0]
    assert decision["cma_es"]["evaluations"] == 4
    assert decision["cma_es"]["last_loss_fed"] == pytest.approx(1.0 - 0.35)
    assert decision["cma_es"]["best_fitness"] == pytest.approx(1.0 - 0.45)


def test_cmaes_strategy_batch_mode_rejects_single_pending_candidate():
    config = CmaesStrategyConfig(mode="cold", seed=41, population_size=4)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose(ctx)

    with pytest.raises(RuntimeError, match="single pending candidate"):
        strategy.propose_many(ctx, count=2)


def test_cmaes_strategy_single_mode_rejects_pending_batch():
    config = CmaesStrategyConfig(mode="cold", seed=43, population_size=4)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=2)

    with pytest.raises(RuntimeError, match="batch candidates are pending"):
        strategy.propose(ctx)


def test_cmaes_strategy_tell_many_scores_requires_exact_pending_batch_count():
    config = CmaesStrategyConfig(mode="cold", seed=47, population_size=4)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )
    strategy.propose_many(ctx, count=2)

    with pytest.raises(RuntimeError, match="expected 2 score pairs"):
        strategy.tell_many_scores([(0.20, 0.80)])

    strategy.tell_many_scores([(0.20, 0.80), (0.40, 0.60)])
    next_batch = strategy.propose_many(ctx, count=1)
    _, decision = next_batch[0]
    assert decision["cma_es"]["evaluations"] == 2


def test_cmaes_strategy_stagnation_stop_reason_waits_for_min_evaluations():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=49,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=5,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert strategy.stop_reason() is None


def test_cmaes_strategy_stagnation_stop_reason_after_no_significant_gain():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=51,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert strategy.stop_reason() == "cmaes_stagnation"
    _, decision = strategy.propose_many(ctx, count=1)[0]
    assert decision["cma_es"]["stagnation"]["active"] is True
    assert decision["cma_es"]["stagnation"]["plateau"] is True


def test_cmaes_strategy_restarts_once_on_stagnation_before_stopping():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=55,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=1,
        restart_population_multiplier=2.0,
        restart_max_population_size=10,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert strategy.stop_reason() is None
    next_batch = strategy.propose_many(ctx, count=1)
    _, decision = next_batch[0]
    assert decision["cma_es"]["restarts"]["count"] == 1
    assert decision["cma_es"]["restarts"]["max"] == 1
    assert decision["cma_es"]["restarts"]["population_size"] == 8
    assert decision["cma_es"]["stagnation"]["evaluations_since_restart"] == 0

    strategy.tell_many_scores([(0.50, 0.50)])
    strategy.propose_many(ctx, count=3)
    strategy.tell_many_scores(
        [
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert strategy.stop_reason() == "cmaes_stagnation"


def test_cmaes_strategy_can_restart_from_random_center():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=58,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=1,
        restart_center_mode="random",
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    _, decision = strategy.propose_many(ctx, count=1)[0]
    restarts = decision["cma_es"]["restarts"]
    assert restarts["count"] == 1
    assert restarts["center_mode"] == "random"
    assert restarts["last_center_mode"] == "random"
    assert restarts["last_center_distance_norm"] > 0.0


def test_cmaes_strategy_can_alternate_restart_centers():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=59,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=2,
        restart_center_mode="alternate",
        restart_population_multiplier=2.0,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    _, first_decision = strategy.propose_many(ctx, count=1)[0]
    first_restarts = first_decision["cma_es"]["restarts"]
    assert first_restarts["count"] == 1
    assert first_restarts["center_mode"] == "alternate"
    assert first_restarts["last_center_mode"] == "best"
    assert first_restarts["last_center_distance_norm"] == pytest.approx(0.0)

    strategy.tell_many_scores([(0.50, 0.50)])
    strategy.propose_many(ctx, count=3)
    strategy.tell_many_scores(
        [
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    _, second_decision = strategy.propose_many(ctx, count=1)[0]
    second_restarts = second_decision["cma_es"]["restarts"]
    assert second_restarts["count"] == 2
    assert second_restarts["center_mode"] == "alternate"
    assert second_restarts["last_center_mode"] == "random"
    assert second_restarts["last_center_distance_norm"] > 0.0


def test_cmaes_strategy_bipop_restart_population_alternates_large_and_small():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=60,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=3,
        restart_population_multiplier=2.0,
        restart_population_schedule="bipop",
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    _, first_decision = strategy.propose_many(ctx, count=1)[0]
    first_restarts = first_decision["cma_es"]["restarts"]
    assert first_restarts["population_schedule"] == "bipop"
    assert first_restarts["population_size"] == 8

    strategy.tell_many_scores([(0.50, 0.50)])
    strategy.propose_many(ctx, count=3)
    strategy.tell_many_scores(
        [
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )
    _, second_decision = strategy.propose_many(ctx, count=1)[0]
    second_restarts = second_decision["cma_es"]["restarts"]
    assert second_restarts["population_size"] == 4

    strategy.tell_many_scores([(0.50, 0.50)])
    strategy.propose_many(ctx, count=3)
    strategy.tell_many_scores(
        [
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )
    _, third_decision = strategy.propose_many(ctx, count=1)[0]
    third_restarts = third_decision["cma_es"]["restarts"]
    assert third_restarts["population_size"] == 16


def test_cmaes_strategy_can_continue_after_restart_budget_is_exhausted():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=57,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=1,
        stagnation_stop_after_restarts=False,
        restart_population_multiplier=2.0,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )
    strategy.propose_many(ctx, count=1)
    strategy.tell_many_scores([(0.50, 0.50)])
    strategy.propose_many(ctx, count=3)
    strategy.tell_many_scores(
        [
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert strategy.stop_reason() is None
    _, decision = strategy.propose_many(ctx, count=1)[0]
    assert decision["cma_es"]["stagnation"]["plateau"] is True
    assert decision["cma_es"]["restarts"]["count"] == 1
    assert decision["cma_es"]["restarts"]["stop_after_max"] is False


def test_cmaes_strategy_checkpoint_restores_restart_budget(tmp_path):
    config = CmaesStrategyConfig(
        mode="cold",
        seed=56,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
        stagnation_max_restarts=1,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )
    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )
    assert strategy.stop_reason() is None
    checkpoint_path = tmp_path / "strategy.pkl"
    strategy.save_checkpoint(checkpoint_path)

    restored = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    restored.load_checkpoint(checkpoint_path)
    _, decision = restored.propose_many(ctx, count=4)[0]
    assert decision["cma_es"]["restarts"]["count"] == 1
    restored.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.509, 0.491),
        ]
    )

    assert restored.stop_reason() == "cmaes_stagnation"


def test_cmaes_strategy_stagnation_allows_significant_new_best():
    config = CmaesStrategyConfig(
        mode="cold",
        seed=53,
        population_size=4,
        stagnation_patience=3,
        stagnation_min_delta=0.02,
        stagnation_min_evaluations=4,
    )
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.50,
        fit_score=0.50,
        state=state,
    )

    strategy.propose_many(ctx, count=4)
    strategy.tell_many_scores(
        [
            (0.50, 0.50),
            (0.51, 0.49),
            (0.505, 0.495),
            (0.525, 0.475),
        ]
    )

    assert strategy.stop_reason() is None


def test_cmaes_strategy_fit_score_to_loss_is_monotone_decreasing():
    high = CmaesStrategy._fit_score_to_loss(0.95, 0.05)
    low = CmaesStrategy._fit_score_to_loss(0.10, 0.90)
    assert high < low
    assert 0.0 <= high <= 1.0
    assert 0.0 <= low <= 1.0


def test_cmaes_strategy_fit_score_handles_non_finite_inputs():
    # Both non-finite → neutral 0.5
    assert CmaesStrategy._fit_score_to_loss(float("-inf"), float("nan")) == pytest.approx(0.5)
    # Only fit_score non-finite → fall back to diff_score (RGB MAE)
    assert CmaesStrategy._fit_score_to_loss(float("-inf"), 0.20) == pytest.approx(0.20)


def test_cmaes_strategy_warm_start_with_real_history_marks_warm_started():
    history = [
        (_initial_params(), 0.40),
        ({**_initial_params(), "u_Gamma_Power": 2.0}, 0.45),
        ({**_initial_params(), "u_BaseColor": [0.4, 0.3, 0.1, 1.0]}, 0.55),
        ({**_initial_params(), "u_Gamma_Power": 1.9, "u_BaseColor": [0.35, 0.28, 0.08, 1.0]}, 0.60),
    ]
    config = CmaesStrategyConfig(mode="warm", seed=3, warm_start_iters=4)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
        warm_start_history=history,
    )
    assert strategy.warm_started is True

    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.20,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    cma_info = decision["cma_es"]
    assert cma_info["warm_started"] is True
    assert cma_info["warm_start_iters_used"] == 4


def test_cmaes_strategy_emits_changes_relative_to_current_params():
    config = CmaesStrategyConfig(mode="cold", seed=13)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=_channel_analysis(),
        diff_score=0.10,
        fit_score=0.20,
        state=state,
    )
    next_params, decision = strategy.propose(ctx)
    # CMA-ES sample is essentially never numerically equal to the initial
    # mean (default sigma=0.30), so we expect non-empty changes.
    assert isinstance(decision["changes"], list)
    assert len(decision["changes"]) > 0
    # And changes should only reference keys that actually exist in
    # next_params (no spurious keys, otherwise lmat_io would reject the
    # write).
    for change in decision["changes"]:
        assert change["param"] in next_params


# --------------------------------------------------------------------
# config helpers


def test_cmaes_strategy_config_dict_round_trip():
    raw = {
        "mode": "warm",
        "warm_start_iters": 8,
        "warm_start_source": "iteration_history",
        "population_size": 6,
        "sigma": 0.25,
        "seed": 42,
        "hint_bias_mix_ratio": 0.20,
        "stagnation_patience": 120,
        "stagnation_min_delta": 0.002,
        "stagnation_min_evaluations": 240,
        "stagnation_max_restarts": 2,
        "stagnation_stop_after_restarts": False,
        "restart_center_mode": "alternate",
        "restart_population_multiplier": 2.0,
        "restart_population_schedule": "bipop",
        "restart_max_population_size": 32,
        "initial_design_samples": 16,
        "initial_design_method": "local_coordinate_probe",
        "initial_design_include_current": False,
        "initial_design_local_step_ratio": 0.025,
        "allow_scene_lighting": False,
    }
    config = cmaes_strategy_config_from_dict(raw)
    assert config.mode == "warm"
    assert config.warm_start_iters == 8
    assert config.warm_start_source == "iteration_history"
    assert config.population_size == 6
    assert config.sigma == pytest.approx(0.25)
    assert config.seed == 42
    assert config.hint_bias_mix_ratio == pytest.approx(0.20)
    assert config.stagnation_patience == 120
    assert config.stagnation_min_delta == pytest.approx(0.002)
    assert config.stagnation_min_evaluations == 240
    assert config.stagnation_max_restarts == 2
    assert config.stagnation_stop_after_restarts is False
    assert config.restart_center_mode == "alternate"
    assert config.restart_population_multiplier == pytest.approx(2.0)
    assert config.restart_population_schedule == "bipop"
    assert config.restart_max_population_size == 32
    assert config.initial_design_samples == 16
    assert config.initial_design_method == "local_coordinate_probe"
    assert config.initial_design_include_current is False
    assert config.initial_design_local_step_ratio == pytest.approx(0.025)
    out = cmaes_strategy_config_to_dict(config)
    assert out == {
        "mode": "warm",
        "warm_start_iters": 8,
        "warm_start_source": "iteration_history",
        "population_size": 6,
        "sigma": 0.25,
        "seed": 42,
        "hint_bias_mix_ratio": 0.20,
        "stagnation_patience": 120,
        "stagnation_min_delta": 0.002,
        "stagnation_min_evaluations": 240,
        "stagnation_max_restarts": 2,
        "stagnation_stop_after_restarts": False,
        "restart_center_mode": "alternate",
        "restart_population_multiplier": 2.0,
        "restart_population_schedule": "bipop",
        "restart_max_population_size": 32,
        "initial_design_samples": 16,
        "initial_design_method": "local_coordinate_probe",
        "initial_design_include_current": False,
        "initial_design_local_step_ratio": 0.025,
        "allow_scene_lighting": False,
    }


def test_cmaes_strategy_config_dict_handles_empty_strings_as_none():
    """The UI sends ``""`` for "leave unset"; we must coerce to None."""
    raw = {
        "mode": "cold",
        "warm_start_iters": 0,
        "population_size": "",
        "sigma": "",
        "seed": "",
    }
    config = cmaes_strategy_config_from_dict(raw)
    assert config.mode == "cold"
    assert config.population_size is None
    assert config.sigma is None
    assert config.seed is None


def test_cmaes_strategy_config_dict_returns_default_on_none():
    config = cmaes_strategy_config_from_dict(None)
    assert config.mode == "warm"
    assert config.warm_start_iters == 12
    assert config.warm_start_source == "elite_archive_first"
    # E-010: 0.30 is the recommended starting point for the hint
    # blend when callers don't override it. Tests for legacy
    # "no bias" semantics should explicitly pass 0.0.
    assert config.hint_bias_mix_ratio == pytest.approx(0.30)


def test_cmaes_strategy_config_dict_clamps_hint_bias_to_unit_interval():
    """The UI slider lets the user type any number; we must clip
    out-of-range and non-finite values so the optimizer never sees
    a huge bias that swamps CMA-ES's own exploration."""
    too_high = cmaes_strategy_config_from_dict({"hint_bias_mix_ratio": 5.0})
    assert too_high.hint_bias_mix_ratio == pytest.approx(1.0)
    negative = cmaes_strategy_config_from_dict({"hint_bias_mix_ratio": -0.5})
    assert negative.hint_bias_mix_ratio == pytest.approx(0.0)
    junk = cmaes_strategy_config_from_dict({"hint_bias_mix_ratio": "abc"})
    assert junk.hint_bias_mix_ratio == pytest.approx(0.30)
    nan_in = cmaes_strategy_config_from_dict({"hint_bias_mix_ratio": float("nan")})
    assert nan_in.hint_bias_mix_ratio == pytest.approx(0.0)


def test_cmaes_strategy_config_dict_normalizes_warm_start_source():
    assert cmaes_strategy_config_from_dict({"warm_start_source": "archive_only"}).warm_start_source == "elite_archive_only"
    assert cmaes_strategy_config_from_dict({"warm_start_source": "history"}).warm_start_source == "iteration_history"
    assert cmaes_strategy_config_from_dict({"warm_start_source": "off"}).warm_start_source == "none"
    assert cmaes_strategy_config_from_dict({"warm_start_source": "bogus"}).warm_start_source == "elite_archive_first"


# --------------------------------------------------------------------
# E-010 hint-bias contract


def _adjustment_hints_emission_increase() -> list[dict[str, object]]:
    """Minimal but realistic hints payload mimicking ``vision.diff_analysis``.

    Two channels point in opposite directions on ``u_BaseColor`` so we
    can assert the cancellation rule, plus an emission/specular pair
    that should drive ``u_SpecularIntensity`` *up* with high severity.
    """

    return [
        {
            "channel": "base_color_main_texture",
            "direction": "decrease",
            "severity": "medium",
            "related_params": ["u_BaseColor"],
        },
        {
            "channel": "color_grading_hsv_contrast",
            "direction": "increase",
            "severity": "medium",
            "related_params": ["u_BaseColor"],
        },
        {
            "channel": "emission",
            "direction": "increase",
            "severity": "high",
            "related_params": ["u_SpecularIntensity", "u_FresnelIntensity"],
        },
    ]


def test_cmaes_strategy_does_not_opt_into_global_no_improve_check():
    """E-010: CMA-ES is stochastic; the heuristic-style 4-step
    no-improve abort would kill it after one population on a 49-dim
    space. ``HeuristicStrategy`` keeps the legacy True so old runs
    behave identically."""
    cma = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=CmaesStrategyConfig(mode="cold", seed=0),
    )
    assert cma.wants_global_no_improve_check() is False

    policies = build_adjustment_policies(_shader_params())
    heur = HeuristicStrategy(policies, _shader_params(), None)
    assert heur.wants_global_no_improve_check() is True


def test_cmaes_strategy_emits_hint_bias_diagnostics_when_disabled():
    """mix_ratio=0 → callback is None and decision records ``applied=False``.
    No hint vector ever reaches the CMA-ES sample. This is the
    "legacy" comparison line for paper experiments."""
    config = CmaesStrategyConfig(mode="cold", seed=17, hint_bias_mix_ratio=0.0)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    analysis = _channel_analysis()
    analysis["adjustment_hints"] = _adjustment_hints_emission_increase()
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=analysis,
        diff_score=0.40,
        fit_score=0.60,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    bias = decision["cma_es"]["hint_bias"]
    assert bias["applied"] is False
    assert bias["mix_ratio"] == pytest.approx(0.0)
    assert bias["n_axes_biased"] == 0
    assert bias["max_abs_delta"] == pytest.approx(0.0)
    assert bias["channels_used"] == []


def test_cmaes_strategy_emits_hint_bias_when_hints_present():
    """mix_ratio>0 + hints with usable severity/direction → at least
    one CMA-ES axis should receive a non-zero delta, and the
    decision dict should expose enough forensic detail to debug
    a runaway bias."""
    config = CmaesStrategyConfig(mode="cold", seed=21, hint_bias_mix_ratio=0.30)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    analysis = _channel_analysis()
    analysis["adjustment_hints"] = _adjustment_hints_emission_increase()
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=analysis,
        diff_score=0.40,
        fit_score=0.60,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    bias = decision["cma_es"]["hint_bias"]
    assert bias["applied"] is True
    assert bias["mix_ratio"] == pytest.approx(0.30)
    # u_SpecularIntensity (Float, no bound → name-fallback bounds)
    # and u_FresnelIntensity should both be biased upward; u_BaseColor
    # has cancelling +medium / -medium, so its 3 axes contribute 0.
    assert bias["n_axes_biased"] >= 2
    assert bias["max_abs_delta"] > 0.0
    assert "emission" in bias["channels_used"]


def test_cmaes_strategy_hint_bias_cancels_on_conflicting_directions():
    """Equal-severity hints in opposite directions on the same param
    must cancel — the algorithm must refuse to push a parameter when
    the channel-level evidence is contradictory. This protects us
    against e.g. base_color/contrast hint pairs that happen to flip
    sign between iterations."""
    only_conflict = [
        {
            "channel": "a",
            "direction": "increase",
            "severity": "high",
            "related_params": ["u_Gamma_Power"],
        },
        {
            "channel": "b",
            "direction": "decrease",
            "severity": "high",
            "related_params": ["u_Gamma_Power"],
        },
    ]
    config = CmaesStrategyConfig(mode="cold", seed=99, hint_bias_mix_ratio=0.30)
    strategy = CmaesStrategy(
        initial_params=_initial_params(),
        shader_params=_shader_params(),
        config=config,
    )
    analysis = _channel_analysis()
    analysis["adjustment_hints"] = only_conflict
    state = AdjustmentState(best_params=dict(_initial_params()))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=analysis,
        diff_score=0.40,
        fit_score=0.60,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    bias = decision["cma_es"]["hint_bias"]
    assert bias["applied"] is False  # zero net bias → no callback installed
    assert bias["n_axes_biased"] == 0


def test_cmaes_strategy_hint_bias_supports_wildcard_param_match():
    """The Unity→Laya material analysis often emits ``u_MetallicRemap*``
    style entries to mean 'every remap axis on this channel'. We must
    expand them prefix-style so a single hint can drive all related
    encoder axes."""
    extra_shader = [
        ShaderParam("u_MetallicRemapMin", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_MetallicRemapMax", "Range", default=1.0, range_min=0.0, range_max=1.0),
    ]
    initial = {
        **_initial_params(),
        "u_MetallicRemapMin": 0.10,
        "u_MetallicRemapMax": 0.90,
    }
    hints = [
        {
            "channel": "metallic_smoothness_specular",
            "direction": "increase",
            "severity": "high",
            "related_params": ["u_MetallicRemap*"],
        }
    ]
    config = CmaesStrategyConfig(mode="cold", seed=57, hint_bias_mix_ratio=0.30)
    strategy = CmaesStrategy(
        initial_params=initial,
        shader_params=_shader_params() + extra_shader,
        config=config,
    )
    analysis = _channel_analysis()
    analysis["adjustment_hints"] = hints
    state = AdjustmentState(best_params=dict(initial))
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(initial),
        analysis=analysis,
        diff_score=0.40,
        fit_score=0.60,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    bias = decision["cma_es"]["hint_bias"]
    # Both Min and Max axes should be in the biased set.
    assert bias["applied"] is True
    assert bias["n_axes_biased"] >= 2


# --------------------------------------------------------------------
# OptimizerUnavailableError contract


def test_cmaes_strategy_raises_clean_error_when_no_trainable_axes():
    """All-fixed param dict (textures only) → CMA-ES has nothing to do."""
    only_textures = {"u_BaseMap": "white", "u_BumpMap": "bump", "u_BaseMap_ST": [1, 1, 0, 0]}
    only_texture_shader_params = [
        ShaderParam("u_BaseMap", "Texture2D", default="white"),
        ShaderParam("u_BumpMap", "Texture2D", default="bump"),
        ShaderParam("u_BaseMap_ST", "Vector4", default=[1, 1, 0, 0]),
    ]
    with pytest.raises(OptimizerUnavailableError, match="no trainable axes"):
        CmaesStrategy(
            initial_params=only_textures,
            shader_params=only_texture_shader_params,
            config=CmaesStrategyConfig(mode="cold", seed=0),
        )


def test_heuristic_strategy_no_effective_change_raises_stuck_count():
    """When the heuristic returns ``stop_reason == "no_effective_change"``,
    ``ctx.state.stage_no_improve`` should be bumped to at least
    STUCK_NO_IMPROVE_LIMIT so choose_stage advances next iteration.

    This is the E-002 contract that used to live as an inline hack in
    fit_material.py and now lives inside HeuristicStrategy."""
    from tools.material_fit.optimizer.adjustment_algorithm import (
        STUCK_NO_IMPROVE_LIMIT,
    )

    policies = build_adjustment_policies(_shader_params())
    strategy = HeuristicStrategy(policies, _shader_params(), unity_material_params={})
    state = AdjustmentState(best_params=dict(_initial_params()))
    # Zero-bias analysis: no parameter should be moved → "no_effective_change".
    flat_analysis = {
        "score": 0.0,
        "material_channels": {
            name: {
                "rgb_bias_candidate_minus_reference": [0.0, 0.0, 0.0],
                "luma_bias_candidate_minus_reference": 0.0,
                "saturation_bias_candidate_minus_reference": 0.0,
                "contrast_bias_candidate_minus_reference": 0.0,
                "rgb_mae": 0.0,
                "edge_minus_center_luma_bias": 0.0,
            }
            for name in (
                "base_color_main_texture",
                "shadow_occlusion",
                "metallic_smoothness_specular",
                "environment_reflection_matcap",
                "fresnel_rim",
                "emission",
                "color_grading_hsv_contrast",
                "center_vs_edge_balance",
            )
        },
    }
    ctx = StrategyContext(
        iteration=0,
        current_params=dict(_initial_params()),
        analysis=flat_analysis,
        diff_score=0.0,
        fit_score=1.0,
        state=state,
    )
    _, decision = strategy.propose(ctx)
    if decision.get("stop_reason") == "no_effective_change":
        assert state.stage_no_improve >= STUCK_NO_IMPROVE_LIMIT
