from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from material_fit.fit_cli import parse_fit_args
from material_fit.fit_material import (
    _browser_score_analysis_payload,
    _structured_residual_feature_payload,
)
from material_fit.optimizer.adjustment_algorithm import AdjustmentState, build_adjustment_policies
from material_fit.optimizer.cma_es_optimizer import ParameterEncoder
from material_fit.optimizer.parameter_search import build_param_policy_audit
from material_fit.optimizer.strategy import StrategyContext, build_strategy
from material_fit.optimizer.structured_fish_escape import (
    BlockEscapeObservation,
    apply_block_escape_probe,
    build_block_escape_directions,
    build_block_escape_response_moves,
    build_coordinate_escape_directions,
)
from material_fit.optimizer.structured_fish_strategy import StructuredFishStrategy
from material_fit.optimizer.structured_fish_space import (
    FishSearchCoordinate,
    MATERIAL_GROUPS,
    MATERIAL_SCALAR_GROUP,
    STRUCTURED_FISH_MATERIAL_COORDINATES,
    structured_fish_coordinates,
    structured_fish_search_param_names,
    structured_fish_space_manifest,
)
from material_fit.shared.models import ShaderParam


def _params() -> dict[str, object]:
    return {
        "u_SkyRotateX": 0.0,
        "u_SkyRotateY": 0.0,
        "u_SkyRotateZ": 0.0,
        "u_LightRotateX": 0.0,
        "u_LightRotateY": 0.0,
        "u_LightRotateZ": 0.0,
        "u_GammaPower": 1.0,
        "u_Saturation": 1.0,
        "u_Contrast": 1.0,
        "u_HueShift": 0.0,
        "u_TexPower": 1.0,
        "u_AoPower": 0.1,
        "u_EmissionPow": 0.0,
        "u_IndirectStrength": 1.0,
        "u_NormalScale": 1.0,
        "u_ShadowSmoothness": 0.1,
        "u_ShadowThreshold1": 0.3,
        "u_SpecularIntensity": 1.0,
        "u_SpecularPower": 8.0,
        "u_SpecularThreshold": 0.7,
        "u_SpecularSmoothness": 0.4,
        "u_RimIntensity": 0.0,
        "u_RimWidth": 0.0,
        "u_Color": [1.0, 1.0, 1.0, 1.0],
        "u_ReflectColor": [0.0, 0.0, 0.0, 1.0],
        "u_ShadowColor1": [0.7, 0.7, 0.7, 1.0],
        "u_SpecularColor": [0.9, 0.9, 0.9, 1.0],
        "u_RimColor": [1.0, 0.9, 0.8, 1.0],
        "u_SpeOffet": [0.0, 0.0, 0.0, 0.0],
        "u_RimOffet": [0.0, 0.0, 0.0, 0.0],
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_AlphaTestValue": 0.5,
    }


def _shader_params() -> list[ShaderParam]:
    params = _params()
    result: list[ShaderParam] = []
    for name, value in params.items():
        if name.endswith("Color") or name == "u_Color":
            param_type = "Color"
        elif isinstance(value, list):
            param_type = "Vector4"
        else:
            param_type = "Float"
        result.append(ShaderParam(name, param_type, default=value))
    return result


def _context(
    iteration: int,
    params: dict[str, object],
    score: float,
    analysis: dict[str, object] | None = None,
) -> StrategyContext:
    return StrategyContext(
        iteration=iteration,
        current_params=params,
        analysis=analysis or {},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=params),
    )


def _write_lmat(path: Path, *, blend_src: int) -> None:
    path.write_text(
        """{
  "version": "LAYAMATERIAL:04",
  "props": {
    "type": "Custom/FishStandar_Low",
    "renderQueue": 2000,
    "materialRenderMode": 0,
    "s_Blend": 0,
    "s_BlendSrc": %d,
    "s_BlendDst": 0,
    "defines": ["NORMALMAP_Y_INVERT"],
    "textures": [{"name": "u_MainTex", "path": "fish.png"}],
    "u_Color": [1, 1, 1, 1]
  }
}
""" % blend_src,
        encoding="utf-8",
    )


def test_structured_space_has_separate_scene_and_material_groups() -> None:
    params = _params()
    coordinates = structured_fish_coordinates(params, shader_params=_shader_params())
    manifest = structured_fish_space_manifest(params, shader_params=_shader_params())

    assert len(coordinates) == 46
    assert len(STRUCTURED_FISH_MATERIAL_COORDINATES) == 40
    assert manifest["groups"]["scene_alignment"] == [
        "u_SkyRotateX",
        "u_SkyRotateY",
        "u_SkyRotateZ",
        "u_LightRotateX",
        "u_LightRotateY",
        "u_LightRotateZ",
    ]
    assert set(MATERIAL_GROUPS).issubset(manifest["groups"])
    assert "u_Color[3]" not in {coordinate.coordinate_id for coordinate in coordinates}
    assert "u_MainTex_ST" not in structured_fish_search_param_names(params, _shader_params())
    assert "u_AlphaTestValue" not in structured_fish_search_param_names(params, _shader_params())


def test_block_basin_escape_is_deterministic_and_preserves_locked_state() -> None:
    shader_params = _shader_params()
    initial = _params()
    initial.update(
        {
            "u_GammaPower": 1.75,
            "u_Saturation": 1.4,
            "u_Contrast": 0.6,
            "u_HueShift": 0.4,
            "u_TexPower": 0.25,
            "u_IndirectStrength": 0.5,
            "u_NormalScale": 0.25,
        }
    )
    coordinates = structured_fish_coordinates(
        initial,
        shader_params=shader_params,
        material_only=True,
    )

    directions = build_block_escape_directions(
        coordinates=coordinates,
        pair_count=4,
        round_index=0,
        seed=1701,
    )
    repeated = build_block_escape_directions(
        coordinates=coordinates,
        pair_count=4,
        round_index=0,
        seed=1701,
    )
    assert directions == repeated
    assert len(directions) == 4
    assert len({direction.signs for direction in directions}) == 4
    assert all(set(direction.signs) <= {-1.0, 1.0} for direction in directions)
    full_directions = build_block_escape_directions(
        coordinates=coordinates,
        pair_count=len(coordinates),
        round_index=0,
        seed=1701,
    )
    direction_matrix = np.asarray([direction.signs for direction in full_directions])
    assert direction_matrix.shape == (len(coordinates), len(coordinates))
    assert np.linalg.matrix_rank(direction_matrix) == len(coordinates)

    steps = {coordinate.coordinate_id: coordinate.initial_step for coordinate in coordinates}
    probe = apply_block_escape_probe(
        initial,
        coordinates=coordinates,
        steps=steps,
        direction=directions[0],
        radius=2.5,
        polarity=1.0,
    )
    assert probe is not None
    assert len(probe.normalized_updates) >= 30
    assert probe.candidate["u_SkyRotateX"] == initial["u_SkyRotateX"]
    assert probe.candidate["u_MainTex_ST"] == initial["u_MainTex_ST"]
    assert probe.candidate["u_AlphaTestValue"] == initial["u_AlphaTestValue"]
    assert probe.candidate["u_Color"][3] == initial["u_Color"][3]


def test_block_secant_residual_move_reduces_a_linear_residual() -> None:
    coordinates = [
        FishSearchCoordinate(name, None, MATERIAL_SCALAR_GROUP, -10.0, 10.0, 1.0)
        for name in ("a", "b", "c")
    ]
    center = {"a": 2.0, "b": -1.0, "c": 1.0, "locked": [1.0, 2.0]}
    steps = {coordinate.coordinate_id: 1.0 for coordinate in coordinates}
    directions = build_block_escape_directions(
        coordinates=coordinates,
        pair_count=4,
        round_index=0,
        seed=1701,
    )
    observations: list[BlockEscapeObservation] = []
    for direction in directions:
        minus = apply_block_escape_probe(
            center,
            coordinates=coordinates,
            steps=steps,
            direction=direction,
            radius=1.0,
            polarity=-1.0,
        )
        plus = apply_block_escape_probe(
            center,
            coordinates=coordinates,
            steps=steps,
            direction=direction,
            radius=1.0,
            polarity=1.0,
        )
        assert minus is not None and plus is not None
        minus_features = [minus.candidate[name] for name in ("a", "b", "c")]
        plus_features = [plus.candidate[name] for name in ("a", "b", "c")]
        observations.append(
            BlockEscapeObservation(
                direction=direction,
                minus_params=minus.candidate,
                plus_params=plus.candidate,
                minus_fit_score=-sum(value * value for value in minus_features),
                plus_fit_score=-sum(value * value for value in plus_features),
                minus_objective_score=-sum(value * value for value in minus_features),
                plus_objective_score=-sum(value * value for value in plus_features),
                minus_features=minus_features,
                plus_features=plus_features,
            )
        )

    moves = build_block_escape_response_moves(
        center,
        center_features=[2.0, -1.0, 1.0],
        coordinates=coordinates,
        steps=steps,
        radius=1.0,
        observations=observations,
        damping=0.8,
        ridge=0.001,
    )
    residual_move = next(move for move in moves if move.method == "residual_block_secant")
    before_norm = sum(center[name] ** 2 for name in ("a", "b", "c"))
    after_norm = sum(residual_move.candidate[name] ** 2 for name in ("a", "b", "c"))
    assert after_norm < before_norm
    assert residual_move.candidate["locked"] == center["locked"]


def test_coordinate_basis_secants_recover_a_large_linear_residual() -> None:
    coordinates = [
        FishSearchCoordinate(name, None, MATERIAL_SCALAR_GROUP, -10.0, 10.0, 1.0)
        for name in ("a", "b", "c")
    ]
    center = {"a": 3.0, "b": -2.0, "c": 1.5}
    steps = {coordinate.coordinate_id: 1.0 for coordinate in coordinates}
    directions = build_coordinate_escape_directions(
        coordinates=coordinates,
        pair_count=3,
        round_index=0,
        seed=1701,
    )
    assert {direction.coordinate_ids for direction in directions} == {("a",), ("b",), ("c",)}

    observations = []
    for direction in directions:
        minus = apply_block_escape_probe(
            center,
            coordinates=coordinates,
            steps=steps,
            direction=direction,
            radius=0.5,
            polarity=-1.0,
        )
        plus = apply_block_escape_probe(
            center,
            coordinates=coordinates,
            steps=steps,
            direction=direction,
            radius=0.5,
            polarity=1.0,
        )
        assert minus is not None and plus is not None
        observations.append(
            BlockEscapeObservation(
                direction=direction,
                minus_params=minus.candidate,
                plus_params=plus.candidate,
                minus_fit_score=0.0,
                plus_fit_score=0.0,
                minus_objective_score=0.0,
                plus_objective_score=0.0,
                minus_features=[minus.candidate[name] for name in ("a", "b", "c")],
                plus_features=[plus.candidate[name] for name in ("a", "b", "c")],
            )
        )

    moves = build_block_escape_response_moves(
        center,
        center_features=[3.0, -2.0, 1.5],
        coordinates=coordinates,
        steps=steps,
        radius=0.5,
        observations=observations,
        damping=1.0,
        ridge=0.0,
        response_trust_radius=4.0,
    )
    residual_move = next(move for move in moves if move.method == "residual_block_secant")
    assert sum(residual_move.candidate[name] ** 2 for name in center) < 1.0e-8

    line_search_moves = build_block_escape_response_moves(
        center,
        center_features=[3.0, -2.0, 1.5],
        coordinates=coordinates,
        steps=steps,
        radius=0.5,
        observations=observations,
        damping=1.0,
        ridge=0.0,
        response_trust_radius=4.0,
        response_line_search_scales=(1.0, 0.5, -0.5),
    )
    residual_candidates = [
        move.candidate for move in line_search_moves if move.method == "residual_block_secant"
    ]
    assert len(residual_candidates) == 3


def test_structured_strategy_audits_and_accepts_block_basin_escape() -> None:
    shader_params = _shader_params()
    initial = _params()
    initial.update(
        {
            "u_GammaPower": 1.75,
            "u_Saturation": 1.4,
            "u_Contrast": 0.6,
            "u_HueShift": 0.4,
            "u_TexPower": 0.25,
            "u_IndirectStrength": 0.5,
            "u_NormalScale": 0.25,
        }
    )
    material_names = list(
        dict.fromkeys(
            coordinate.param_name for coordinate in STRUCTURED_FISH_MATERIAL_COORDINATES
        )
    )
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=material_names,
        structured_fish_config={
            "basin_escape": {
                "enabled": True,
                "pair_count": 2,
                "radii": [1.0],
                "damping": 0.8,
                "ridge": 0.01,
                "seed": 1701,
            }
        },
    )

    candidate, decision = strategy.propose(_context(0, initial, 0.75))
    assert decision["structured_fish"]["group"] == "basin_escape"
    assert decision["structured_fish"]["escape_profile"] == "antithetic_block_secant_v1"
    assert decision["structured_fish"]["feedback_source"] == (
        "online_target_png_score_and_residuals"
    )
    assert decision["structured_fish"]["target_params_visible"] is False
    assert candidate["u_MainTex_ST"] == initial["u_MainTex_ST"]
    assert candidate["u_SkyRotateX"] == initial["u_SkyRotateX"]

    strategy.propose(_context(1, candidate, 0.90))
    summary = strategy.research_summary()
    assert summary["basin_escape"]["probe_count"] == 2
    assert summary["basin_escape"]["accept_count"] == 1
    assert summary["basin_escape"]["results"][0]["improved"] is True
    assert summary["basin_escape"]["target_params_visible"] is False


def test_block_basin_escape_completes_response_stage_before_coordinate_search() -> None:
    target = _params()
    shader_params = _shader_params()
    material_coordinates = structured_fish_coordinates(
        target,
        shader_params=shader_params,
        material_only=True,
    )
    initial = target.copy()
    initial = {
        name: list(value) if isinstance(value, list) else value
        for name, value in initial.items()
    }
    for index, coordinate in enumerate(material_coordinates):
        direction = -1.0 if index % 2 else 1.0
        initial = coordinate.write(
            initial,
            coordinate.read(initial) + direction * coordinate.initial_step,
        )
    material_names = list(dict.fromkeys(coordinate.param_name for coordinate in material_coordinates))
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=material_names,
        structured_fish_config={
            "basin_escape": {
                "enabled": True,
                "pair_count": 2,
                "radii": [1.0],
                "damping": 0.8,
                "ridge": 0.001,
                "seed": 1701,
            }
        },
    )

    current = initial
    groups: list[str] = []
    probe_kinds: list[str] = []
    for iteration in range(12):
        residual = [
            coordinate.read(current) - coordinate.read(target)
            for coordinate in material_coordinates
        ]
        score = 1.0 - min(sum(value * value for value in residual) / 100.0, 0.9)
        current, decision = strategy.propose(
            _context(
                iteration,
                current,
                score,
                {
                    "structured_residual_features": {
                        "profile": "synthetic",
                        "features": residual,
                    }
                },
            )
        )
        structured = decision["structured_fish"]
        groups.append(str(structured["group"]))
        probe_kinds.append(str(structured.get("probe_kind")))
        if structured["group"] != "basin_escape":
            break

    assert "basin_escape_block_probe" in probe_kinds
    assert "basin_escape_response" in probe_kinds
    assert groups[-1] == "material_scalar"
    summary = strategy.research_summary()
    assert summary["basin_escape"]["round_index"] == 1
    assert summary["basin_escape"]["response_probe_count"] >= 1


def test_basin_escape_activation_preserves_legacy_route_for_large_residuals() -> None:
    initial = _params()
    shader_params = _shader_params()
    material_names = [
        param.name
        for param in shader_params
        if param.name not in {"u_SkyRotateX", "u_SkyRotateY", "u_SkyRotateZ"}
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=material_names,
        structured_fish_config={
            "opportunistic_ranked_accept": True,
            "basin_escape": {
                "enabled": True,
                "pair_count": 2,
                "radii": [1.0],
                "activation_min_fit_score": 0.80,
                "disable_opportunistic_when_skipped": True,
            },
        },
    )

    _candidate, decision = strategy.propose(_context(0, initial, 0.60))

    assert decision["structured_fish"]["group"] != "basin_escape"
    summary = strategy.research_summary()
    assert summary["basin_escape"]["activation_status"] == (
        "skipped_initial_fit_below_threshold"
    )
    assert summary["basin_escape"]["initial_fit_score"] == pytest.approx(0.60)
    assert summary["opportunistic_ranked_accept_configured"] is True
    assert summary["opportunistic_ranked_accept"] is False


def test_basin_escape_activation_keeps_escape_for_deceptive_high_score() -> None:
    initial = _params()
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=[param.name for param in shader_params],
        structured_fish_config={
            "basin_escape": {
                "enabled": True,
                "pair_count": 2,
                "radii": [1.0],
                "activation_min_fit_score": 0.80,
            },
        },
    )

    _candidate, decision = strategy.propose(_context(0, initial, 0.85))

    assert decision["structured_fish"]["group"] == "basin_escape"
    summary = strategy.research_summary()
    assert summary["basin_escape"]["activation_status"] == "active"
    assert summary["basin_escape"]["initial_fit_score"] == pytest.approx(0.85)


def test_basin_escape_can_activate_after_broad_group_warmup() -> None:
    initial = _params()
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=["u_GammaPower"],
        structured_fish_config={
            "basin_escape": {
                "enabled": True,
                "pair_count": 1,
                "radii": [1.0],
                "activation_min_fit_score": 0.80,
                "activation_mode": "after_broad_groups",
            },
        },
    )

    current = initial
    groups: list[str] = []
    for iteration, score in enumerate((0.60, 0.85, 0.85, 0.85)):
        current, decision = strategy.propose(_context(iteration, current, score))
        group = str(decision["structured_fish"]["group"])
        groups.append(group)
        if group == "basin_escape":
            break

    assert groups[0] == "material_scalar"
    assert groups[-1] == "basin_escape"
    summary = strategy.research_summary()
    assert summary["basin_escape"]["activation_mode"] == "after_broad_groups"
    assert summary["basin_escape"]["activation_status"] == "active"
    assert summary["basin_escape"]["activation_fit_score"] == pytest.approx(0.85)


def test_fit_cli_accepts_structured_fish_optimizer() -> None:
    args = parse_fit_args(["--config", "fit_config.json", "--optimizer", "structured_fish"])
    assert args.optimizer == "structured_fish"


def test_material_block_hybrid_transitions_between_asset_independent_blocks() -> None:
    pytest.importorskip("cmaes")
    initial = {"u_GammaPower": 1.0, "u_RimIntensity": 1.0}
    shader_params = [
        ShaderParam("u_GammaPower", "Float", default=1.0),
        ShaderParam("u_RimIntensity", "Float", default=1.0),
    ]
    strategy = build_strategy(
        optimizer="material_block_hybrid",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        material_block_hybrid_config={
            "block_order": ["base_surface", "rim"],
            "block_iterations": 2,
            "population_size": 4,
            "refine_enabled": False,
            "seed": 7,
        },
    )

    current = initial
    active_names: list[str | None] = []
    for iteration in range(5):
        current, decision = strategy.propose(
            _context(iteration, current, 0.5 + 0.01 * iteration)
        )
        active_names.append(decision["material_block_hybrid"]["active_name"])

    assert active_names == [
        "base_surface",
        "base_surface",
        "rim",
        "rim",
        None,
    ]
    summary = strategy.research_summary()
    assert [stage["name"] for stage in summary["completed_stages"]] == [
        "base_surface",
        "rim",
    ]
    assert summary["target_params_visible"] is False
    assert strategy.stop_reason() == "material_block_hybrid_complete"


def test_cma_encoder_honors_structured_coordinate_bound_overrides() -> None:
    params = {"u_SpecularIntensity": 1.0, "u_SpeOffet": [0.0, 0.0, 0.0, 0.0]}
    shader_params = [
        ShaderParam("u_SpecularIntensity", "Float", default=1.0),
        ShaderParam("u_SpeOffet", "Vector4", default=[0.0, 0.0, 0.0, 0.0]),
    ]
    bounds = {"u_SpecularIntensity": (0.0, 10.0)}
    bounds.update({f"u_SpeOffet[{index}]": (-2.0, 2.0) for index in range(4)})

    encoder = ParameterEncoder(
        params,
        shader_params,
        param_whitelist=list(params),
        axis_bounds=bounds,
    )

    assert encoder.lower_bounds.tolist() == pytest.approx([0.0, -2.0, -2.0, -2.0, -2.0])
    assert encoder.upper_bounds.tolist() == pytest.approx([10.0, 2.0, 2.0, 2.0, 2.0])
    assert all(axis.transform == "linear" for axis in encoder.axes)


def test_fit_cli_accepts_material_block_hybrid_optimizer() -> None:
    args = parse_fit_args(
        ["--config", "fit_config.json", "--optimizer", "material_block_hybrid"]
    )
    assert args.optimizer == "material_block_hybrid"


def test_material_stage1_hybrid_uses_reproduced_stage_order() -> None:
    pytest.importorskip("cmaes")
    initial = {
        "u_SkyRotateX": 0.0,
        "u_GammaPower": 1.0,
        "u_RimIntensity": 1.0,
        "u_SpecularIntensity": 1.0,
        "u_Contrast": 1.0,
    }
    shader_params = [
        ShaderParam(name, "Float", default=float(value))
        for name, value in initial.items()
    ]
    strategy = build_strategy(
        optimizer="material_stage1_hybrid",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        material_stage1_hybrid_config={
            "warmup_iterations": 1,
            "block_iterations": 1,
            "refine_iterations": 1,
            "late_scene_realign_iterations": 1,
            "late_material_polish_iterations": 1,
            "late_realign_trigger_score": 0.99,
            "local_jacobian_iterations": 1,
            "local_jacobian_trigger_score": 0.99,
            "local_jacobian": {
                "difference_mode": "forward",
                "acceptance_objective": "fit_score",
                "active_coordinate_count": 2,
            },
            "terminal_pattern_iterations": 1,
            "terminal_pattern": {
                "active_coordinate_count": 2,
                "full_refresh_interval": 1,
            },
            "population_size": 4,
            "seed": 11,
        },
    )

    current = initial
    active_names: list[str | None] = []
    for iteration in range(11):
        current, decision = strategy.propose(
            _context(iteration, current, 0.5 + 0.01 * iteration)
        )
        active_names.append(decision["material_stage1_hybrid"]["active_name"])

    assert active_names == [
        "scene_and_material",
        "rim",
        "specular",
        "tone_shadow",
        "base_surface",
        "material_only",
        "late_scene_realign",
        "late_material_polish",
        "local_material_jacobian",
        "terminal_material_pattern",
        None,
    ]
    summary = strategy.research_summary()
    assert summary["target_params_visible"] is False
    assert [stage["name"] for stage in summary["completed_stages"]] == [
        "scene_and_material",
        "rim",
        "specular",
        "tone_shadow",
        "base_surface",
        "material_only",
        "late_scene_realign",
        "late_material_polish",
        "local_material_jacobian",
        "terminal_material_pattern",
    ]
    assert summary["late_realign_activated"] is True
    assert summary["local_jacobian_activated"] is True
    assert summary["local_jacobian"]["difference_mode"] == "forward"
    assert summary["terminal_pattern_activated"] is True
    assert summary["terminal_pattern_completed"] is True
    local_summary = summary["completed_stages"][-2]["nested"]
    assert local_summary["difference_mode"] == "forward"
    assert local_summary["active_coordinate_count"] == 2
    assert strategy.stop_reason() == "material_stage1_hybrid_complete"


def test_material_stage1_hybrid_skips_late_realign_above_threshold() -> None:
    pytest.importorskip("cmaes")
    initial = {
        "u_SkyRotateX": 0.0,
        "u_GammaPower": 1.0,
        "u_RimIntensity": 1.0,
        "u_SpecularIntensity": 1.0,
        "u_Contrast": 1.0,
    }
    shader_params = [
        ShaderParam(name, "Float", default=float(value))
        for name, value in initial.items()
    ]
    strategy = build_strategy(
        optimizer="material_stage1_hybrid",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        material_stage1_hybrid_config={
            "warmup_iterations": 1,
            "block_iterations": 1,
            "refine_iterations": 1,
            "late_scene_realign_iterations": 1,
            "late_material_polish_iterations": 1,
            "late_realign_trigger_score": 0.75,
            "local_jacobian_iterations": 1,
            "local_jacobian_trigger_score": 0.75,
            "population_size": 4,
            "seed": 11,
        },
    )

    current = initial
    for iteration in range(7):
        current, decision = strategy.propose(
            _context(iteration, current, 0.8 + 0.01 * iteration)
        )

    assert decision["material_stage1_hybrid"]["active_name"] is None
    summary = strategy.research_summary()
    assert summary["late_realign_activated"] is False
    assert summary["local_jacobian_activated"] is False
    assert [stage["name"] for stage in summary["completed_stages"]] == [
        "scene_and_material",
        "rim",
        "specular",
        "tone_shadow",
        "base_surface",
        "material_only",
    ]
    assert strategy.stop_reason() == "material_stage1_hybrid_complete"


def test_material_stage1_hybrid_can_use_secant_local_refiner() -> None:
    pytest.importorskip("cmaes")
    initial = {
        "u_GammaPower": 1.0,
        "u_RimIntensity": 1.0,
        "u_RimWidth": 1.0,
    }
    shader_params = [
        ShaderParam(name, "Float", default=float(value))
        for name, value in initial.items()
    ]
    strategy = build_strategy(
        optimizer="material_stage1_hybrid",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        material_stage1_hybrid_config={
            "block_order": ["rim"],
            "warmup_iterations": 1,
            "block_iterations": 1,
            "refine_iterations": 1,
            "late_realign_trigger_score": 0.0,
            "local_jacobian_iterations": 1,
            "local_jacobian_trigger_score": 1.0,
            "local_refiner_strategy": "material_secant_trust_region",
            "local_refiner": {
                "design_size": 1,
                "compressed_design": True,
                "antithetic": False,
            },
            "population_size": 4,
            "seed": 11,
        },
    )

    current = initial
    active_names: list[str | None] = []
    for iteration in range(5):
        score = 0.5 + 0.01 * iteration
        current, decision = strategy.propose(
            _context(
                iteration,
                current,
                score,
                {
                    "structured_residual_features": {
                        "features": [1.0 - score],
                    }
                },
            )
        )
        active_names.append(decision["material_stage1_hybrid"]["active_name"])

    assert active_names == [
        "scene_and_material",
        "rim",
        "material_only",
        "local_material_secant",
        None,
    ]
    summary = strategy.research_summary()
    assert summary["local_refiner_strategy"] == "material_secant_trust_region"
    assert summary["local_jacobian_activated"] is True
    assert summary["completed_stages"][-1]["kind"] == "local_material_refiner"
    assert summary["completed_stages"][-1]["nested"]["profile"] == (
        "material_secant_trust_region_v2"
    )


def test_material_stage1_hybrid_scalar_grid_scan_uses_online_score_only() -> None:
    pytest.importorskip("cmaes")
    initial = {
        "u_GammaPower": 1.0,
        "u_EmissionPow": 0.0,
    }
    shader_params = [
        ShaderParam(name, "Float", default=float(value))
        for name, value in initial.items()
    ]
    strategy = build_strategy(
        optimizer="material_stage1_hybrid",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        material_stage1_hybrid_config={
            "structured_only": True,
            "scalar_grid_scans": [
                {"param_name": "u_EmissionPow", "values": [0.0, 4.0, 16.0]}
            ],
            "warmup_iterations": 1,
            "block_iterations": 1,
            "refine_iterations": 1,
            "late_scene_realign_iterations": 1,
            "late_material_polish_iterations": 1,
            "local_jacobian_iterations": 1,
        },
    )

    current = initial
    proposed_values: list[float] = []
    for iteration in range(4):
        score = 1.0 - abs(float(current["u_EmissionPow"]) - 16.0) / 16.0
        current, decision = strategy.propose(_context(iteration, current, score))
        if decision["material_stage1_hybrid"]["active_kind"] == "scalar_grid_scan":
            proposed_values.append(float(current["u_EmissionPow"]))

    summary = strategy.research_summary()
    scan = summary["scalar_grid_scans"]
    assert proposed_values == [0.0, 4.0, 16.0]
    assert scan["completed"][0]["best_value"] == 16.0
    assert scan["completed"][0]["best_fit_score"] == 1.0
    assert scan["target_params_visible"] is False
    assert summary["target_params_visible"] is False


def test_fit_cli_accepts_material_stage1_hybrid_optimizer() -> None:
    args = parse_fit_args(
        ["--config", "fit_config.json", "--optimizer", "material_stage1_hybrid"]
    )
    assert args.optimizer == "material_stage1_hybrid"


def test_structured_param_audit_allows_only_explicit_scene_alignment() -> None:
    params = _params()
    names = structured_fish_search_param_names(params, _shader_params())
    default_audit = build_param_policy_audit(params, _shader_params(), search_param_names=names)
    structured_audit = build_param_policy_audit(
        params,
        _shader_params(),
        search_param_names=names,
        allow_scene_lighting_search=True,
    )

    default_locked = {row["name"] for row in default_audit["locked_params"]}
    structured_searchable = {row["name"] for row in structured_audit["searchable_params"]}
    assert "u_SkyRotateY" in default_locked
    assert "u_SkyRotateY" in structured_searchable
    assert "u_MainTex_ST" not in structured_searchable
    assert "u_AlphaTestValue" not in structured_searchable


def test_structured_strategy_starts_with_scene_alignment_and_preserves_vector_shape() -> None:
    initial = _params()
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=structured_fish_search_param_names(initial, shader_params),
    )

    candidate, decision = strategy.propose(_context(0, initial, 0.75))
    assert strategy.name == "structured_fish"
    assert decision["structured_fish"]["group"] == "scene_alignment"
    assert decision["structured_fish"]["coordinate"] == "u_SkyRotateX"
    assert candidate["u_SkyRotateX"] == pytest.approx(-22.5)
    assert candidate["u_Color"] == [1.0, 1.0, 1.0, 1.0]

    color_coordinate = next(
        coordinate
        for coordinate in structured_fish_coordinates(initial)
        if coordinate.coordinate_id == "u_Color[0]"
    )
    changed = color_coordinate.write(initial, 0.5)
    assert changed["u_Color"] == [0.5, 1.0, 1.0, 1.0]


def test_ranked_coordinate_search_accepts_first_improving_direction_opportunistically() -> None:
    initial = {"u_GammaPower": 1.0}
    shader_params = [ShaderParam("u_GammaPower", "Float", default=1.0)]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=["u_GammaPower"],
        structured_fish_config={"opportunistic_ranked_accept": True},
    )

    minus_candidate, _ = strategy.propose(_context(0, initial, 0.70))
    assert minus_candidate["u_GammaPower"] == pytest.approx(0.70)
    plus_candidate, _ = strategy.propose(_context(1, minus_candidate, 0.60))
    assert plus_candidate["u_GammaPower"] == pytest.approx(1.30)
    ranked_candidate, ranked_decision = strategy.propose(
        _context(2, plus_candidate, 0.80)
    )
    assert ranked_decision["structured_fish"]["phase"] == "ranked_refinement"
    assert ranked_candidate["u_GammaPower"] == pytest.approx(1.60)

    next_round_candidate, _ = strategy.propose(_context(3, ranked_candidate, 0.90))
    assert next_round_candidate["u_GammaPower"] == pytest.approx(1.90)
    assert strategy.research_summary()["opportunistic_skip_count"] == 1


def test_broad_coordinate_line_pursuit_repeats_an_improving_axis() -> None:
    initial = {"u_GammaPower": 1.0}
    shader_params = [ShaderParam("u_GammaPower", "Float", default=1.0)]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=["u_GammaPower"],
        structured_fish_config={"broad_coordinate_max_repeats": 2},
    )

    current = initial
    broad_values: list[float] = []
    for iteration in range(10):
        score = float(current["u_GammaPower"])
        current, decision = strategy.propose(_context(iteration, current, score))
        structured = decision["structured_fish"]
        if structured["phase"] != "broad_groups":
            break
        broad_values.append(float(current["u_GammaPower"]))

    assert broad_values[:6] == pytest.approx([0.7, 1.3, 1.0, 1.6, 1.3, 1.9])
    summary = strategy.research_summary()
    assert summary["broad_coordinate_max_repeats"] == 2
    assert summary["broad_coordinate_repeat_count"] == 2


def test_structured_strategy_uses_parabolic_coordinate_interpolation() -> None:
    initial: dict[str, object] = {"u_SkyRotateY": 0.0}
    shader_params = [ShaderParam("u_SkyRotateY", "Float", default=0.0)]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=["u_SkyRotateY"],
    )
    target = 31.5

    def score(params: dict[str, object]) -> float:
        value = float(params["u_SkyRotateY"])
        return 1.0 - ((value - target) / 180.0) ** 2

    first, first_decision = strategy.propose(_context(0, initial, score(initial)))
    second, second_decision = strategy.propose(_context(1, first, score(first)))
    third, third_decision = strategy.propose(_context(2, second, score(second)))

    assert first_decision["structured_fish"]["probe_kind"] == "axis"
    assert second_decision["structured_fish"]["probe_kind"] == "axis"
    assert third_decision["structured_fish"]["probe_kind"] == "parabolic"
    assert float(third["u_SkyRotateY"]) == pytest.approx(target)


def test_structured_strategy_uses_joint_pattern_after_broad_responses() -> None:
    initial: dict[str, object] = {"u_SkyRotateX": 0.0, "u_SkyRotateY": 0.0}
    shader_params = [
        ShaderParam("u_SkyRotateX", "Float", default=0.0),
        ShaderParam("u_SkyRotateY", "Float", default=0.0),
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        structured_fish_config={"pattern_move_scale": 0.5},
    )

    def score(params: dict[str, object]) -> float:
        return 0.5 + 0.001 * (
            float(params["u_SkyRotateX"]) + float(params["u_SkyRotateY"])
        )

    current = initial
    joint_candidate: dict[str, object] | None = None
    joint_decision: dict[str, object] | None = None
    for iteration in range(12):
        current, decision = strategy.propose(_context(iteration, current, score(current)))
        if decision.get("structured_fish", {}).get("probe_kind") == "joint_pattern":
            joint_candidate = current
            joint_decision = decision
            break

    assert joint_candidate is not None
    assert joint_decision is not None
    assert set(joint_decision["structured_fish"]["coordinates"]) == {
        "u_SkyRotateX",
        "u_SkyRotateY",
    }
    assert float(joint_candidate["u_SkyRotateX"]) > 22.5
    assert float(joint_candidate["u_SkyRotateY"]) > 22.5


def test_structured_strategy_reports_configured_regularization() -> None:
    initial = _params()
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=structured_fish_search_param_names(initial, shader_params),
        structured_fish_config={"regularization_weight": 0.1},
    )
    strategy.propose(_context(0, initial, 0.75))
    assert strategy.research_summary()["regularization_weight"] == pytest.approx(0.1)


def test_structured_strategy_anneals_regularization_between_ranked_rounds() -> None:
    initial: dict[str, object] = {"u_SkyRotateX": 0.0, "u_SkyRotateY": 0.0}
    shader_params = [
        ShaderParam("u_SkyRotateX", "Float", default=0.0),
        ShaderParam("u_SkyRotateY", "Float", default=0.0),
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        structured_fish_config={
            "regularization_weight": 0.1,
            "regularization_final_weight": 0.0,
            "regularization_decay": 0.5,
        },
    )

    current = initial
    for iteration in range(16):
        current, _ = strategy.propose(_context(iteration, current, 0.5))
        summary = strategy.research_summary()
        if summary["round"] >= 2:
            break

    assert summary["round"] >= 2
    assert summary["regularization_initial_weight"] == pytest.approx(0.1)
    assert summary["regularization_weight"] == pytest.approx(0.05)


def test_structured_strategy_permanently_disables_regularization_at_online_score_gate() -> None:
    initial = _params()
    shader_params = _shader_params()
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=structured_fish_search_param_names(initial, shader_params),
        structured_fish_config={
            "regularization_weight": 0.1,
            "regularization_final_weight": 0.0,
            "regularization_decay": 0.5,
            "regularization_disable_score": 0.985,
        },
    )

    strategy.propose(_context(0, initial, 0.99))
    strategy._round_index = 3
    strategy._update_regularization_schedule()
    summary = strategy.research_summary()

    assert summary["regularization_disabled_by_score"] is True
    assert summary["regularization_disable_trigger_score"] == pytest.approx(0.99)
    assert summary["regularization_weight"] == 0.0




def test_structured_strategy_freezes_scene_after_dedicated_alignment_rounds() -> None:
    initial: dict[str, object] = {
        "u_SkyRotateX": 0.0,
        "u_LightRotateY": 0.0,
        "u_GammaPower": 1.0,
        "u_Saturation": 1.0,
    }
    shader_params = [
        ShaderParam(name, "Float", default=value)
        for name, value in initial.items()
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        structured_fish_config={
            "scene_alignment_rounds": 2,
            "freeze_scene_after_alignment": True,
        },
    )

    current = initial
    scene_probe_count = 0
    observed_scene_rounds: set[int] = set()
    ranked_summary: dict[str, object] | None = None
    for iteration in range(80):
        current, decision = strategy.propose(_context(iteration, current, 0.5))
        structured = decision.get("structured_fish", {})
        if structured.get("group") == "scene_alignment":
            scene_probe_count += 1
            observed_scene_rounds.add(int(structured["round"]))
        summary = strategy.research_summary()
        if summary["phase"] == "ranked_refinement":
            ranked_summary = summary
            break

    assert ranked_summary is not None
    assert scene_probe_count == 8
    assert observed_scene_rounds == {1, 2}
    assert ranked_summary["scene_alignment_round"] == 2
    assert ranked_summary["scene_alignment_frozen"] is True
    assert set(ranked_summary["agenda"]) == {"u_GammaPower", "u_Saturation"}


def test_structured_strategy_builds_gauss_newton_joint_probe() -> None:
    initial: dict[str, object] = {"u_SkyRotateX": 0.0, "u_SkyRotateY": 0.0}
    shader_params = [
        ShaderParam("u_SkyRotateX", "Float", default=0.0),
        ShaderParam("u_SkyRotateY", "Float", default=0.0),
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        structured_fish_config={
            "gauss_newton_damping": 0.75,
            "gauss_newton_ridge": 0.001,
        },
    )

    def analysis(params: dict[str, object]) -> dict[str, object]:
        return {
            "structured_residual_features": {
                "features": [
                    (float(params["u_SkyRotateX"]) - 10.0) / 100.0,
                    (float(params["u_SkyRotateY"]) + 5.0) / 100.0,
                ]
            }
        }

    current = initial
    gn_candidate: dict[str, object] | None = None
    for iteration in range(12):
        current, decision = strategy.propose(
            _context(iteration, current, 0.5, analysis(current))
        )
        if decision.get("structured_fish", {}).get("probe_kind") == "gauss_newton":
            gn_candidate = current
            break

    assert gn_candidate is not None
    assert float(gn_candidate["u_SkyRotateX"]) == pytest.approx(7.47, abs=0.15)
    assert float(gn_candidate["u_SkyRotateY"]) == pytest.approx(-3.74, abs=0.15)


def test_structured_strategy_repeats_accepted_gauss_newton_probe_immediately() -> None:
    initial: dict[str, object] = {"u_SkyRotateX": 0.0, "u_SkyRotateY": 0.0}
    shader_params = [
        ShaderParam("u_SkyRotateX", "Float", default=0.0),
        ShaderParam("u_SkyRotateY", "Float", default=0.0),
    ]
    strategy = build_strategy(
        optimizer="structured_fish",
        initial_params=initial,
        shader_params=shader_params,
        policies=build_adjustment_policies(shader_params),
        unity_material_params={},
        search_param_names=list(initial),
        structured_fish_config={"gauss_newton_max_repeats": 2},
    )

    def analysis(params: dict[str, object]) -> dict[str, object]:
        return {
            "structured_residual_features": {
                "features": [
                    (
                        float(params["u_SkyRotateX"])
                        + float(params["u_SkyRotateY"])
                        - 10.0
                    )
                    / 100.0,
                    (
                        float(params["u_SkyRotateX"])
                        + 0.5 * float(params["u_SkyRotateY"])
                        - 5.0
                    )
                    / 100.0,
                ]
            }
        }

    def score(params: dict[str, object]) -> float:
        features = analysis(params)["structured_residual_features"]["features"]
        return 1.0 - sum(float(value) ** 2 for value in features)

    current = initial
    first_gn_iteration: int | None = None
    repeated_decision: dict[str, object] | None = None
    for iteration in range(40):
        current, decision = strategy.propose(
            _context(iteration, current, score(current), analysis(current))
        )
        structured = decision.get("structured_fish", {})
        if structured.get("probe_kind") != "gauss_newton":
            continue
        if first_gn_iteration is None:
            first_gn_iteration = iteration
            continue
        repeated_decision = decision
        assert iteration == first_gn_iteration + 1
        break

    assert repeated_decision is not None, (first_gn_iteration, strategy.research_summary())
    repeated = repeated_decision["structured_fish"]
    assert repeated["repeat_index"] == 1
    assert repeated["damping"] == pytest.approx(0.9)


def test_structured_strategy_routes_gauss_newton_cadence_by_online_score() -> None:
    strategy = StructuredFishStrategy(
        initial_params={"u_GammaPower": 1.0, "u_Saturation": 1.0},
        shader_params=[
            ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0, range_max=3.0),
            ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
        ],
        search_param_names=["u_GammaPower", "u_Saturation"],
        gauss_newton_interval=16,
        gauss_newton_max_repeats=2,
        gauss_newton_high_score_threshold=0.97,
        gauss_newton_high_score_interval=8,
        gauss_newton_high_score_max_repeats=4,
    )

    strategy._best_fit_score = 0.96
    assert strategy._effective_gauss_newton_interval() == 16
    assert strategy._effective_gauss_newton_max_repeats() == 2
    strategy._best_fit_score = 0.97
    assert strategy._effective_gauss_newton_interval() == 8
    assert strategy._effective_gauss_newton_max_repeats() == 4




def test_structured_residual_features_preserve_signed_rgb(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    reference_path = tmp_path / "view.png"
    candidate_path = tmp_path / "candidate" / "view.png"
    candidate_path.parent.mkdir()
    reference = Image.new("RGBA", (16, 16), (255, 255, 255, 255))
    candidate = reference.copy()
    ImageDraw.Draw(reference).rectangle((4, 4, 11, 11), fill=(100, 100, 100, 255))
    ImageDraw.Draw(candidate).rectangle((4, 4, 11, 11), fill=(120, 90, 100, 255))
    reference.save(reference_path)
    candidate.save(candidate_path)
    config = {
        "structured_fish": {
            "residual_features": {
                "enabled": True,
                "grid_size": 2,
                "foreground_threshold": 8.0,
            }
        },
        "laya_capture": {
            "browser_score": {
                "reference_images": [{"view_id": "v0", "path": str(reference_path)}]
            }
        },
    }
    payload = _structured_residual_feature_payload(
        {"screenshots": [str(candidate_path)]},
        config=config,
    )

    assert payload is not None
    assert payload["profile"] == "signed_rgb_grid_v1"
    assert payload["feature_count"] == 12
    signed = payload["signed_rgb_candidate_minus_reference"]
    assert signed[0] == pytest.approx(20.0 / 255.0)
    assert signed[1] == pytest.approx(-10.0 / 255.0)
    assert signed[2] == pytest.approx(0.0)


def test_browser_score_analysis_uses_inline_residual_features_without_pngs() -> None:
    render_result = {
        "browser_score": {
            "fit_score": 0.9,
            "diff_score": 0.1,
            "views": [],
            "structured_residual_features": {
                "profile": "signed_rgb_grid_v1",
                "grid_size": 2,
                "features": [0.1, -0.2, 0.0],
            },
        },
        "screenshots": [],
    }
    payload = _browser_score_analysis_payload(render_result, config={})
    residual = payload["analysis"]["structured_residual_features"]
    assert residual["source"] == "browser_score"
    assert residual["features"] == [0.1, -0.2, 0.0]
