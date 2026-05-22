"""Checkpoint drift guard for branch-style material search.

Best-so-far should protect the final output, not steer every accepted step.
This guard only decides when the current branch has drifted too far from a
checkpoint and should be reset.  The thresholds are intentionally wide because
render scores can drop sharply while crossing coupled-parameter valleys.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .search_evidence import MetricVector


@dataclass(frozen=True)
class BranchDriftDecision:
    action: str
    should_rollback: bool
    checkpoint_score: float | None
    fit_score: float
    score_drop: float
    soft_drop_limit: float
    hard_drop_limit: float
    recovery_floor: float
    recent_best_score: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "should_rollback": self.should_rollback,
            "checkpoint_score": self.checkpoint_score,
            "fit_score": self.fit_score,
            "score_drop": self.score_drop,
            "soft_drop_limit": self.soft_drop_limit,
            "hard_drop_limit": self.hard_drop_limit,
            "recovery_floor": self.recovery_floor,
            "recent_best_score": self.recent_best_score,
            "reason": self.reason,
        }


class BranchDriftGuard:
    """Allow valley crossing while preventing runaway branches."""

    def __init__(
        self,
        *,
        recovery_window: int = 28,
        min_soft_drop: float = 0.10,
        soft_drop_ratio: float = 0.18,
        min_hard_drop: float = 0.18,
        hard_drop_ratio: float = 0.28,
        min_recovery_margin: float = 0.06,
        recovery_margin_ratio: float = 0.10,
    ) -> None:
        self.recovery_window = max(4, int(recovery_window))
        self.min_soft_drop = max(0.0, float(min_soft_drop))
        self.soft_drop_ratio = max(0.0, float(soft_drop_ratio))
        self.min_hard_drop = max(0.0, float(min_hard_drop))
        self.hard_drop_ratio = max(0.0, float(hard_drop_ratio))
        self.min_recovery_margin = max(0.0, float(min_recovery_margin))
        self.recovery_margin_ratio = max(0.0, float(recovery_margin_ratio))
        self._checkpoint_params: dict[str, Any] = {}
        self._checkpoint_score = -math.inf
        self._branch_best_score = -math.inf
        self._recent: list[tuple[int, float]] = []
        self._last_decision: BranchDriftDecision | None = None

    @property
    def checkpoint_params(self) -> dict[str, Any]:
        return dict(self._checkpoint_params)

    @property
    def checkpoint_score(self) -> float | None:
        if math.isfinite(self._checkpoint_score):
            return self._checkpoint_score
        return None

    def update_checkpoint(self, *, params: dict[str, Any], fit_score: float) -> None:
        if not math.isfinite(float(fit_score)):
            return
        if not self._checkpoint_params or float(fit_score) >= self._checkpoint_score - 1.0e-9:
            self._checkpoint_params = dict(params)
            self._checkpoint_score = float(fit_score)
            self._branch_best_score = max(self._branch_best_score, float(fit_score))

    def allows_exploration(self, *, fit_score: float) -> bool:
        if not math.isfinite(float(fit_score)):
            return False
        if not math.isfinite(self._checkpoint_score):
            return True
        return self._checkpoint_score - float(fit_score) < self._hard_drop_limit()

    def observe(
        self,
        *,
        iteration: int,
        params: dict[str, Any],
        fit_score: float,
        metrics: MetricVector | None = None,
    ) -> BranchDriftDecision:
        del metrics  # Reserved for future component-level catastrophic guards.
        fit = float(fit_score)
        if not math.isfinite(fit):
            decision = self._decision("hard_drift", True, fit, "non_finite_score")
            self._last_decision = decision
            return decision
        if not math.isfinite(self._checkpoint_score):
            self.update_checkpoint(params=params, fit_score=fit)
        self._branch_best_score = max(self._branch_best_score, fit)
        self._recent.append((int(iteration), fit))
        self._recent = self._recent[-self.recovery_window :]

        hard_limit = self._hard_drop_limit()
        soft_limit = self._soft_drop_limit()
        score_drop = self._checkpoint_score - fit if math.isfinite(self._checkpoint_score) else 0.0
        if score_drop >= hard_limit:
            decision = self._decision("hard_drift", True, fit, "score_below_hard_limit")
        elif self._recovery_failed():
            decision = self._decision("recovery_failed", True, fit, "no_recovery_in_window")
        elif score_drop >= soft_limit:
            decision = self._decision("soft_drift", False, fit, "score_below_soft_limit")
        else:
            decision = self._decision("continue", False, fit, "within_branch_budget")
        self._last_decision = decision
        return decision

    def evaluate_without_record(self, *, fit_score: float) -> BranchDriftDecision:
        return self._decision(
            "hard_drift" if not self.allows_exploration(fit_score=fit_score) else "continue",
            not self.allows_exploration(fit_score=fit_score),
            float(fit_score),
            "base_outside_branch_budget" if not self.allows_exploration(fit_score=fit_score) else "within_branch_budget",
        )

    def summary(self) -> dict[str, Any]:
        recent_best = max((score for _, score in self._recent), default=None)
        return {
            "checkpoint_score": self.checkpoint_score,
            "branch_best_score": self._branch_best_score if math.isfinite(self._branch_best_score) else None,
            "recent_count": len(self._recent),
            "recent_best_score": recent_best,
            "soft_drop_limit": self._soft_drop_limit(),
            "hard_drop_limit": self._hard_drop_limit(),
            "recovery_floor": self._recovery_floor(),
            "last_decision": self._last_decision.to_dict() if self._last_decision else None,
        }

    def _recovery_failed(self) -> bool:
        if len(self._recent) < self.recovery_window:
            return False
        recent_best = max(score for _, score in self._recent)
        return recent_best < self._recovery_floor()

    def _soft_drop_limit(self) -> float:
        if not math.isfinite(self._checkpoint_score):
            return self.min_soft_drop
        return max(self.min_soft_drop, abs(self._checkpoint_score) * self.soft_drop_ratio)

    def _hard_drop_limit(self) -> float:
        if not math.isfinite(self._checkpoint_score):
            return self.min_hard_drop
        return max(self.min_hard_drop, abs(self._checkpoint_score) * self.hard_drop_ratio)

    def _recovery_floor(self) -> float:
        if not math.isfinite(self._checkpoint_score):
            return -math.inf
        margin = max(self.min_recovery_margin, abs(self._checkpoint_score) * self.recovery_margin_ratio)
        return self._checkpoint_score - margin

    def _decision(self, action: str, should_rollback: bool, fit_score: float, reason: str) -> BranchDriftDecision:
        checkpoint = self.checkpoint_score
        recent_best = max((score for _, score in self._recent), default=None)
        score_drop = (float(checkpoint) - float(fit_score)) if checkpoint is not None else 0.0
        return BranchDriftDecision(
            action=action,
            should_rollback=should_rollback,
            checkpoint_score=checkpoint,
            fit_score=float(fit_score),
            score_drop=score_drop,
            soft_drop_limit=self._soft_drop_limit(),
            hard_drop_limit=self._hard_drop_limit(),
            recovery_floor=self._recovery_floor(),
            recent_best_score=recent_best,
            reason=reason,
        )


__all__ = ["BranchDriftDecision", "BranchDriftGuard"]
