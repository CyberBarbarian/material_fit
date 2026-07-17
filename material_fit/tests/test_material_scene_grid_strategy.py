from __future__ import annotations

import copy
from typing import Any

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_scene_grid_strategy import (
    MaterialSceneGridStrategy,
)
from material_fit.optimizer.strategy_core import StrategyContext


def _context(params: dict[str, Any], score: float, iteration: int) -> StrategyContext:
    return StrategyContext(
        iteration=iteration,
        current_params=copy.deepcopy(params),
        analysis={},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=copy.deepcopy(params)),
    )


def test_scene_grid_searches_circular_values_and_keeps_online_best() -> None:
    strategy = MaterialSceneGridStrategy(
        initial_params={"u_SkyRotateX": 0.0},
        shader_params=[],
        search_param_names=["u_SkyRotateX"],
        config={
            "coarse_values": [-180.0, -90.0, 0.0, 90.0],
            "refinement_steps": [],
        },
    )
    params = {"u_SkyRotateX": 0.0}
    candidate, _ = strategy.propose(_context(params, 0.5, 0))
    assert candidate["u_SkyRotateX"] in {-180.0, 180.0}
    candidate, _ = strategy.propose(_context(candidate, 0.6, 1))
    assert candidate["u_SkyRotateX"] == -90.0
    strategy.propose(_context(candidate, 0.4, 2))

    summary = strategy.research_summary()
    assert summary["best_fit_score"] == 0.6
    assert summary["accept_count"] == 1
