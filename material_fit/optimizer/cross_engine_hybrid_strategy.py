"""Black-box cross-engine optimizer over the validated fish material subspace."""

from __future__ import annotations

import copy
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .pattern16_strategy import (
    PATTERN16_BOUNDS,
    PATTERN16_INITIAL_STEPS,
    PATTERN16_PARAM_ORDER,
    pattern16_search_param_names,
)
from .strategy_core import OptimizerStrategy, StrategyContext


_DIRECTIONS: tuple[float, float] = (-1.0, 1.0)
_EPS = 1.0e-9


class CrossEngineHybridStrategy(OptimizerStrategy):
    """Response-ranked pattern search using only render-score feedback."""

    name = "cross_engine_hybrid"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None = None,
        fixed_rounds_before_ranking: int = 3,
    ) -> None:
        self._param_names = _cross_engine_param_names(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        self._steps = {name: float(PATTERN16_INITIAL_STEPS[name]) for name in self._param_names}
        self._min_steps = {name: step / 8.0 for name, step in self._steps.items()}
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._fixed_rounds_before_ranking = max(int(fixed_rounds_before_ranking), 1)
        self._fixed_round_index = 1
        self._phase = "calibration"
        self._round_index = 1
        self._param_index = 0
        self._direction_index = 0
        self._agenda: list[str] = list(self._param_names)
        self._local_best_score: float | None = None
        self._local_best_params: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._stop_reason: str | None = None
        self._accept_count = 0
        self._probe_count = 0
        self._shrink_count = 0
        self._response: dict[str, dict[str, Any]] = {
            name: {
                "attempts": 0,
                "best_gain": 0.0,
                "best_direction": None,
                "last_gain": 0.0,
                "success_count": 0,
                "fail_streak": 0,
            }
            for name in self._param_names
        }

    def wants_global_no_improve_check(self) -> bool:
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        previous = self._consume_pending(ctx)
        if self._best_fit_score is None:
            self._best_fit_score = float(ctx.fit_score)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._reset_local_search()
        if not self._param_names:
            self._stop_reason = "cross_engine_hybrid_no_searchable_params"
            return copy.deepcopy(self._best_params), self._stop_decision(previous)

        if self._phase == "calibration":
            return self._next_calibration_candidate(previous)
        if self._phase == "broad_pattern":
            return self._next_broad_candidate(previous)
        return self._next_ranked_candidate(previous)

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def research_summary(self) -> dict[str, Any]:
        return {
            "phase": self._phase,
            "selected_params": list(self._param_names),
            "bounds": {name: list(PATTERN16_BOUNDS[name]) for name in self._param_names},
            "steps": dict(self._steps),
            "min_steps": dict(self._min_steps),
            "round": self._round_index,
            "fixed_round": self._fixed_round_index,
            "fixed_rounds_before_ranking": self._fixed_rounds_before_ranking,
            "agenda": list(self._agenda),
            "response": copy.deepcopy(self._response),
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
        base_score = float(pending.get("base_fit_score", self._best_fit_score or score))
        gain = score - base_score
        param = str(pending.get("param") or "")
        direction = float(pending.get("direction", 0.0) or 0.0)
        response = self._response.get(param)
        if response is not None:
            response["attempts"] = int(response.get("attempts", 0) or 0) + 1
            response["last_gain"] = gain
            if gain > float(response.get("best_gain", 0.0) or 0.0) + _EPS:
                response["best_gain"] = gain
                response["best_direction"] = direction
            if gain > _EPS:
                response["success_count"] = int(response.get("success_count", 0) or 0) + 1
                response["fail_streak"] = 0
            else:
                response["fail_streak"] = int(response.get("fail_streak", 0) or 0) + 1
        improved_local = self._local_best_score is None or score > self._local_best_score + _EPS
        if improved_local:
            self._local_best_score = score
            self._local_best_params = copy.deepcopy(ctx.current_params)
        return {
            "kind": "cross_engine_probe",
            "phase": pending.get("phase"),
            "round": pending.get("round"),
            "param": param,
            "direction": direction,
            "delta": pending.get("delta"),
            "base_fit_score": base_score,
            "score": score,
            "gain": gain,
            "improved_local": improved_local,
            "local_best_score": self._local_best_score,
        }

    def _next_calibration_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._phase == "calibration":
            if self._direction_index < len(_DIRECTIONS):
                param = self._param_names[self._param_index]
                direction = _DIRECTIONS[self._direction_index]
                self._direction_index += 1
                candidate = self._candidate_from_best(param, direction * self._steps[param])
                if _values_equal(candidate.get(param), self._best_params.get(param)):
                    continue
                self._probe_count += 1
                delta = float(candidate[param]) - float(self._best_params[param])
                self._pending = self._pending_record(
                    phase="calibration",
                    param=param,
                    direction=direction,
                    delta=delta,
                )
                return candidate, self._probe_decision(
                    phase="calibration",
                    previous=previous,
                    param=param,
                    direction=direction,
                    delta=delta,
                    candidate=candidate,
                )

            self._finish_param()
            self._param_index += 1
            if self._param_index >= len(self._param_names):
                self._phase = "broad_pattern"
                self._round_index = 1
                self._fixed_round_index = 2
                self._param_index = 0
                self._agenda = list(self._param_names)
                self._reset_local_search()
                break
            self._reset_local_search()

        return self._next_broad_candidate(previous)

    def _next_broad_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._phase == "broad_pattern":
            if self._param_index >= len(self._agenda):
                if self._fixed_round_index < self._fixed_rounds_before_ranking:
                    self._fixed_round_index += 1
                    self._round_index += 1
                    self._param_index = 0
                    self._agenda = list(self._param_names)
                    self._reset_local_search()
                    continue
                self._phase = "ranked_pattern"
                self._round_index = 1
                self._param_index = 0
                self._agenda = self._ranked_agenda()
                self._reset_local_search()
                break
            if self._direction_index < len(_DIRECTIONS):
                param = self._agenda[self._param_index]
                direction = _DIRECTIONS[self._direction_index]
                self._direction_index += 1
                candidate = self._candidate_from_best(param, direction * self._steps[param])
                if _values_equal(candidate.get(param), self._best_params.get(param)):
                    continue
                self._probe_count += 1
                delta = float(candidate[param]) - float(self._best_params[param])
                self._pending = self._pending_record(
                    phase="broad_pattern",
                    param=param,
                    direction=direction,
                    delta=delta,
                )
                return candidate, self._probe_decision(
                    phase="broad_pattern",
                    previous=previous,
                    param=param,
                    direction=direction,
                    delta=delta,
                    candidate=candidate,
                )

            self._finish_param()
            self._param_index += 1
            self._reset_local_search()

        return self._next_ranked_candidate(previous)

    def _next_ranked_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._stop_reason is None:
            if self._param_index >= len(self._agenda):
                self._finish_ranked_round()
                if self._stop_reason:
                    return copy.deepcopy(self._best_params), self._stop_decision(previous)
                continue
            if self._direction_index < len(_DIRECTIONS):
                param = self._agenda[self._param_index]
                direction = self._direction_for_ranked_probe(param, self._direction_index)
                self._direction_index += 1
                candidate = self._candidate_from_best(param, direction * self._steps[param])
                if _values_equal(candidate.get(param), self._best_params.get(param)):
                    continue
                self._probe_count += 1
                delta = float(candidate[param]) - float(self._best_params[param])
                self._pending = self._pending_record(
                    phase="ranked_pattern",
                    param=param,
                    direction=direction,
                    delta=delta,
                )
                return candidate, self._probe_decision(
                    phase="ranked_pattern",
                    previous=previous,
                    param=param,
                    direction=direction,
                    delta=delta,
                    candidate=candidate,
                )

            self._finish_param()
            self._param_index += 1
            self._reset_local_search()

        return copy.deepcopy(self._best_params), self._stop_decision(previous)

    def _finish_param(self) -> bool:
        if self._local_best_score is None or self._best_fit_score is None:
            return False
        if self._local_best_score <= self._best_fit_score + _EPS:
            if self._phase == "ranked_pattern":
                param = self._current_param_name()
                if param is not None:
                    self._shrink_param(param)
            return False
        self._best_fit_score = self._local_best_score
        self._best_params = copy.deepcopy(self._local_best_params or self._best_params)
        self._accept_count += 1
        return True

    def _finish_ranked_round(self) -> None:
        self._agenda = self._ranked_agenda()
        if all(self._steps[name] <= self._min_steps[name] + 1.0e-12 for name in self._param_names):
            self._stop_reason = "cross_engine_hybrid_step_limit"
            return
        self._round_index += 1
        self._param_index = 0
        self._reset_local_search()

    def _reset_local_search(self) -> None:
        self._direction_index = 0
        self._local_best_score = self._best_fit_score
        self._local_best_params = copy.deepcopy(self._best_params)

    def _ranked_agenda(self) -> list[str]:
        rows = []
        for index, name in enumerate(self._param_names):
            response = self._response[name]
            best_gain = float(response.get("best_gain", 0.0) or 0.0)
            last_gain = max(float(response.get("last_gain", 0.0) or 0.0), 0.0)
            fail_streak = int(response.get("fail_streak", 0) or 0)
            priority = best_gain / (1.0 + 0.5 * fail_streak) + 0.35 * last_gain
            rows.append((
                -priority,
                int(response.get("attempts", 0) or 0),
                index,
                name,
            ))
        rows.sort()
        return [name for _, _, _, name in rows]

    def _direction_for_ranked_probe(self, param: str, index: int) -> float:
        best_direction = self._response[param].get("best_direction")
        if best_direction in (-1.0, 1.0):
            return float(best_direction if index == 0 else -best_direction)
        return _DIRECTIONS[index]

    def _current_param_name(self) -> str | None:
        if self._phase == "calibration" and 0 <= self._param_index < len(self._param_names):
            return self._param_names[self._param_index]
        if self._phase == "ranked_pattern" and 0 <= self._param_index < len(self._agenda):
            return self._agenda[self._param_index]
        return None

    def _shrink_param(self, name: str) -> None:
        old = self._steps[name]
        self._steps[name] = max(old * 0.5, self._min_steps[name])
        if self._steps[name] < old - 1.0e-12:
            self._shrink_count += 1

    def _candidate_from_best(self, name: str, delta: float) -> dict[str, Any]:
        candidate = copy.deepcopy(self._best_params)
        candidate[name] = _clamp_param(name, float(candidate[name]) + delta)
        return candidate

    def _pending_record(self, *, phase: str, param: str, direction: float, delta: float) -> dict[str, Any]:
        return {
            "phase": phase,
            "round": self._round_index,
            "param": param,
            "direction": direction,
            "delta": delta,
            "base_fit_score": self._best_fit_score,
        }

    def _probe_decision(
        self,
        *,
        phase: str,
        previous: dict[str, Any] | None,
        param: str,
        direction: float,
        delta: float,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"cross_engine_{phase}_probe",
                "description": "Black-box probe accepted only by Unity/Laya render score",
            },
            "cross_engine_hybrid": {
                "phase": phase,
                "round": self._round_index,
                "fixed_round": self._fixed_round_index,
                "param_index": self._param_index,
                "param": param,
                "direction": direction,
                "delta": delta,
                "step": self._steps[param],
                "bounds": list(PATTERN16_BOUNDS[param]),
                "best_fit_score": self._best_fit_score,
                "agenda": list(self._agenda),
                "response": copy.deepcopy(self._response[param]),
                "previous_candidate": previous,
            },
            "changes": _diff_params(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _stop_decision(self, previous: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None,
            "cross_engine_hybrid": {
                "phase": self._phase,
                "round": self._round_index,
                "fixed_round": self._fixed_round_index,
                "fixed_rounds_before_ranking": self._fixed_rounds_before_ranking,
                "selected_params": list(self._param_names),
                "best_fit_score": self._best_fit_score,
                "accept_count": self._accept_count,
                "probe_count": self._probe_count,
                "shrink_count": self._shrink_count,
                "agenda": list(self._agenda),
                "response": copy.deepcopy(self._response),
                "previous_candidate": previous,
            },
            "changes": [],
            "stop_reason": self._stop_reason or "cross_engine_hybrid_stopped",
        }


def _cross_engine_param_names(
    *,
    initial_params: dict[str, Any],
    shader_params: Sequence[ShaderParam],
    search_param_names: Sequence[str] | None,
) -> list[str]:
    safe_names = pattern16_search_param_names(initial_params, shader_params)
    if search_param_names is None:
        return safe_names
    requested = set(search_param_names)
    return [name for name in safe_names if name in requested]


def _clamp_param(name: str, value: float) -> float:
    low, high = PATTERN16_BOUNDS[name]
    return min(max(float(value), low), high)


def _diff_params(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name in PATTERN16_PARAM_ORDER:
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


__all__ = ["CrossEngineHybridStrategy"]
