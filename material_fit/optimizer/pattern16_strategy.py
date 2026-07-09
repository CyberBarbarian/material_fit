"""Deterministic 16-parameter coordinate pattern search.

This strategy is the maintained form of the early fish run that produced the
strong Unity-reference results. It deliberately searches a small, fixed visual
subspace instead of trying to infer a broad semantic graph.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .param_policy import fixed_optimizer_param_reason
from .strategy_core import OptimizerStrategy, StrategyContext


PATTERN16_PARAM_ORDER: tuple[str, ...] = (
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
)

PATTERN16_BOUNDS: dict[str, tuple[float, float]] = {
    "u_GammaPower": (0.8, 4.8),
    "u_Saturation": (0.2, 2.0),
    "u_TexPower": (0.4, 3.2),
    "u_AoPower": (0.0, 1.6),
    "u_EmissionPow": (0.0, 2.0),
    "u_IndirectStrength": (0.0, 2.0),
    "u_NormalScale": (0.0, 2.0),
    "u_ShadowSmoothness": (0.0, 1.0),
    "u_ShadowThreshold1": (0.0, 1.0),
    "u_ShadowThreshold2": (0.0, 1.0),
    "u_SpecularIntensity": (0.0, 2.0),
    "u_SpecularPower": (1.0, 32.0),
    "u_SpecularThreshold": (0.0, 1.0),
    "u_SpecularSmoothness": (0.0, 1.0),
    "u_RimIntensity": (0.0, 3.0),
    "u_RimWidth": (1.0, 8.0),
}

PATTERN16_INITIAL_STEPS: dict[str, float] = {
    "u_GammaPower": 0.35,
    "u_Saturation": 0.20,
    "u_TexPower": 0.35,
    "u_AoPower": 0.20,
    "u_EmissionPow": 0.20,
    "u_IndirectStrength": 0.20,
    "u_NormalScale": 0.20,
    "u_ShadowSmoothness": 0.12,
    "u_ShadowThreshold1": 0.08,
    "u_ShadowThreshold2": 0.08,
    "u_SpecularIntensity": 0.25,
    "u_SpecularPower": 4.0,
    "u_SpecularThreshold": 0.08,
    "u_SpecularSmoothness": 0.10,
    "u_RimIntensity": 0.30,
    "u_RimWidth": 0.60,
}

_DIRECTIONS: tuple[float, float] = (-1.0, 1.0)
_EPS = 1.0e-9


def pattern16_search_param_names(
    params: dict[str, Any],
    shader_params: Sequence[ShaderParam] = (),
) -> list[str]:
    """Return the active Pattern16 params that are safe to search."""

    param_by_name = {param.name: param for param in shader_params}
    names: list[str] = []
    for name in PATTERN16_PARAM_ORDER:
        if name not in params:
            continue
        param = param_by_name.get(name)
        if fixed_optimizer_param_reason(name, param) is not None:
            continue
        value = params.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        names.append(name)
    return names


class Pattern16Strategy(OptimizerStrategy):
    """Coordinate pattern search over the historically validated fish subspace."""

    name = "pattern16"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
    ) -> None:
        self._param_names = pattern16_search_param_names(initial_params, shader_params)
        self._steps = {
            name: float(PATTERN16_INITIAL_STEPS[name])
            for name in self._param_names
        }
        self._min_steps = {name: step / 8.0 for name, step in self._steps.items()}
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._round_index = 0
        self._param_index = 0
        self._direction_index = 0
        self._local_best_score: float | None = None
        self._local_best_params: dict[str, Any] | None = None
        self._local_best_delta = 0.0
        self._improved_any_in_round = False
        self._min_step_shrink_count = 0
        self._pending: dict[str, Any] | None = None
        self._stop_reason: str | None = None
        self._accept_count = 0
        self._probe_count = 0
        self._shrink_count = 0

    def wants_global_no_improve_check(self) -> bool:
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        previous = self._consume_pending(ctx)
        if self._best_fit_score is None:
            self._best_fit_score = float(ctx.fit_score)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._round_index = 1
            self._reset_local_search()

        candidate, decision = self._next_candidate(previous)
        return candidate, decision

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def research_summary(self) -> dict[str, Any]:
        return {
            "phase": "coordinate_pattern_search_blackbox_16d",
            "selected_params": list(self._param_names),
            "bounds": {name: list(PATTERN16_BOUNDS[name]) for name in self._param_names},
            "steps": dict(self._steps),
            "min_steps": dict(self._min_steps),
            "round": self._round_index,
            "accept_count": self._accept_count,
            "probe_count": self._probe_count,
            "shrink_count": self._shrink_count,
            "best_fit_score": self._best_fit_score,
            "stop_reason": self._stop_reason,
        }

    def _consume_pending(self, ctx: StrategyContext) -> dict[str, Any] | None:
        if self._pending is None:
            return None
        pending = self._pending
        self._pending = None
        score = float(ctx.fit_score)
        local_score = self._local_best_score
        improved_local = local_score is None or score > local_score + _EPS
        if improved_local:
            self._local_best_score = score
            self._local_best_params = copy.deepcopy(ctx.current_params)
            self._local_best_delta = float(pending.get("delta", 0.0))
        return {
            "kind": "probe",
            "round": pending.get("round"),
            "param": pending.get("param"),
            "direction": pending.get("direction"),
            "delta": pending.get("delta"),
            "score": score,
            "improved_local": improved_local,
            "local_best_score": self._local_best_score,
        }

    def _reset_local_search(self) -> None:
        self._direction_index = 0
        self._local_best_score = self._best_fit_score
        self._local_best_params = copy.deepcopy(self._best_params)
        self._local_best_delta = 0.0

    def _next_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self._param_names:
            self._stop_reason = "pattern16_no_searchable_params"
            return copy.deepcopy(self._best_params), self._stop_decision(previous)

        while self._stop_reason is None:
            if self._direction_index < len(_DIRECTIONS):
                param = self._param_names[self._param_index]
                direction = _DIRECTIONS[self._direction_index]
                self._direction_index += 1
                delta = direction * self._steps[param]
                candidate = self._candidate_from_best(param, delta)
                if _values_equal(candidate.get(param), self._best_params.get(param)):
                    continue
                self._probe_count += 1
                self._pending = {
                    "round": self._round_index,
                    "param": param,
                    "direction": direction,
                    "delta": delta,
                }
                return candidate, self._probe_decision(
                    previous=previous,
                    param=param,
                    direction=direction,
                    delta=delta,
                    candidate=candidate,
                )

            accepted = self._finish_param()
            self._param_index += 1
            if self._param_index >= len(self._param_names):
                self._finish_round()
                if self._stop_reason:
                    return copy.deepcopy(self._best_params), self._stop_decision(previous, accepted=accepted)
            self._reset_local_search()

        return copy.deepcopy(self._best_params), self._stop_decision(previous)

    def _candidate_from_best(self, name: str, delta: float) -> dict[str, Any]:
        candidate = copy.deepcopy(self._best_params)
        candidate[name] = self._clamp_param(name, float(candidate[name]) + delta)
        return candidate

    def _finish_param(self) -> bool:
        if self._local_best_score is None or self._best_fit_score is None:
            return False
        if self._local_best_score <= self._best_fit_score + _EPS:
            return False
        self._best_fit_score = self._local_best_score
        self._best_params = copy.deepcopy(self._local_best_params or self._best_params)
        self._improved_any_in_round = True
        self._min_step_shrink_count = 0
        self._accept_count += 1
        return True

    def _finish_round(self) -> None:
        if self._improved_any_in_round:
            self._round_index += 1
            self._param_index = 0
            self._improved_any_in_round = False
            return

        all_at_min_before = self._all_steps_at_min()
        for name in self._param_names:
            self._steps[name] = max(self._steps[name] * 0.5, self._min_steps[name])
        self._shrink_count += 1
        all_at_min_after = self._all_steps_at_min()
        if all_at_min_after and all_at_min_before:
            self._min_step_shrink_count += 1
        else:
            self._min_step_shrink_count = 0
        if self._min_step_shrink_count >= 1:
            self._stop_reason = "pattern16_step_limit"
            return
        self._round_index += 1
        self._param_index = 0

    def _all_steps_at_min(self) -> bool:
        return all(self._steps[name] <= self._min_steps[name] + 1.0e-12 for name in self._param_names)

    @staticmethod
    def _clamp_param(name: str, value: float) -> float:
        low, high = PATTERN16_BOUNDS[name]
        if not math.isfinite(value):
            return low
        return min(max(float(value), low), high)

    def _probe_decision(
        self,
        *,
        previous: dict[str, Any] | None,
        param: str,
        direction: float,
        delta: float,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "pattern16_coordinate_probe",
                "description": "16D coordinate pattern search over the validated fish material subspace",
            },
            "pattern16": {
                "round": self._round_index,
                "param_index": self._param_index,
                "param": param,
                "direction": direction,
                "delta": delta,
                "step": self._steps[param],
                "bounds": list(PATTERN16_BOUNDS[param]),
                "best_fit_score": self._best_fit_score,
                "local_best_score": self._local_best_score,
                "previous_candidate": previous,
            },
            "changes": _diff_params(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _stop_decision(
        self,
        previous: dict[str, Any] | None,
        *,
        accepted: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None,
            "pattern16": {
                "round": self._round_index,
                "selected_params": list(self._param_names),
                "best_fit_score": self._best_fit_score,
                "accept_count": self._accept_count,
                "probe_count": self._probe_count,
                "shrink_count": self._shrink_count,
                "previous_candidate": previous,
                "accepted_last_param": accepted,
            },
            "changes": [],
            "stop_reason": self._stop_reason or "pattern16_stopped",
        }


def _diff_params(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name in list(PATTERN16_PARAM_ORDER):
        if name not in before and name not in after:
            continue
        old = before.get(name)
        new = after.get(name)
        if _values_equal(old, new):
            continue
        changes.append({"param": name, "before": old, "after": new})
    return changes


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1.0e-12
    return left == right


__all__ = [
    "PATTERN16_BOUNDS",
    "PATTERN16_INITIAL_STEPS",
    "PATTERN16_PARAM_ORDER",
    "Pattern16Strategy",
    "pattern16_search_param_names",
]
