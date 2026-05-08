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
from tools.material_fit.optimizer.strategy import (  # noqa: E402
    CmaesStrategy,
    CmaesStrategyConfig,
    HeuristicStrategy,
    OptimizerUnavailableError,
    StrategyContext,
    build_strategy,
    cmaes_strategy_config_from_dict,
    cmaes_strategy_config_to_dict,
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
        "population_size": 6,
        "sigma": 0.25,
        "seed": 42,
        "hint_bias_mix_ratio": 0.20,
    }
    config = cmaes_strategy_config_from_dict(raw)
    assert config.mode == "warm"
    assert config.warm_start_iters == 8
    assert config.population_size == 6
    assert config.sigma == pytest.approx(0.25)
    assert config.seed == 42
    assert config.hint_bias_mix_ratio == pytest.approx(0.20)
    out = cmaes_strategy_config_to_dict(config)
    assert out == {
        "mode": "warm",
        "warm_start_iters": 8,
        "population_size": 6,
        "sigma": 0.25,
        "seed": 42,
        "hint_bias_mix_ratio": 0.20,
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
