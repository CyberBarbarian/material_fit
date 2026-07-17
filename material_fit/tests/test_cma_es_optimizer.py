"""Tests for :mod:`tools.material_fit.optimizer.cma_es_optimizer`.

These tests pin down the contract that the CMA-ES driver must satisfy
*before* it goes anywhere near a real Laya screenshot loop:

* ``ParameterEncoder`` only exposes numeric scalars / numeric vectors as
  trainable axes — no texture bindings, no ``*_ST`` tiling, no booleans.
* The encoder is bidirectional: ``decode(encode(x)) == x`` for every
  trainable param value (modulo bound clipping and alpha preservation).
* CMA-ES samples stay inside their bounds.
* ``ask()`` / ``tell()`` round-trips are stable for ``population_size``
  iterations and the optimizer makes progress on a convex test.
* Warm-starting from a fake heuristic trajectory consumes the prior and
  starts at a tighter mean than vanilla CMA-ES.

Run with::

    python -m pytest tools/material_fit/tests/test_cma_es_optimizer.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.optimizer.cma_es_optimizer import (
    CmaesConfig,
    CmaesOptimizer,
    ParameterEncoder,
    cmaes_from_heuristic_history,
)
from tools.material_fit.optimizer.semantic_graph import ParamSemantics
from tools.material_fit.shared.models import ShaderParam


# --------------------------------------------------------------------
# Fixtures


def _shader_params() -> list[ShaderParam]:
    """Mirror a slice of FishStandard's uniformMap that exercises every
    trainable / non-trainable case the encoder must handle."""

    return [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_BaseMap_ST", "Vector4", default=[1, 1, 0, 0]),
        ShaderParam("u_BaseMap", "Texture2D", default="white"),
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_OcclusionStrength", "Range", default=1.0, range_min=0.0, range_max=10.0),
        ShaderParam("u_SpecularColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_SpecularIntensity", "Float", default=1.0),
        ShaderParam("u_FresnelColor", "Color", default=[1, 0, 0, 0]),
        ShaderParam("u_FresnelIntensity", "Float", default=1.0),
        ShaderParam("u_FresnelUesF0", "Bool", default=True),
        ShaderParam("u_AdjustHue", "Float", default=0.0),
        ShaderParam("u_AdjustSaturation", "Float", default=0.0),
        ShaderParam("u_AdjustLightness", "Float", default=0.0),
        ShaderParam("u_ContrastScale", "Float", default=0.0),
        ShaderParam("u_EmissionColor", "Color", default=[0, 0, 0, 0]),
        ShaderParam("u_EmissionScale", "Float", default=1.0),
        ShaderParam("u_Alpha", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_SelfLightDir", "Vector4", default=[0, 0, 0, 0]),
    ]


def _initial_params() -> dict[str, object]:
    return {
        "u_BaseColor": [0.32, 0.27, 0.07, 1.0],
        "u_BaseMap_ST": [1, 1, 0, 0],
        "u_BaseMap": "white",
        "u_Gamma_Power": 2.2,
        "u_Metallic": 0.0,
        "u_Smoothness": 0.8,
        "u_OcclusionStrength": 1.0,
        "u_SpecularColor": [1.0, 1.0, 1.0, 1.0],
        "u_SpecularIntensity": 1.0,
        "u_FresnelColor": [1.0, 0.0, 0.0, 0.0],
        "u_FresnelIntensity": 1.0,
        "u_FresnelUesF0": True,
        "u_AdjustHue": 0.0,
        "u_AdjustSaturation": 0.0,
        "u_AdjustLightness": 0.0,
        "u_ContrastScale": 0.0,
        "u_EmissionColor": [0.0, 0.0, 0.0, 0.0],
        "u_EmissionScale": 1.0,
        "u_Alpha": 1.0,
        "u_SelfLightDir": [0.0, 0.0, 0.0, 0.0],
    }


# --------------------------------------------------------------------
# ParameterEncoder


def test_encoder_excludes_textures_and_st_and_bools():
    encoder = ParameterEncoder(_initial_params(), _shader_params())

    fixed = encoder.fixed_params
    # Textures must be fixed (not trainable)
    assert fixed["u_BaseMap"] == "white"
    # Tiling vectors must be fixed
    assert fixed["u_BaseMap_ST"] == [1, 1, 0, 0]
    # Booleans are fixed
    assert fixed["u_FresnelUesF0"] is True
    # Alpha-only knob (u_Alpha) is blacklisted by name
    assert fixed["u_Alpha"] == 1.0
    # Scene lighting direction belongs to the render setup, not material fit.
    assert fixed["u_SelfLightDir"] == [0.0, 0.0, 0.0, 0.0]

    axis_names = {axis.param_name for axis in encoder.axes}
    assert "u_BaseMap" not in axis_names
    assert "u_BaseMap_ST" not in axis_names
    assert "u_FresnelUesF0" not in axis_names
    assert "u_Alpha" not in axis_names
    assert "u_SelfLightDir" not in axis_names

    # Color params expose 3 axes (RGB) not 4 (RGBA)
    base_color_axes = [a for a in encoder.axes if a.param_name == "u_BaseColor"]
    assert len(base_color_axes) == 3
    # Each axis is bounded to [0, 1]
    for axis in base_color_axes:
        assert axis.low == 0.0
        assert axis.high == 1.0


def test_encoder_allows_explicit_scene_rotation_search_only_when_enabled():
    params = {"u_SkyRotateX": 0.0, "u_GammaPower": 1.0}
    shader = [
        ShaderParam("u_SkyRotateX", "Float", default=0.0),
        ShaderParam("u_GammaPower", "Float", default=1.0),
    ]

    locked = ParameterEncoder(
        params,
        shader,
        param_whitelist=["u_SkyRotateX"],
    )
    enabled = ParameterEncoder(
        params,
        shader,
        param_whitelist=["u_SkyRotateX"],
        semantics={
            "u_SkyRotateX": ParamSemantics(
                name="u_SkyRotateX",
                param_type="Float",
                group="scene",
                role="orientation",
                transform="linear",
                searchable=False,
                reason="scene lighting/environment orientation parameter",
            )
        },
        allow_scene_lighting=True,
    )

    assert locked.dim == 0
    assert [(axis.param_name, axis.low, axis.high) for axis in enabled.axes] == [
        ("u_SkyRotateX", -180.0, 180.0)
    ]

def test_encoder_round_trip_preserves_values():
    initial = _initial_params()
    encoder = ParameterEncoder(initial, _shader_params())

    encoded = encoder.encode(initial)
    decoded = encoder.decode(encoded)

    # Trainable keys round-trip within bound clipping (no clipping should
    # happen for default values that are inside their bounds).
    for name, original in initial.items():
        assert name in decoded, f"{name} disappeared from decode()"
        round_tripped = decoded[name]
        if isinstance(original, list):
            assert isinstance(round_tripped, list)
            assert len(round_tripped) == len(original)
            for o, r in zip(original, round_tripped):
                assert math.isclose(float(o), float(r), abs_tol=1e-9)
        elif isinstance(original, bool):
            assert round_tripped is original
        elif isinstance(original, (int, float)):
            assert math.isclose(float(original), float(round_tripped), abs_tol=1e-9)
        else:
            assert original == round_tripped


def test_encoder_clamps_to_bounds_on_decode():
    encoder = ParameterEncoder(_initial_params(), _shader_params())
    # Make a vector that exceeds every axis's bounds
    extreme = encoder.upper_bounds * 100.0
    decoded = encoder.decode(extreme)
    for name, value in decoded.items():
        if name == "u_BaseColor":
            for component in value[:3]:
                assert 0.0 <= float(component) <= 1.0
        if name == "u_Gamma_Power":
            assert 0.05 <= float(value) <= 10.0
        if name == "u_Metallic":
            assert 0.0 <= float(value) <= 1.0


def test_encoder_preserves_alpha_of_color():
    initial = _initial_params()
    initial["u_BaseColor"] = [0.5, 0.5, 0.5, 0.42]  # custom alpha
    encoder = ParameterEncoder(initial, _shader_params())
    decoded = encoder.decode(encoder.encode(initial))
    assert decoded["u_BaseColor"][3] == pytest.approx(0.42)


def test_encoder_dim_and_bounds_are_consistent():
    encoder = ParameterEncoder(_initial_params(), _shader_params())
    assert encoder.dim == len(encoder.axes)
    assert encoder.lower_bounds.shape == (encoder.dim,)
    assert encoder.upper_bounds.shape == (encoder.dim,)
    assert (encoder.lower_bounds < encoder.upper_bounds).all()


def test_encoder_axis_order_uses_shader_order_not_initial_dict_order():
    initial = _initial_params()
    reordered_initial = dict(reversed(list(initial.items())))

    encoder = ParameterEncoder(initial, _shader_params())
    reordered_encoder = ParameterEncoder(reordered_initial, _shader_params())

    assert reordered_encoder.axis_fingerprint() == encoder.axis_fingerprint()
    assert np.array_equal(reordered_encoder.lower_bounds, encoder.lower_bounds)
    assert np.array_equal(reordered_encoder.upper_bounds, encoder.upper_bounds)


# --------------------------------------------------------------------
# CmaesOptimizer


def test_cmaes_optimizer_ask_tell_minimization_progresses():
    """End-to-end ask/tell on a small convex problem.

    Uses a 3-axis shader subset and the default population size (which
    for ``n=3`` is the recommended 6) so the test exercises the full
    machinery without paying the "high-dim CMA-ES wants 50+
    generations" cost we'd hit if we used the full 25-axis space here.
    """
    shader_params = [
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
    ]
    initial = {"u_Gamma_Power": 2.2, "u_Metallic": 0.0, "u_Smoothness": 0.8}
    encoder = ParameterEncoder(initial, shader_params)
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=42, population_size=8))

    target = np.array([2.5, 0.3, 0.6])
    initial_loss = float(np.sum((encoder.initial_vector - target) ** 2))

    for _ in range(30 * opt.population_size):  # ~30 generations
        params = opt.ask()
        x = encoder.encode(params)
        loss = float(np.sum((x - target) ** 2))
        opt.tell(loss)

    best_params, best_fit = opt.best
    assert best_params is not None
    assert best_fit < initial_loss * 0.01, (
        f"CMA-ES failed to reduce the loss. initial={initial_loss:.4g}, "
        f"best={best_fit:.4g}"
    )


def test_cmaes_optimizer_respects_bounds_for_every_ask():
    encoder = ParameterEncoder(_initial_params(), _shader_params())
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=0, population_size=8))

    for _ in range(2 * opt.population_size):
        params = opt.ask()
        vec = encoder.encode(params)
        assert (vec >= encoder.lower_bounds - 1e-9).all()
        assert (vec <= encoder.upper_bounds + 1e-9).all()
        # Tell a constant fitness so the optimizer keeps progressing
        opt.tell(1.0)


def test_cmaes_optimizer_ask_many_tell_many_updates_one_population():
    shader_params = [
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
    ]
    initial = {"u_Gamma_Power": 2.2, "u_Metallic": 0.0, "u_Smoothness": 0.8}
    encoder = ParameterEncoder(initial, shader_params)
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=123, population_size=4))

    batch = opt.ask_many(opt.population_size)

    assert len(batch) == 4
    assert opt.pending_count == 4
    assert opt.evaluations == 0
    losses = [float(np.sum(encoder.encode(params) ** 2)) for params in batch]

    opt.tell_many(losses)

    assert opt.pending_count == 0
    assert opt.evaluations == 4
    assert len(opt.history()) == 4
    best_params, best_fitness = opt.best
    assert best_params is not None
    assert best_fitness == pytest.approx(min(losses))


def test_cmaes_optimizer_tell_many_rejects_count_above_pending_without_partial_update():
    encoder = ParameterEncoder(_initial_params(), _shader_params())
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=5, population_size=4))
    opt.ask_many(2)

    with pytest.raises(RuntimeError, match="more fitness values than pending"):
        opt.tell_many([0.3, 0.2, 0.1])

    assert opt.pending_count == 2
    assert opt.evaluations == 0
    assert opt.history() == []


def test_cmaes_optimizer_checkpoint_round_trip_continues_search(tmp_path):
    shader_params = [
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
    ]
    initial = {"u_Gamma_Power": 2.2, "u_Metallic": 0.0, "u_Smoothness": 0.8}
    encoder = ParameterEncoder(initial, shader_params)
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=123, population_size=4))

    first_batch = opt.ask_many(opt.population_size)
    first_losses = [float(np.sum(encoder.encode(params) ** 2)) for params in first_batch]
    opt.tell_many(first_losses)
    checkpoint_path = tmp_path / "cma_optimizer.pkl"

    opt.save_checkpoint(checkpoint_path)
    metadata = CmaesOptimizer.checkpoint_metadata(checkpoint_path)
    assert metadata["schema_version"] == 1
    assert metadata["optimizer"] == "cma_es"
    assert metadata["encoder_dim"] == encoder.dim
    restored = CmaesOptimizer.load_checkpoint(checkpoint_path)

    assert restored.evaluations == opt.evaluations
    assert restored.pending_count == 0
    assert len(restored.history()) == len(opt.history())
    assert restored.best[1] == pytest.approx(opt.best[1])

    second_batch = restored.ask_many(restored.population_size)
    assert len(second_batch) == restored.population_size
    second_losses = [float(np.sum(encoder.encode(params) ** 2)) for params in second_batch]
    restored.tell_many(second_losses)

    assert restored.evaluations == opt.evaluations + restored.population_size
    assert restored.pending_count == 0


def test_cmaes_optimizer_checkpoint_rejects_incompatible_encoder(tmp_path):
    shader_params = [
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
    ]
    initial = {"u_Gamma_Power": 2.2, "u_Metallic": 0.0}
    encoder = ParameterEncoder(initial, shader_params)
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=123, population_size=4))
    batch = opt.ask_many(opt.population_size)
    opt.tell_many([float(np.sum(encoder.encode(params) ** 2)) for params in batch])
    checkpoint_path = tmp_path / "cma_optimizer.pkl"
    opt.save_checkpoint(checkpoint_path)

    incompatible_encoder = ParameterEncoder(
        {**initial, "u_Smoothness": 0.8},
        [
            *shader_params,
            ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ],
    )

    with pytest.raises(ValueError, match="incompatible CMA-ES checkpoint"):
        CmaesOptimizer.load_checkpoint(checkpoint_path, expected_encoder=incompatible_encoder)


def test_cmaes_optimizer_restart_preserves_history_and_global_best():
    shader_params = [
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
    ]
    initial = {"u_Gamma_Power": 2.2, "u_Metallic": 0.0}
    encoder = ParameterEncoder(initial, shader_params)
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=123, population_size=4))
    batch = opt.ask_many(opt.population_size)
    losses = [0.30, 0.20, 0.40, 0.50]
    opt.tell_many(losses)
    best_params, best_loss = opt.best

    opt.restart(initial_mean=best_params, population_size=6)

    assert opt.evaluations == 4
    assert opt.population_size == 6
    assert opt.loss_history() == losses
    assert opt.best[1] == pytest.approx(best_loss)
    assert opt.best[0] == best_params
    assert opt.pending_count == 0
    next_batch = opt.ask_many(2)
    assert len(next_batch) == 2
    assert opt.pending_count == 2


# --------------------------------------------------------------------
# Warm-start


def _fake_history(encoder: ParameterEncoder, n: int, *, seed: int) -> list[tuple[dict, float]]:
    """Produce ``n`` (params, fitness) pairs concentrated near a target.

    This mimics what a heuristic warm-start would deliver: solutions
    that are *biased* toward a useful region but with non-trivial
    spread so the warm-start MGD has a meaningful covariance.
    """
    rng = np.random.default_rng(seed)
    target = (encoder.lower_bounds + encoder.upper_bounds) / 2.0
    width = (encoder.upper_bounds - encoder.lower_bounds) / 6.0
    history: list[tuple[dict, float]] = []
    for _ in range(n):
        x = target + rng.normal(0.0, width)
        x = np.clip(x, encoder.lower_bounds, encoder.upper_bounds)
        params = encoder.decode(x)
        loss = float(np.sum((x - target) ** 2))
        history.append((params, loss))
    return history


def test_warm_start_prefers_prior_region():
    encoder = ParameterEncoder(_initial_params(), _shader_params())

    history = _fake_history(encoder, n=12, seed=1)
    target = (encoder.lower_bounds + encoder.upper_bounds) / 2.0

    opt = cmaes_from_heuristic_history(
        _initial_params(),
        _shader_params(),
        history,
        config=CmaesConfig(seed=7, population_size=8),
    )
    assert opt.warm_started is True

    # Sample one population without telling and verify the *mean* of the
    # samples is closer to the heuristic's target than to the encoder's
    # naive initial vector.
    asks = []
    for _ in range(opt.population_size):
        params = opt.ask()
        asks.append(encoder.encode(params))

    # Don't update the optimizer with garbage; tell back the same fitness
    # so the run is well-formed for cleanup.
    for _ in asks:
        opt.tell(1.0)

    asks_arr = np.stack(asks)
    sample_mean = asks_arr.mean(axis=0)

    dist_to_target = float(np.linalg.norm(sample_mean - target))
    dist_to_initial = float(np.linalg.norm(sample_mean - encoder.initial_vector))

    assert dist_to_target < dist_to_initial, (
        f"warm-started CMA-ES did not move toward the prior. "
        f"dist_to_target={dist_to_target:.4g}, dist_to_initial={dist_to_initial:.4g}"
    )


def test_cmaes_from_heuristic_history_with_no_history_falls_back_to_cold():
    opt = cmaes_from_heuristic_history(
        _initial_params(),
        _shader_params(),
        history=[],
        config=CmaesConfig(seed=0),
    )
    assert opt.warm_started is False


def test_warm_start_requires_two_samples():
    encoder = ParameterEncoder(_initial_params(), _shader_params())
    history = _fake_history(encoder, n=1, seed=2)
    with pytest.raises(ValueError):
        cmaes_from_heuristic_history(
            _initial_params(),
            _shader_params(),
            history,
            config=CmaesConfig(seed=0),
        )


# --------------------------------------------------------------------
# Smoke tests on a "real" param dict (the one we shipped with iter_0000)


def test_real_params_json_produces_reasonable_search_space():
    real_params = {
        "u_BaseColor": [0.3292, 0.2656, 0.0675, 1.0],
        "u_BaseMap_ST": [1, 1, 0, 0],
        "u_Gamma_Power": 2.198,
        "u_Metallic": 0,
        "u_Smoothness": 1,
        "u_OcclusionStrength": 1,
        "u_GIIntensity": 1,
        "u_BumpScale": 1,
        "u_DiffuseThreshold": 0.5,
        "u_DiffuseSmoothness": 0.1,
        "u_ShadowColor": [0, 0, 0, 1],
        "u_IBLMapColor": [1, 1, 1, 1],
        "u_IBLMapIntensity": 0.3,
        "u_SpecularColor": [1, 1, 1, 1],
        "u_SpecularIntensity": 1,
        "u_FresnelColor": [1, 0, 0, 0],
        "u_FresnelIntensity": 1,
        "u_AdjustHue": 0.0,
        "u_AdjustSaturation": 0.0,
        "u_AdjustLightness": 0.0,
        "u_ContrastScale": 0.0,
        "u_EmissionColor": [0, 0, 0, 0],
        "u_EmissionScale": 1,
        "u_Alpha": 1,
        "u_Cutoff": 0.5,
    }
    encoder = ParameterEncoder(real_params, _shader_params())
    # We expect at least the colors + scalars to be in the search space.
    # 5 colors × 3 channels = 15, plus ~14 scalars (excluding STs/alpha/etc.)
    # ≈ 25-30 axes. This is the dimensionality our paper draft cites.
    assert 15 <= encoder.dim <= 60, f"dim={encoder.dim} is suspicious"

    # Smoke run: sample one population
    opt = CmaesOptimizer(encoder, config=CmaesConfig(seed=11, population_size=6))
    for _ in range(opt.population_size):
        opt.ask()
        opt.tell(1.0)
