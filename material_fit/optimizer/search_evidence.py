"""Lightweight evidence models for semantic material search.

These classes are intentionally small and dependency-free. They are not
neural networks or full surrogate models; they capture enough trial
history to choose better restart groups and active subspaces without
making :mod:`optimizer.strategy` responsible for all bookkeeping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


_COMPONENT_KEYS = (
    "color_mean",
    "color_p95",
    "luminance_mae",
    "luminance_bias",
    "structure_ssim_l",
    "highlight",
    "detail_texture",
)


@dataclass(frozen=True)
class MetricVector:
    """Compact loss vector used to compare candidate side effects."""

    fit_score: float | None = None
    components: dict[str, float] = field(default_factory=dict)
    worst_fit_score: float | None = None
    worst_view_id: str | None = None

    def bottleneck(self) -> dict[str, float]:
        """Return positive component losses normalized only by presence."""

        return {key: max(value, 0.0) for key, value in self.components.items()}


@dataclass
class TrialEvidence:
    group: str
    kind: str
    fit_delta: float
    component_improvement: dict[str, float]
    accepted: bool
    changed_params: list[str]


class TopKArchive:
    """Keep the best distinct parameter sets seen during one run."""

    def __init__(self, capacity: int = 12) -> None:
        self.capacity = max(1, int(capacity))
        self._items: list[dict[str, Any]] = []

    @property
    def items(self) -> list[dict[str, Any]]:
        return list(self._items)

    def add(
        self,
        *,
        params: dict[str, Any],
        fit_score: float,
        metrics: MetricVector,
        group: str | None = None,
        iteration: int | None = None,
    ) -> None:
        if not math.isfinite(float(fit_score)):
            return
        signature = _param_signature(params)
        item = {
            "fit_score": float(fit_score),
            "params": dict(params),
            "signature": signature,
            "group": group,
            "iteration": iteration,
            "worst_fit_score": metrics.worst_fit_score,
            "worst_view_id": metrics.worst_view_id,
            "components": dict(metrics.components),
        }
        self._items = [old for old in self._items if old.get("signature") != signature]
        self._items.append(item)
        self._items.sort(key=lambda entry: float(entry.get("fit_score", -math.inf)), reverse=True)
        del self._items[self.capacity :]

    def select_restart(
        self,
        *,
        bottleneck: dict[str, float],
        current_params: dict[str, Any],
        min_fit_score: float | None = None,
    ) -> dict[str, Any] | None:
        """Pick a strong archive point that is useful for current bottlenecks."""

        current_signature = _param_signature(current_params)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._items:
            if item.get("signature") == current_signature:
                continue
            fit_score = _finite_float(item.get("fit_score"))
            if fit_score is None or (min_fit_score is not None and fit_score < min_fit_score):
                continue
            complement = _bottleneck_complement_score(
                item.get("components") if isinstance(item.get("components"), dict) else {},
                bottleneck,
            )
            worst_fit = _finite_float(item.get("worst_fit_score"))
            worst_bonus = 0.02 * worst_fit if worst_fit is not None else 0.0
            scored.append((fit_score + 0.25 * complement + worst_bonus, item))
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected = scored[0][1]
        return {
            "params": dict(selected.get("params") or {}),
            "fit_score": selected.get("fit_score"),
            "group": selected.get("group"),
            "iteration": selected.get("iteration"),
            "worst_fit_score": selected.get("worst_fit_score"),
            "worst_view_id": selected.get("worst_view_id"),
            "components": dict(selected.get("components") or {}),
            "restart_score": scored[0][0],
        }

    def summary(self, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "fit_score": item.get("fit_score"),
                "group": item.get("group"),
                "iteration": item.get("iteration"),
                "worst_fit_score": item.get("worst_fit_score"),
                "worst_view_id": item.get("worst_view_id"),
                "components": item.get("components"),
            }
            for item in self._items[: max(0, int(limit))]
        ]


class InfluenceTracker:
    """Online group -> component influence evidence.

    The score is an exponential moving average of observed component loss
    reductions. It is a local evidence layer, not a global causal model.
    """

    def __init__(self, alpha: float = 0.35) -> None:
        self.alpha = max(0.01, min(1.0, float(alpha)))
        self._group_component_ema: dict[str, dict[str, float]] = {}
        self._group_trials: dict[str, int] = {}

    def observe(
        self,
        *,
        group: str,
        kind: str,
        before: MetricVector,
        after: MetricVector,
        fit_delta: float,
        accepted: bool,
        changed_params: list[str],
    ) -> TrialEvidence:
        improvements: dict[str, float] = {}
        keys = set(before.components) | set(after.components)
        for key in keys:
            # Components are losses: lower is better, so improvement is
            # before - after.
            improvements[key] = before.components.get(key, 0.0) - after.components.get(key, 0.0)
        group_ema = self._group_component_ema.setdefault(group, {})
        for key, value in improvements.items():
            old = group_ema.get(key, 0.0)
            group_ema[key] = (1.0 - self.alpha) * old + self.alpha * float(value)
        self._group_trials[group] = self._group_trials.get(group, 0) + 1
        return TrialEvidence(
            group=group,
            kind=kind,
            fit_delta=float(fit_delta),
            component_improvement=improvements,
            accepted=accepted,
            changed_params=list(changed_params),
        )

    def utility_for(self, group: str, bottleneck: dict[str, float]) -> float:
        ema = self._group_component_ema.get(group)
        if not ema:
            return 0.0
        score = 0.0
        for key, need in bottleneck.items():
            if need <= 0.0:
                continue
            # Positive EMA means the group tends to reduce this loss.
            score += max(ema.get(key, 0.0), 0.0) * need
        trials = self._group_trials.get(group, 0)
        # Small exploration bonus keeps under-sampled groups eligible.
        return score + (0.005 / math.sqrt(max(trials, 1)))

    def summary_for(self, group: str, bottleneck: dict[str, float]) -> dict[str, Any]:
        ema = self._group_component_ema.get(group, {})
        return {
            "trials": self._group_trials.get(group, 0),
            "utility": self.utility_for(group, bottleneck),
            "component_ema": dict(ema),
        }

    def summary(self, bottleneck: dict[str, float]) -> dict[str, Any]:
        groups = sorted(set(self._group_component_ema) | set(self._group_trials))
        return {group: self.summary_for(group, bottleneck) for group in groups}

    @property
    def trial_count(self) -> int:
        return sum(self._group_trials.values())


class ParamInfluenceTracker:
    """Bandit-style evidence for choosing individual shader parameters."""

    def __init__(self, alpha: float = 0.35, exploration_weight: float = 0.035) -> None:
        self.alpha = max(0.01, min(1.0, float(alpha)))
        self.exploration_weight = max(0.0, float(exploration_weight))
        self._component_ema: dict[str, dict[str, float]] = {}
        self._attempts: dict[str, int] = {}
        self._accepted: dict[str, int] = {}
        self._fit_gain_ema: dict[str, float] = {}
        self._risk_ema: dict[str, float] = {}
        self._recent_failures: dict[str, int] = {}

    def observe(
        self,
        *,
        changed_params: list[str],
        before: MetricVector,
        after: MetricVector,
        fit_delta: float,
        accepted: bool,
    ) -> None:
        params = sorted({str(item) for item in changed_params if item})
        if not params:
            return
        weight = 1.0 / max(len(params), 1)
        component_improvements = {
            key: before.components.get(key, 0.0) - after.components.get(key, 0.0)
            for key in set(before.components) | set(after.components)
        }
        risk = self._risk(before, after)
        for name in params:
            self._attempts[name] = self._attempts.get(name, 0) + 1
            if accepted:
                self._accepted[name] = self._accepted.get(name, 0) + 1
                self._recent_failures[name] = 0
            else:
                self._recent_failures[name] = self._recent_failures.get(name, 0) + 1
            old_fit = self._fit_gain_ema.get(name, 0.0)
            self._fit_gain_ema[name] = (1.0 - self.alpha) * old_fit + self.alpha * float(fit_delta) * weight
            old_risk = self._risk_ema.get(name, 0.0)
            self._risk_ema[name] = (1.0 - self.alpha) * old_risk + self.alpha * risk * weight
            component_ema = self._component_ema.setdefault(name, {})
            for key, value in component_improvements.items():
                old = component_ema.get(key, 0.0)
                component_ema[key] = (1.0 - self.alpha) * old + self.alpha * float(value) * weight

    def priority_for(
        self,
        param: str,
        bottleneck: dict[str, float],
        *,
        semantic_relevance: float = 0.0,
    ) -> float:
        attempts = self._attempts.get(param, 0)
        gain = max(self._fit_gain_ema.get(param, 0.0), 0.0)
        component_gain = 0.0
        for key, need in bottleneck.items():
            if need <= 0.0:
                continue
            component_gain += max(self._component_ema.get(param, {}).get(key, 0.0), 0.0) * float(need)
        exploration = self.exploration_weight / math.sqrt(attempts + 1.0)
        failure_penalty = 0.010 * self._recent_failures.get(param, 0)
        attempt_penalty = 0.0025 * math.sqrt(attempts)
        risk_penalty = max(self._risk_ema.get(param, 0.0), 0.0)
        return (
            max(float(semantic_relevance), 0.0)
            + gain
            + component_gain
            + exploration
            - failure_penalty
            - attempt_penalty
            - risk_penalty
        )

    def summary_for(self, param: str, bottleneck: dict[str, float], *, semantic_relevance: float = 0.0) -> dict[str, Any]:
        return {
            "attempts": self._attempts.get(param, 0),
            "accepted": self._accepted.get(param, 0),
            "fit_gain_ema": self._fit_gain_ema.get(param, 0.0),
            "risk_ema": self._risk_ema.get(param, 0.0),
            "recent_failures": self._recent_failures.get(param, 0),
            "component_ema": dict(self._component_ema.get(param, {})),
            "semantic_relevance": semantic_relevance,
            "priority": self.priority_for(param, bottleneck, semantic_relevance=semantic_relevance),
        }

    def summary(self, bottleneck: dict[str, float], limit: int = 12) -> list[dict[str, Any]]:
        params = sorted(set(self._attempts) | set(self._component_ema))
        rows = [
            {"param": name, **self.summary_for(name, bottleneck)}
            for name in params
        ]
        rows.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
        return rows[: max(0, int(limit))]

    @staticmethod
    def _risk(before: MetricVector, after: MetricVector) -> float:
        if before.worst_fit_score is None or after.worst_fit_score is None:
            return 0.0
        return max(float(before.worst_fit_score) - float(after.worst_fit_score), 0.0)


def metric_vector_from_analysis(analysis: dict[str, Any] | None, fit_score: float | None = None) -> MetricVector:
    analysis = analysis if isinstance(analysis, dict) else {}
    research = analysis.get("research_metrics") if isinstance(analysis.get("research_metrics"), dict) else {}
    raw_components = research.get("components") if isinstance(research.get("components"), dict) else {}
    components: dict[str, float] = {}
    for key in _COMPONENT_KEYS:
        value = _finite_float(raw_components.get(key))
        if value is not None:
            components[key] = value
    multiview = analysis.get("multiview") if isinstance(analysis.get("multiview"), dict) else {}
    summary = multiview.get("summary") if isinstance(multiview.get("summary"), dict) else {}
    return MetricVector(
        fit_score=_finite_float(fit_score),
        components=components,
        worst_fit_score=_finite_float(summary.get("worst_fit_score")),
        worst_view_id=str(summary.get("worst_view_id")) if summary.get("worst_view_id") else None,
    )


def _finite_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _param_signature(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(params):
        value = params[key]
        if isinstance(value, float):
            encoded = f"{value:.8g}"
        elif isinstance(value, list):
            encoded = "[" + ",".join(f"{item:.8g}" if isinstance(item, float) else str(item) for item in value) + "]"
        else:
            encoded = str(value)
        parts.append(f"{key}={encoded}")
    return "|".join(parts)


def _bottleneck_complement_score(components: dict[str, Any], bottleneck: dict[str, float]) -> float:
    if not bottleneck:
        return 0.0
    score = 0.0
    for key, need in bottleneck.items():
        component_value = _finite_float(components.get(key))
        if component_value is None:
            continue
        # Components are losses, so an archive item with lower loss on
        # the current bottleneck is a better restart base.
        score += max(float(need) - component_value, 0.0) * max(float(need), 0.0)
    return score


__all__ = [
    "InfluenceTracker",
    "MetricVector",
    "ParamInfluenceTracker",
    "TopKArchive",
    "TrialEvidence",
    "metric_vector_from_analysis",
]
