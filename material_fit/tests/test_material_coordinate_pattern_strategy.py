from __future__ import annotations

from material_fit.fit_cli import parse_fit_args
from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_coordinate_pattern_strategy import (
    MaterialCoordinatePatternStrategy,
)
from material_fit.optimizer.material_discrete_space import (
    DISCRETE_CANDIDATE_PARAM,
    attach_discrete_candidate,
    build_legal_discrete_candidates,
)
from material_fit.optimizer.strategy import build_strategy
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_GammaPower", "Range", default=1.0, range_min=0.0001, range_max=3.0),
        ShaderParam("u_Saturation", "Range", default=1.0, range_min=0.0, range_max=2.0),
    ]


def _context(iteration: int, params: dict[str, float], target: dict[str, float]) -> StrategyContext:
    error = (
        ((params["u_GammaPower"] - target["u_GammaPower"]) / 2.9999) ** 2
        + ((params["u_Saturation"] - target["u_Saturation"]) / 2.0) ** 2
    )
    score = 1.0 - min(error, 1.0)
    return StrategyContext(
        iteration=iteration,
        current_params=params,
        analysis={},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=params),
    )


def test_coordinate_pattern_recovers_unknown_target_from_scores_only() -> None:
    initial = {"u_GammaPower": 0.45, "u_Saturation": 1.55}
    target = {"u_GammaPower": 1.65, "u_Saturation": 0.65}
    strategy = MaterialCoordinatePatternStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "initial_step_scale": 1.0,
            "active_coordinate_count": 1,
            "full_refresh_interval": 3,
        },
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    for iteration in range(48):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, decision = strategy.propose(context)
        assert decision["material_coordinate_pattern"]["target_params_visible"] is False
    best_score = max(best_score, _context(48, current, target).fit_score)

    summary = strategy.research_summary()
    assert best_score > 0.999
    assert summary["accepted_moves"] > 0
    assert summary["full_sweeps"] > 0
    assert summary["active_sweeps"] > 0


def test_initial_grid_crosses_a_local_start_basin_without_target_parameters() -> None:
    initial = {"u_GammaPower": 1.3, "u_Saturation": 1.0}
    target = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = MaterialCoordinatePatternStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower"],
        config={"initial_grid_points": 17},
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    for iteration in range(20):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, decision = strategy.propose(context)
        assert decision["material_coordinate_pattern"]["target_params_visible"] is False

    summary = strategy.research_summary()
    assert best_score > 0.999
    assert summary["initial_grid_points"] == 17
    assert summary["initial_grid_probe_count"] >= 16
    assert summary["accepted_initial_grid_moves"] > 0


def test_initial_grid_composes_improvements_across_coordinates() -> None:
    initial = {"u_GammaPower": 0.0001, "u_Saturation": 0.0}
    target = {"u_GammaPower": 1.50005, "u_Saturation": 1.0}
    strategy = MaterialCoordinatePatternStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={"initial_grid_points": 3},
    )

    current = dict(initial)
    best_score = _context(0, current, target).fit_score
    for iteration in range(8):
        context = _context(iteration, current, target)
        best_score = max(best_score, context.fit_score)
        current, _decision = strategy.propose(context)
    best_score = max(best_score, _context(8, current, target).fit_score)

    assert best_score > 0.999
    assert strategy.research_summary()["accepted_initial_grid_moves"] >= 2


def test_factory_builds_coordinate_pattern_with_config() -> None:
    initial = {"u_GammaPower": 1.0, "u_Saturation": 1.0}
    strategy = build_strategy(
        optimizer="material_coordinate_pattern",
        initial_params=initial,
        shader_params=_shader_params(),
        policies=[],
        unity_material_params=None,
        search_param_names=list(initial),
        material_coordinate_pattern_config={"active_coordinate_count": 1},
    )

    assert isinstance(strategy, MaterialCoordinatePatternStrategy)
    assert strategy.research_summary()["active_coordinate_count"] == 1


def test_coordinate_pattern_can_extrapolate_joint_accepted_moves() -> None:
    initial = {"u_GammaPower": 0.45, "u_Saturation": 1.55}
    target = {"u_GammaPower": 1.65, "u_Saturation": 0.65}
    strategy = MaterialCoordinatePatternStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=list(initial),
        config={
            "initial_step_scale": 0.5,
            "active_coordinate_count": 2,
            "pattern_move_scales": [1.0, 0.5],
        },
    )

    current = dict(initial)
    for iteration in range(40):
        current, decision = strategy.propose(_context(iteration, current, target))
        assert decision["material_coordinate_pattern"]["target_params_visible"] is False

    summary = strategy.research_summary()
    assert summary["pattern_probe_count"] > 0
    assert summary["accepted_pattern_moves"] > 0


def test_coordinate_pattern_searches_legal_hard_states_in_the_same_loop() -> None:
    candidates = build_legal_discrete_candidates(
        {
            "defines": {
                "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
                "enabled": [],
            },
            "render_states": {"s_Blend": 0, "s_BlendSrc": 0},
        }
    )
    initial = attach_discrete_candidate(
        {"u_GammaPower": 1.0, "u_Saturation": 1.0},
        candidates[0],
    )
    target_candidate = candidates[7]
    strategy = MaterialCoordinatePatternStrategy(
        initial_params=initial,
        shader_params=_shader_params(),
        search_param_names=["u_GammaPower", "u_Saturation"],
        discrete_candidates=candidates,
    )

    current = initial
    for iteration in range(18):
        candidate = current[DISCRETE_CANDIDATE_PARAM]
        score = 1.0 if candidate["candidate_id"] == target_candidate["candidate_id"] else 0.5
        current, _decision = strategy.propose(
            StrategyContext(
                iteration=iteration,
                current_params=current,
                analysis={},
                diff_score=1.0 - score,
                fit_score=score,
                state=AdjustmentState(best_params=current),
            )
        )

    summary = strategy.research_summary()
    assert summary["hard_state_probe_count"] == len(candidates) - 1
    assert summary["accepted_hard_state_moves"] == 1
    assert summary["best_hard_state_candidate_id"] == target_candidate["candidate_id"]


def test_fit_cli_accepts_coordinate_pattern_optimizer() -> None:
    args = parse_fit_args(
        ["--config", "fit_config.json", "--optimizer", "material_coordinate_pattern"]
    )

    assert args.optimizer == "material_coordinate_pattern"
