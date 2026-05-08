"""Regression tests for stage progression in ``adjustment_algorithm``.

Background: the user observed a 12-iteration auto-adjust run that stayed
on ``base_color`` for *every* iteration, only ever changing ``u_BaseColor``
and ``u_Gamma_Power``. Root cause was that ``choose_stage`` ignored
``policy.max_iterations`` and had no stuck detection, so once a stage's
channel score refused to drop below ``target_score`` the algorithm would
grind on it forever instead of advancing through the coarse-to-fine plan.

These tests pin down the new contract:

* ``max_iterations`` is honoured.
* Stages are skipped when they're already converged.
* "Stuck on a stage" (no improvement) advances after a small budget.
* After exhausting all stages we cycle back for a refinement pass.
* Global stagnation eventually trips ``should_abort_global``.

Run with:

    python -m pytest tools/material_fit/tests/test_stage_progression.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.material_fit.optimizer.adjustment_algorithm import (  # noqa: E402
    GLOBAL_NO_IMPROVE_LIMIT,
    STUCK_NO_IMPROVE_LIMIT,
    AdjustmentState,
    AdjustmentStagePolicy,
    choose_stage,
    should_abort_global,
    update_stage_progress,
)


def _stage(name: str, channel: str, params: list[str], *, max_iter: int = 3, target: float = 0.05) -> AdjustmentStagePolicy:
    return AdjustmentStagePolicy(
        name=name,
        description=name,
        channels=[channel],
        params=params,
        max_iterations=max_iter,
        target_score=target,
    )


def _analysis(channel_scores: dict[str, float]) -> dict:
    return {
        "material_channels": {
            name: {"rgb_mae": value} for name, value in channel_scores.items()
        }
    }


@pytest.fixture
def policies() -> list[AdjustmentStagePolicy]:
    return [
        _stage("base_color", "ch_a", ["u_BaseColor"], max_iter=3, target=0.05),
        _stage("specular", "ch_b", ["u_Specular"], max_iter=2, target=0.05),
        _stage("matcap", "ch_c", ["u_Matcap"], max_iter=2, target=0.05),
    ]


def _simulate_iter(policies, state, channel_score, *, post_score=None):
    """One simulated iteration: choose, then mark progress with the
    post-render channel score so stage_no_improve / stage_iteration update.
    Returns the chosen policy and its choose_stage info."""
    if post_score is None:
        post_score = channel_score
    policy, info = choose_stage(policies, _analysis(channel_score), state)
    if policy is not None:
        update_stage_progress(state, policy, _analysis(post_score))
    return policy, info


def test_advances_after_max_iterations(policies):
    """The smoking-gun bug: keep base_color score WAY above target forever
    and confirm we still advance to specular after max_iterations=3."""
    state = AdjustmentState()
    visited = []
    for _ in range(6):
        # ch_a is always 0.30 — far above the 0.05 target.
        policy, _info = _simulate_iter(policies, state, {"ch_a": 0.30, "ch_b": 0.10, "ch_c": 0.10})
        visited.append(policy.name)
    # First 3 iters must be base_color; then specular (max_iter=2); then matcap.
    assert visited[:3] == ["base_color"] * 3, f"unexpected: {visited}"
    assert "specular" in visited[3:5], (
        f"specular never reached after exhausting base_color: {visited}"
    )
    assert visited[-1] in {"matcap", "base_color"}, f"unexpected last stage: {visited}"


def test_advances_when_stuck_no_improvement(policies):
    """Channel score is below max_iterations cap budget but not improving —
    stuck detection should still advance us once stage_iteration >= 2."""
    state = AdjustmentState()
    # base_color has max_iter=3 but stuck for 2 iters with no improvement.
    # Note: STUCK_NO_IMPROVE_LIMIT is 2, requires stage_iteration >= 2.
    visited = []
    for _ in range(5):
        policy, _info = _simulate_iter(policies, state, {"ch_a": 0.20, "ch_b": 0.20, "ch_c": 0.20})
        visited.append(policy.name)
    # Either max_iter=3 or stuck-after-2 — either way advancing past
    # base_color must happen by iteration 4 at the latest.
    assert visited[:3] == ["base_color"] * 3
    assert visited[3] != "base_color", f"didn't advance off stuck base_color: {visited}"


def test_skips_already_converged_stage(policies):
    state = AdjustmentState()
    # ch_a is already below target (0.04 < 0.05) — base_color must be skipped
    # without burning an iteration on it.
    policy, info = _simulate_iter(policies, state, {"ch_a": 0.04, "ch_b": 0.20, "ch_c": 0.20})
    assert policy.name == "specular", f"didn't skip converged base_color: {policy.name}"
    transitions = info["transitions"]
    assert any(t.get("event") == "skip" and t.get("from_stage") == "base_color"
               for t in transitions), f"missing skip transition: {transitions}"


def test_advances_when_target_reached_mid_stage(policies):
    state = AdjustmentState()
    # First iter: above target → work base_color.
    policy, _ = _simulate_iter(policies, state, {"ch_a": 0.30, "ch_b": 0.20, "ch_c": 0.20})
    assert policy.name == "base_color"
    # Second iter: now below target → advance.
    policy, info = _simulate_iter(policies, state, {"ch_a": 0.04, "ch_b": 0.20, "ch_c": 0.20})
    assert policy.name == "specular"
    transitions = info["transitions"]
    assert any(t.get("reason") == "target_reached" for t in transitions), (
        f"missing target_reached transition: {transitions}"
    )


def test_cycle_restart_after_all_stages_exhausted(policies):
    """After all stages have been visited and not converged, we should
    cycle back to stage 0 for a refinement pass."""
    state = AdjustmentState()
    # Run enough iterations to exhaust all stages.
    visited = []
    for _ in range(20):
        policy, _info = _simulate_iter(policies, state, {"ch_a": 0.20, "ch_b": 0.20, "ch_c": 0.20})
        visited.append(policy.name)
    assert state.cycle >= 1, (
        f"never cycled after 20 iters across {len(policies)} stages: cycle={state.cycle}, visited={visited}"
    )


def test_stage_progress_tracks_improvement(policies):
    state = AdjustmentState()
    policy, _ = _simulate_iter(policies, state, {"ch_a": 0.30, "ch_b": 0.20, "ch_c": 0.20}, post_score={"ch_a": 0.25, "ch_b": 0.20, "ch_c": 0.20})
    assert state.stage_iteration == 1
    assert state.stage_no_improve == 0
    assert math.isclose(state.stage_best_score, 0.25, rel_tol=1e-9)
    # Now degrade.
    _simulate_iter(policies, state, {"ch_a": 0.25, "ch_b": 0.20, "ch_c": 0.20}, post_score={"ch_a": 0.27, "ch_b": 0.20, "ch_c": 0.20})
    assert state.stage_no_improve == 1, "no_improve must increment when score regresses"
    # Improve again.
    _simulate_iter(policies, state, {"ch_a": 0.27, "ch_b": 0.20, "ch_c": 0.20}, post_score={"ch_a": 0.20, "ch_b": 0.20, "ch_c": 0.20})
    assert state.stage_no_improve == 0, "no_improve must reset on improvement"


def test_stage_counters_reset_on_advance(policies):
    state = AdjustmentState()
    # Burn 3 iters on base_color (max_iter=3) → next call advances.
    for _ in range(3):
        _simulate_iter(policies, state, {"ch_a": 0.30, "ch_b": 0.20, "ch_c": 0.20})
    assert state.stage_iteration == 3
    # The 4th call must advance off base_color and reset counters.
    policy, info = _simulate_iter(policies, state, {"ch_a": 0.30, "ch_b": 0.20, "ch_c": 0.20})
    assert policy.name == "specular", f"didn't advance off base_color: {policy.name}"
    # After advancing, state should reflect stage 1 with one iter spent on it.
    assert state.stage_index == 1
    # update_stage_progress incremented stage_iteration to 1 for specular.
    assert state.stage_iteration == 1
    assert any(t.get("reason") == "max_iterations_exhausted" for t in info["transitions"])


def test_should_abort_global():
    state = AdjustmentState()
    state.global_no_improve = GLOBAL_NO_IMPROVE_LIMIT - 1
    assert not should_abort_global(state)
    state.global_no_improve = GLOBAL_NO_IMPROVE_LIMIT
    assert should_abort_global(state)


def test_choose_stage_returns_tuple_and_info(policies):
    """API contract: choose_stage now returns ``(policy, info_dict)`` so
    callers can persist transition reasons into decision.json."""
    state = AdjustmentState()
    policy, info = choose_stage(policies, _analysis({"ch_a": 0.30, "ch_b": 0.20, "ch_c": 0.20}), state)
    assert policy is not None
    assert isinstance(info, dict)
    for key in ("transitions", "selected", "stage_iteration", "cycle"):
        assert key in info, f"missing key {key} in choose_stage info"
    assert info["selected"] == policy.name


def test_empty_policies_returns_none():
    state = AdjustmentState()
    policy, info = choose_stage([], _analysis({}), state)
    assert policy is None
    assert info["transitions"] == []
