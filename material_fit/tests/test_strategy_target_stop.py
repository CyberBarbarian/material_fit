from __future__ import annotations

from material_fit.fit_material import _strategy_target_stop_decision
from material_fit.optimizer.strategy_core import OptimizerStrategy


class _DeferredStrategy(OptimizerStrategy):
    name = "deferred"

    def propose(self, ctx):
        return ctx.current_params, {}

    def allows_target_distance_stop(self) -> bool:
        return False


class _DefaultStrategy(OptimizerStrategy):
    name = "default"

    def propose(self, ctx):
        return ctx.current_params, {}


def test_strategy_can_defer_a_target_score_stop() -> None:
    stop, deferred = _strategy_target_stop_decision(
        _DeferredStrategy(),
        0.99,
        target_score=0.98,
        score_ceiling=None,
    )

    assert stop is None
    assert deferred == "target_reached"


def test_default_strategy_still_stops_at_target_score() -> None:
    stop, deferred = _strategy_target_stop_decision(
        _DefaultStrategy(),
        0.99,
        target_score=0.98,
        score_ceiling=None,
    )

    assert stop == "target_reached"
    assert deferred is None
