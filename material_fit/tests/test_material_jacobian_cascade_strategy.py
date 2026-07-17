from __future__ import annotations

import copy
from typing import Any

from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.material_jacobian_cascade_strategy import (
    MaterialJacobianCascadeStrategy,
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
        self.search_param_names = list(search_param_names)
        self.config = copy.deepcopy(config)
        self.proposals = 0
        self.instances.append(self)

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self.proposals += 1
        candidate = copy.deepcopy(ctx.current_params)
        candidate["x"] = float(candidate["x"]) + 1.0
        return candidate, {"changes": [{"name": "x"}], "stop_reason": "continue"}

    def stop_reason(self) -> None:
        return None

    def research_summary(self) -> dict[str, Any]:
        return {"tag": self.config["tag"], "proposals": self.proposals}


class _FakeSecant(_FakeJacobian):
    instances: list["_FakeSecant"] = []


class _FakePattern(_FakeJacobian):
    instances: list["_FakePattern"] = []


class _FakePortfolio(_FakeJacobian):
    instances: list["_FakePortfolio"] = []


def _context(params: dict[str, Any], score: float, iteration: int) -> StrategyContext:
    return StrategyContext(
        iteration=iteration,
        current_params=copy.deepcopy(params),
        analysis={"score": score},
        diff_score=1.0 - score,
        fit_score=score,
        state=AdjustmentState(best_params=copy.deepcopy(params)),
    )


def test_cascade_switches_on_online_score_and_reseeds_from_observed_best(
    monkeypatch,
) -> None:
    from material_fit.optimizer import material_jacobian_cascade_strategy as module

    _FakeJacobian.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    strategy = MaterialJacobianCascadeStrategy(
        initial_params={"x": 0.0},
        shader_params=[],
        search_param_names=["x"],
        config={
            "total_max_proposals": 2,
            "stages": [
                {
                    "name": "basin",
                    "max_proposals": 2,
                    "minimum_proposals": 0,
                    "switch_score": 0.90,
                    "jacobian": {"tag": "basin"},
                },
                {
                    "name": "refine",
                    "max_proposals": 2,
                    "jacobian": {"tag": "refine"},
                },
            ],
        },
    )

    first, _decision = strategy.propose(_context({"x": 0.0}, 0.80, 0))
    assert first["x"] == 1.0
    second, decision = strategy.propose(_context({"x": 1.0}, 0.91, 1))

    assert second["x"] == 2.0
    assert [instance.config["tag"] for instance in _FakeJacobian.instances] == [
        "basin",
        "refine",
    ]
    assert _FakeJacobian.instances[1].initial_params == {"x": 1.0}
    assert decision["material_jacobian_cascade"]["stage_name"] == "refine"
    assert strategy.stop_reason() == "material_jacobian_cascade_budget_complete"


def test_cascade_can_freeze_parameters_only_in_later_stages(monkeypatch) -> None:
    from material_fit.optimizer import material_jacobian_cascade_strategy as module

    _FakeJacobian.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    strategy = MaterialJacobianCascadeStrategy(
        initial_params={"scene": 0.0, "material": 0.0},
        shader_params=[],
        search_param_names=["scene", "material"],
        config={
            "total_max_proposals": 2,
            "stages": [
                {
                    "name": "joint",
                    "max_proposals": 1,
                    "jacobian": {"tag": "joint"},
                },
                {
                    "name": "material_only",
                    "max_proposals": 1,
                    "frozen_param_names": ["scene"],
                    "jacobian": {"tag": "material_only"},
                },
            ],
        },
    )

    first, _ = strategy.propose(
        _context({"scene": 0.0, "material": 0.0, "x": 0.0}, 0.8, 0)
    )
    strategy.propose(_context(first, 0.9, 1))

    assert _FakeJacobian.instances[0].search_param_names == ["scene", "material"]
    assert _FakeJacobian.instances[1].search_param_names == ["material"]


def test_cascade_can_switch_from_jacobian_to_scene_frozen_secant(
    monkeypatch,
) -> None:
    from material_fit.optimizer import material_jacobian_cascade_strategy as module

    _FakeJacobian.instances = []
    _FakeSecant.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    monkeypatch.setattr(module, "MaterialSecantTrustRegionStrategy", _FakeSecant)
    strategy = MaterialJacobianCascadeStrategy(
        initial_params={"scene": 0.0, "material": 0.0, "x": 0.0},
        shader_params=[],
        search_param_names=["scene", "material"],
        config={
            "total_max_proposals": 2,
            "stages": [
                {
                    "name": "joint",
                    "max_proposals": 1,
                    "jacobian": {"tag": "joint"},
                },
                {
                    "name": "material_secant",
                    "optimizer": "secant",
                    "max_proposals": 1,
                    "frozen_param_names": ["scene"],
                    "secant": {"tag": "material_secant"},
                },
            ],
        },
    )

    first, _ = strategy.propose(
        _context({"scene": 0.0, "material": 0.0, "x": 0.0}, 0.8, 0)
    )
    _candidate, decision = strategy.propose(_context(first, 0.9, 1))

    assert len(_FakeJacobian.instances) == 1
    assert len(_FakeSecant.instances) == 1
    assert _FakeSecant.instances[0].search_param_names == ["material"]
    assert decision["material_jacobian_cascade"]["optimizer"] == "secant"


def test_cascade_can_finish_with_scene_frozen_coordinate_pattern(
    monkeypatch,
) -> None:
    from material_fit.optimizer import material_jacobian_cascade_strategy as module

    _FakeJacobian.instances = []
    _FakePattern.instances = []
    monkeypatch.setattr(module, "MaterialJacobianTrustRegionStrategy", _FakeJacobian)
    monkeypatch.setattr(module, "MaterialCoordinatePatternStrategy", _FakePattern)
    strategy = MaterialJacobianCascadeStrategy(
        initial_params={"scene": 0.0, "material": 0.0, "x": 0.0},
        shader_params=[],
        search_param_names=["scene", "material"],
        config={
            "total_max_proposals": 2,
            "stages": [
                {
                    "name": "joint",
                    "max_proposals": 1,
                    "jacobian": {"tag": "joint"},
                },
                {
                    "name": "material_pattern",
                    "optimizer": "pattern",
                    "max_proposals": 1,
                    "frozen_param_names": ["scene"],
                    "pattern": {"tag": "material_pattern"},
                },
            ],
        },
    )

    first, _ = strategy.propose(
        _context({"scene": 0.0, "material": 0.0, "x": 0.0}, 0.8, 0)
    )
    _candidate, decision = strategy.propose(_context(first, 0.9, 1))

    assert len(_FakeJacobian.instances) == 1
    assert len(_FakePattern.instances) == 1
    assert _FakePattern.instances[0].search_param_names == ["material"]
    assert decision["material_jacobian_cascade"]["optimizer"] == "pattern"


def test_cascade_can_use_a_portfolio_stage(monkeypatch) -> None:
    from material_fit.optimizer import material_jacobian_cascade_strategy as module

    _FakePortfolio.instances = []
    monkeypatch.setattr(module, "MaterialOptimizerPortfolioStrategy", _FakePortfolio)
    strategy = MaterialJacobianCascadeStrategy(
        initial_params={"scene": 0.0, "material": 0.0, "x": 0.0},
        shader_params=[],
        search_param_names=["scene", "material"],
        config={
            "total_max_proposals": 1,
            "stages": [
                {
                    "name": "basin_portfolio",
                    "optimizer": "portfolio",
                    "max_proposals": 1,
                    "frozen_param_names": ["scene"],
                    "portfolio": {"tag": "portfolio"},
                }
            ],
        },
    )

    _candidate, decision = strategy.propose(
        _context({"scene": 0.0, "material": 0.0, "x": 0.0}, 0.8, 0)
    )

    assert len(_FakePortfolio.instances) == 1
    assert _FakePortfolio.instances[0].search_param_names == ["material"]
    assert decision["material_jacobian_cascade"]["optimizer"] == "portfolio"
