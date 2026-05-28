"""Global-best-centered response search optimizer.

This strategy is intentionally smaller than the older semantic scheduler:
every trial is generated from the best-known parameter set, while observed
responses decide which parameter receives the next evaluation budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .candidate_builder import CandidateBuilder, diff_params
from .cma_es_optimizer import ParameterEncoder
from .semantic_graph import ShaderEffectGraph


@dataclass
class _ParamEvidence:
    attempts: int = 0
    positive_attempts: int = 0
    no_effect_attempts: int = 0
    best_delta: float = -math.inf
    total_delta: float = 0.0
    last_delta: float = 0.0
    best_direction: float = 1.0
    direction_balance: float = 0.0
    metric_delta_sum: dict[str, float] = field(default_factory=dict)

    @property
    def mean_delta(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.total_delta / float(self.attempts)

    @property
    def stable_direction(self) -> float:
        if abs(self.direction_balance) < 1.0e-9:
            return self.best_direction
        return 1.0 if self.direction_balance >= 0.0 else -1.0


@dataclass
class _PendingTrial:
    action: str
    params: list[str]
    directions: dict[str, float]
    base_fit_score: float
    base_metrics: dict[str, float]
    center_fit_score: float
    step_scale: float


class AdaptiveResponseSearchStrategy:
    """Evidence-driven optimizer that always searches around global best."""

    name = "adaptive_response_search"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        graph: ShaderEffectGraph,
        auto_adjust_mode: str = "fresh_fit",
    ) -> None:
        self._initial_params = dict(initial_params)
        self._shader_params = list(shader_params)
        self._graph = graph
        self._builder = CandidateBuilder(
            graph=graph,
            shader_params=shader_params,
            encoder_cls=ParameterEncoder,
            step_schedule=[0.16, 0.10, 0.065, 0.04, 0.025],
        )
        self._auto_adjust_mode = (auto_adjust_mode or "fresh_fit").strip().lower()
        self._pending: _PendingTrial | None = None
        self._evidence: dict[str, _ParamEvidence] = {}
        self._best_params = dict(initial_params)
        self._best_fit_score = -math.inf
        self._best_metrics: dict[str, float] = {}
        self._last_response: dict[str, Any] | None = None
        self._trial_count = 0
        self._baseline_recorded = False
        self._pair_interval = 14
        self._min_probe_attempts = 2
        self._axis_expansion_interval = 9
        self._interaction_probe_interval = 17
        self._no_effect_epsilon = 2.0e-4

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return None

    def research_summary(self) -> dict[str, Any]:
        return {
            "phase": "adaptive_response_search",
            "best_fit_score": self._best_score_json(),
            "trial_count": self._trial_count,
            "param_count": len(self._evidence),
            "top_params": self._ranked_param_rows([])[:8],
            "last_response": self._last_response,
        }

    def propose(self, ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        current_metrics = self._metric_components(ctx.analysis)
        self._observe_best(ctx, current_metrics)
        active_params = self._active_params(self._best_params or ctx.current_params)
        self._consume_pending(ctx)
        center = self._center_params(ctx.current_params)
        center_metrics = self._center_metrics(current_metrics)
        center_fit = self._center_fit_score(ctx)

        if not self._baseline_recorded and self._pending is None and ctx.iteration == 0:
            self._baseline_recorded = True
            return center, {
                "optimizer": self.name,
                "stage": {
                    "name": "adaptive_response_search",
                    "description": "baseline evaluation only; no parameter change",
                },
                "semantic_action": "baseline_evaluation",
                "changes": [],
                "stop_reason": "continue",
                "adaptive_response_search": {
                    **self._diagnostics(active_params, None),
                    "baseline_evaluation_only": True,
                    "center_fit_score": center_fit,
                    "center_metrics": center_metrics,
                },
            }

        trial = self._select_trial(active_params, ctx.iteration)
        if trial is None:
            return center, {
                "optimizer": self.name,
                "stage": None,
                "semantic_action": "no_active_params",
                "changes": [],
                "stop_reason": "no_active_params",
                "adaptive_response_search": self._diagnostics(active_params, None),
            }

        proposed, payload = self._build_trial_candidate(center, trial)
        if proposed is None:
            self._mark_no_effect(trial["params"])
            return center, {
                "optimizer": self.name,
                "stage": None,
                "semantic_action": "no_effective_change",
                "changes": [],
                "stop_reason": "no_effective_change",
                "adaptive_response_search": self._diagnostics(active_params, trial),
            }

        params = [str(name) for name in payload.get("changed_params", trial["params"])]
        directions = {
            name: float(trial["directions"].get(name, 1.0))
            for name in params
        }
        self._pending = _PendingTrial(
            action=str(trial["action"]),
            params=params,
            directions=directions,
            base_fit_score=center_fit,
            base_metrics=center_metrics,
            center_fit_score=center_fit,
            step_scale=float(trial["step_scale"]),
        )
        self._trial_count += 1
        changes = diff_params(ctx.current_params, proposed)
        return proposed, {
            "optimizer": self.name,
            "stage": {
                "name": "adaptive_response_search",
                "description": "global-best-centered response evidence search",
            },
            "semantic_action": str(trial["action"]),
            "changes": changes,
            "stop_reason": "continue" if changes else "no_effective_change",
            "adaptive_response_search": self._diagnostics(active_params, trial),
        }

    def _observe_best(self, ctx: Any, current_metrics: dict[str, float]) -> None:
        state_obj = getattr(ctx, "state", None)
        best_params = (
            getattr(state_obj, "best_fit_params", None)
            or getattr(state_obj, "best_params", None)
        )
        best_score = getattr(state_obj, "best_fit_score", None)
        current_fit = getattr(ctx, "fit_score", None)
        if (
            isinstance(best_params, dict)
            and isinstance(best_score, (int, float))
            and math.isfinite(float(best_score))
        ):
            if float(best_score) >= self._best_fit_score:
                self._best_fit_score = float(best_score)
                self._best_params = dict(best_params)
                if (
                    isinstance(current_fit, (int, float))
                    and math.isfinite(float(current_fit))
                    and math.isclose(float(best_score), float(current_fit), abs_tol=1.0e-9)
                ):
                    self._best_metrics = dict(current_metrics)
            return
        if isinstance(current_fit, (int, float)) and math.isfinite(float(current_fit)):
            if float(current_fit) >= self._best_fit_score:
                self._best_fit_score = float(current_fit)
                self._best_params = dict(getattr(ctx, "current_params", {}) or {})
                self._best_metrics = dict(current_metrics)

    def _consume_pending(self, ctx: Any) -> None:
        if self._pending is None:
            return
        pending = self._pending
        self._pending = None
        fit_score = float(getattr(ctx, "fit_score", 0.0) or 0.0)
        delta = fit_score - pending.base_fit_score
        metric_delta = self._metric_delta(pending.base_metrics, self._metric_components(ctx.analysis))
        for name in pending.params:
            ev = self._evidence.setdefault(name, _ParamEvidence())
            direction = float(pending.directions.get(name, 1.0) or 1.0)
            ev.attempts += 1
            ev.total_delta += delta
            ev.last_delta = delta
            if abs(delta) < self._no_effect_epsilon:
                ev.no_effect_attempts += 1
            if delta > self._no_effect_epsilon:
                ev.positive_attempts += 1
                ev.direction_balance += direction
                if delta > ev.best_delta:
                    ev.best_delta = delta
                    ev.best_direction = direction
            for key, value in metric_delta.items():
                ev.metric_delta_sum[key] = ev.metric_delta_sum.get(key, 0.0) + value
        self._last_response = {
            "action": pending.action,
            "params": list(pending.params),
            "fit_score": fit_score,
            "base_fit_score": pending.base_fit_score,
            "center_fit_score": pending.center_fit_score,
            "delta": delta,
            "metric_delta": metric_delta,
            "accepted_by_score": delta > self._no_effect_epsilon,
        }

    def _select_trial(
        self,
        active_params: Sequence[str],
        iteration: int,
    ) -> dict[str, Any] | None:
        if not active_params:
            return None
        calibration = self._least_probed_param(active_params)
        if calibration is not None:
            ev = self._evidence.setdefault(calibration, _ParamEvidence())
            direction = 1.0 if ev.attempts % 2 == 0 else -1.0
            return {
                "action": "calibration_probe",
                "params": [calibration],
                "directions": {calibration: direction},
                "axis_offsets": {calibration: 0},
                "step_scale": 1.0,
                "reason": "ensure every active param has +/- response evidence",
            }
        ranked = self._ranked_param_rows(active_params)
        positive = [row for row in ranked if float(row["score"]) > 0.0]
        axis_expansion = self._axis_expansion_param(active_params, iteration)
        if axis_expansion is not None:
            name = axis_expansion
            ev = self._evidence.setdefault(name, _ParamEvidence())
            direction = 1.0 if ev.attempts % 2 == 0 else -1.0
            return {
                "action": "axis_expansion_probe",
                "params": [name],
                "directions": {name: direction},
                "axis_offsets": {name: self._next_axis_offset(name)},
                "step_scale": 0.75,
                "reason": "low-frequency axis coverage for vector/color params",
            }
        interaction = self._interaction_probe_params(active_params, positive, iteration)
        if interaction is not None:
            return {
                "action": "interaction_probe",
                "params": interaction,
                "directions": {
                    name: self._evidence[name].stable_direction
                    for name in interaction
                },
                "axis_offsets": {
                    name: self._next_axis_offset(name)
                    for name in interaction
                },
                "step_scale": 0.42,
                "reason": "bounded pair probe to test local-optimum interactions",
            }
        if (
            len(positive) >= 2
            and iteration > 0
            and iteration % self._pair_interval == self._pair_interval - 1
        ):
            names = [str(positive[0]["param"]), str(positive[1]["param"])]
            return {
                "action": "evidence_pair_probe",
                "params": names,
                "directions": {
                    name: self._evidence[name].stable_direction
                    for name in names
                },
                "axis_offsets": {
                    name: self._next_axis_offset(name)
                    for name in names
                },
                "step_scale": 0.55,
                "reason": "combine top independently useful params from response evidence",
            }
        if positive:
            name = str(positive[0]["param"])
            ev = self._evidence.setdefault(name, _ParamEvidence())
            return {
                "action": "exploit_param",
                "params": [name],
                "directions": {name: ev.stable_direction},
                "axis_offsets": {name: self._next_axis_offset(name)},
                "step_scale": self._exploit_step_scale(ev),
                "reason": "allocate budget to strongest response evidence",
            }
        name = min(
            active_params,
            key=lambda item: (
                self._evidence.setdefault(item, _ParamEvidence()).attempts,
                item,
            ),
        )
        return {
            "action": "low_confidence_probe",
            "params": [name],
            "directions": {name: self._evidence[name].stable_direction * -1.0},
            "axis_offsets": {name: self._next_axis_offset(name)},
            "step_scale": 0.45,
            "reason": "no proven positive response yet; rotate low-confidence probes",
        }

    def _build_trial_candidate(
        self,
        center: dict[str, Any],
        trial: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        params = [str(name) for name in trial["params"]]
        if len(params) >= 2:
            rows = [
                {
                    "param": name,
                    "axis_offset": int(trial.get("axis_offsets", {}).get(name, 0) or 0),
                }
                for name in params
            ]
            directions = [float(trial["directions"].get(name, 1.0)) for name in params]
            result = self._builder.build_subspace_candidate(
                base_params=center,
                param_rows=rows,
                directions=directions,
                group_cycle=0,
                step_scale=float(trial["step_scale"]),
            )
            if result is not None:
                return result
        name = params[0]
        result = self._builder.nudge_param_candidate(
            base_params=center,
            param_name=name,
            step_scale=float(trial["step_scale"]),
            group_cycle=0,
            axis_offset=int(trial.get("axis_offsets", {}).get(name, 0) or 0),
            direction_override=float(trial["directions"].get(name, 1.0)),
        )
        if result is None:
            return None, {"changed_params": []}
        return result

    def _active_params(self, params: dict[str, Any]) -> list[str]:
        active = [
            name for name in self._graph.active_search_params_for(params)
            if name in params
        ]
        activation = [
            str(row.get("param"))
            for row in self._graph.activation_params_for(params)
            if isinstance(row, dict) and row.get("param") in params
        ]
        merged = list(dict.fromkeys([*active, *activation]))
        return [name for name in merged if self._can_encode_param(params, name)]

    def _can_encode_param(self, params: dict[str, Any], name: str) -> bool:
        encoder = ParameterEncoder(
            params,
            self._shader_params,
            param_whitelist=[name],
            semantics=self._graph,
        )
        return encoder.dim > 0

    def _least_probed_param(self, active_params: Sequence[str]) -> str | None:
        candidates = [
            name for name in active_params
            if self._evidence.setdefault(name, _ParamEvidence()).attempts < self._min_probe_attempts
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda name: (
                self._evidence[name].attempts,
                self._semantic_cold_start_penalty(name),
                name,
            ),
        )

    def _ranked_param_rows(self, active_params: Sequence[str]) -> list[dict[str, Any]]:
        names = list(active_params) if active_params else list(self._evidence)
        rows = []
        for name in names:
            ev = self._evidence.setdefault(name, _ParamEvidence())
            best_delta = ev.best_delta if math.isfinite(ev.best_delta) else 0.0
            score = (
                best_delta * 8.0
                + max(ev.mean_delta, 0.0) * 3.0
                + ev.positive_attempts * 0.03
                - ev.no_effect_attempts * 0.04
                - ev.attempts * 0.004
                - self._semantic_cold_start_penalty(name) * 0.002
            )
            rows.append({
                "param": name,
                "score": score,
                "attempts": ev.attempts,
                "positive_attempts": ev.positive_attempts,
                "best_delta": best_delta,
                "mean_delta": ev.mean_delta,
                "direction": ev.stable_direction,
            })
        rows.sort(key=lambda row: float(row["score"]), reverse=True)
        return rows

    def _semantic_cold_start_penalty(self, name: str) -> float:
        sem = self._graph.params.get(name)
        group = str(getattr(sem, "group", "") if sem is not None else "")
        order = 0
        graph_group = self._graph.groups.get(group)
        if graph_group is not None:
            order = int(getattr(graph_group, "order", 0) or 0)
        return float(order)

    def _required_probe_attempts(self, name: str) -> int:
        axis_count = self._axis_count(self._center_params(self._initial_params), name)
        return max(self._min_probe_attempts, min(axis_count * 2, 8))

    def _axis_expansion_param(
        self,
        active_params: Sequence[str],
        iteration: int,
    ) -> str | None:
        if iteration <= 0 or iteration % self._axis_expansion_interval != 0:
            return None
        candidates = [
            name for name in active_params
            if self._axis_count(self._center_params(self._initial_params), name) > 1
            and self._evidence.setdefault(name, _ParamEvidence()).attempts < self._required_probe_attempts(name)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda name: (self._evidence[name].attempts, name))

    def _interaction_probe_params(
        self,
        active_params: Sequence[str],
        positive_rows: Sequence[dict[str, Any]],
        iteration: int,
    ) -> list[str] | None:
        if iteration <= 0 or iteration % self._interaction_probe_interval != 0:
            return None
        if len(active_params) < 2:
            return None
        if len(positive_rows) >= 2:
            return None
        ranked = self._ranked_param_rows(active_params)
        names = [
            str(row["param"]) for row in ranked
            if self._evidence.setdefault(str(row["param"]), _ParamEvidence()).attempts > 0
        ]
        if len(names) < 2:
            names = list(active_params)
        return names[:2] if len(names) >= 2 else None

    def _next_axis_offset(self, name: str) -> int:
        ev = self._evidence.setdefault(name, _ParamEvidence())
        axis_count = self._axis_count(self._center_params(self._initial_params), name)
        return int(ev.attempts // 2) % max(axis_count, 1)

    def _axis_count(self, params: dict[str, Any], name: str) -> int:
        encoder = ParameterEncoder(
            params,
            self._shader_params,
            param_whitelist=[name],
            semantics=self._graph,
        )
        return max(encoder.dim, 1)

    def _exploit_step_scale(self, ev: _ParamEvidence) -> float:
        if ev.positive_attempts >= 3:
            return 0.38
        if ev.no_effect_attempts >= 2:
            return 0.75
        return 0.65

    def _mark_no_effect(self, params: Sequence[str]) -> None:
        for name in params:
            ev = self._evidence.setdefault(str(name), _ParamEvidence())
            ev.attempts += 1
            ev.no_effect_attempts += 1

    def _center_params(self, fallback: dict[str, Any]) -> dict[str, Any]:
        if self._best_params:
            return dict(self._best_params)
        return dict(fallback)

    def _center_metrics(self, fallback: dict[str, float]) -> dict[str, float]:
        if self._best_metrics:
            return dict(self._best_metrics)
        return dict(fallback)

    def _center_fit_score(self, ctx: Any) -> float:
        if math.isfinite(self._best_fit_score):
            return self._best_fit_score
        fit_score = getattr(ctx, "fit_score", None)
        if isinstance(fit_score, (int, float)) and math.isfinite(float(fit_score)):
            return float(fit_score)
        return -math.inf

    @staticmethod
    def _metric_components(analysis: dict[str, Any]) -> dict[str, float]:
        metrics = analysis.get("research_metrics") if isinstance(analysis, dict) else None
        components = metrics.get("components") if isinstance(metrics, dict) else None
        if not isinstance(components, dict):
            return {}
        out: dict[str, float] = {}
        for key, value in components.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                number = float(value)
                if math.isfinite(number):
                    out[str(key)] = number
        return out

    @staticmethod
    def _metric_delta(
        before: dict[str, float],
        after: dict[str, float],
    ) -> dict[str, float]:
        keys = set(before) | set(after)
        return {
            key: float(after.get(key, 0.0)) - float(before.get(key, 0.0))
            for key in keys
        }

    def _diagnostics(
        self,
        active_params: Sequence[str],
        trial: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "active_param_count": len(active_params),
            "best_fit_score": self._best_score_json(),
            "center": "global_best",
            "trial_count": self._trial_count,
            "selected_trial": trial,
            "top_params": self._ranked_param_rows(active_params)[:8],
            "last_response": self._last_response,
        }

    def _best_score_json(self) -> float | None:
        if math.isfinite(self._best_fit_score):
            return self._best_fit_score
        return None


__all__ = ["AdaptiveResponseSearchStrategy"]
