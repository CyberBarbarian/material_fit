"""Trust-region state for expensive black-box material search."""

from __future__ import annotations

import math
from typing import Any


class TrustRegionBranch:
    """Manage one local branch without letting global best steer every step.

    The global best remains the final output guard. This branch owns the
    current local search center and adapts its radius from observed trial
    outcomes: improvements move the center and may expand the radius;
    failures shrink the radius and eventually deactivate the branch.
    """

    def __init__(
        self,
        *,
        initial_radius: float = 1.0,
        min_radius: float = 0.18,
        max_radius: float = 1.6,
        expand: float = 1.25,
        shrink: float = 0.55,
        failure_limit: int = 3,
        global_fit_floor: float = 0.05,
    ) -> None:
        self.initial_radius = float(initial_radius)
        self.min_radius = float(min_radius)
        self.max_radius = float(max_radius)
        self.expand = float(expand)
        self.shrink = float(shrink)
        self.failure_limit = max(1, int(failure_limit))
        self.global_fit_floor = max(0.0, float(global_fit_floor))
        self._active = False
        self._center_params: dict[str, Any] = {}
        self._center_fit_score = -math.inf
        self._best_fit_score = -math.inf
        self._radius = self.initial_radius
        self._success_count = 0
        self._failure_count = 0
        self._restart_count = 0
        self._last_outcome = "inactive"

    @property
    def active(self) -> bool:
        return self._active

    @property
    def radius_scale(self) -> float:
        return self._radius if self._active else self.initial_radius

    @property
    def center_params(self) -> dict[str, Any]:
        return dict(self._center_params)

    def ensure(self, *, center_params: dict[str, Any], fit_score: float) -> None:
        if self._active and self._center_params:
            return
        self.restart(center_params=center_params, fit_score=fit_score)

    def restart(self, *, center_params: dict[str, Any], fit_score: float) -> None:
        self._active = True
        self._center_params = dict(center_params)
        self._center_fit_score = float(fit_score) if math.isfinite(float(fit_score)) else -math.inf
        self._best_fit_score = self._center_fit_score
        self._radius = self.initial_radius
        self._success_count = 0
        self._failure_count = 0
        self._restart_count += 1
        self._last_outcome = "restart"

    def can_accept(
        self,
        *,
        fit_score: float,
        global_best_score: float,
    ) -> bool:
        if not self._active:
            return False
        if not math.isfinite(float(fit_score)):
            return False
        if math.isfinite(float(global_best_score)) and fit_score < global_best_score - self.global_fit_floor:
            return False
        return True

    def record_success(self, *, params: dict[str, Any], fit_score: float, min_improvement: float) -> None:
        fit_score = float(fit_score)
        improved_center = fit_score >= self._center_fit_score + max(float(min_improvement), 0.0)
        if improved_center:
            self._center_params = dict(params)
            self._center_fit_score = fit_score
            self._success_count += 1
            self._failure_count = 0
            self._last_outcome = "success"
            if fit_score > self._best_fit_score:
                self._best_fit_score = fit_score
            if self._success_count >= 2:
                self._radius = min(self.max_radius, self._radius * self.expand)
                self._success_count = 0
        else:
            self.record_failure()

    def record_failure(self) -> None:
        if not self._active:
            return
        self._success_count = 0
        self._failure_count += 1
        self._last_outcome = "failure"
        if self._failure_count >= self.failure_limit:
            self._radius *= self.shrink
            self._failure_count = 0
            self._last_outcome = "shrink"
        if self._radius < self.min_radius:
            self._active = False
            self._last_outcome = "deactivated_radius_too_small"

    def summary(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "radius": self._radius,
            "min_radius": self.min_radius,
            "max_radius": self.max_radius,
            "center_fit_score": self._center_fit_score if math.isfinite(self._center_fit_score) else None,
            "best_fit_score": self._best_fit_score if math.isfinite(self._best_fit_score) else None,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "restart_count": self._restart_count,
            "last_outcome": self._last_outcome,
        }


__all__ = ["TrustRegionBranch"]
