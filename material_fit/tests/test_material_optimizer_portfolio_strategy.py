from __future__ import annotations

import copy
from typing import Any

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_optimizer_portfolio_strategy import (
    MaterialOptimizerPortfolioStrategy,
)
from material_fit.optimizer.strategy_core import StrategyContext


class _FakeJacobian:
    instances: list["_FakeJacobian"] = []

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: list[Any],
        search_param_names: list[str],
        config: dict[str, Any],
    ) -> None:
        self.initial_params = copy.deepcopy(initial_params)
        self.config = copy.deepcopy(config)
        self.proposals = 0
        self.instances.append(self)

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self.proposals += 1
        candidate = copy.deepcopy(ctx.current_params)
        candidate["x"] = float(candidate["x"]) + float(self.config["delta"])
        return candidate, {"changes": [{"name": "x"}], "stop_reason": "continue"}

    def stop_reason(self) -> None:
        return None

    def research_summary(self) -> dict[str, Any]:
        return {"delta": self.config["delta"], "proposals": self.proposals}


def _context(params: dict[str, float], score: float, iteration: int) -> StrategyContext:
    return StrategyContext(
        iteration=iteration,
        current_params=copy.deepcopy(params),
        analysis={"score": score},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=copy.deepcopy(params)),
    )


def test_portfolio_restarts_branches_from_shared_seed_and_returns_global_best(
    monkeypatch,
) -> None:
    from material_fit.optimizer import material_optimizer_portfolio_strategy as module

    _FakeJacobian.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    strategy = MaterialOptimizerPortfolioStrategy(
        initial_params={"x": 0.0},
        shader_params=[],
        search_param_names=["x"],
        config={
            "branches": [
                {
                    "name": "first",
                    "optimizer": "jacobian",
                    "max_proposals": 1,
                    "start_from": "shared_seed",
                    "jacobian": {"delta": 1.0},
                },
                {
                    "name": "second",
                    "optimizer": "jacobian",
                    "max_proposals": 1,
                    "start_from": "shared_seed",
                    "jacobian": {"delta": 2.0},
                },
            ]
        },
    )

    first, _ = strategy.propose(_context({"x": 0.0}, 0.5, 0))
    second, decision = strategy.propose(_context(first, 0.7, 1))
    best, final = strategy.propose(_context(second, 0.9, 2))

    assert first == {"x": 1.0}
    assert second == {"x": 2.0}
    assert best == {"x": 2.0}
    assert [instance.initial_params for instance in _FakeJacobian.instances] == [
        {"x": 0.0},
        {"x": 0.0},
    ]
    assert decision["material_optimizer_portfolio"]["branch_name"] == "second"
    assert final["stop_reason"] == "material_optimizer_portfolio_complete"
    assert strategy.stop_reason() == "material_optimizer_portfolio_complete"
    summary = strategy.research_summary()
    assert summary["best_fit_score"] == 0.9
    assert [row["best_fit_score"] for row in summary["branch_summaries"]] == [
        0.7,
        0.9,
    ]


def test_portfolio_can_start_a_later_branch_from_global_best(monkeypatch) -> None:
    from material_fit.optimizer import material_optimizer_portfolio_strategy as module

    _FakeJacobian.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    strategy = MaterialOptimizerPortfolioStrategy(
        initial_params={"x": 0.0},
        shader_params=[],
        search_param_names=["x"],
        config={
            "branches": [
                {
                    "name": "basin",
                    "optimizer": "jacobian",
                    "max_proposals": 1,
                    "jacobian": {"delta": 1.0},
                },
                {
                    "name": "polish",
                    "optimizer": "jacobian",
                    "max_proposals": 1,
                    "start_from": "global_best",
                    "jacobian": {"delta": 2.0},
                },
            ]
        },
    )

    first, _ = strategy.propose(_context({"x": 0.0}, 0.5, 0))
    second, _ = strategy.propose(_context(first, 0.8, 1))

    assert second == {"x": 3.0}
    assert _FakeJacobian.instances[1].initial_params == {"x": 1.0}
