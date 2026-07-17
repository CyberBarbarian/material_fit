"""SPSA/Adam optimizer for coupled fish material coordinates."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

import numpy as np

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_space import FishSearchCoordinate, structured_fish_coordinates


class FishSpsaStrategy(OptimizerStrategy):
    """Estimate a joint black-box gradient with antithetic SPSA probes."""

    name = "fish_spsa"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        self._coordinates = structured_fish_coordinates(
            initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        if not self._coordinates:
            raise ValueError("fish_spsa has no searchable structured fish coordinates")
        self._base_params = copy.deepcopy(initial_params)
        self._center = self._encode(initial_params)
        self._center_fit = -math.inf
        self._rng = np.random.default_rng(int(cfg.get("seed", 20260713)))
        self._perturbation_scale = _positive_float(cfg.get("perturbation_scale"), 0.05)
        self._learning_rate = _positive_float(cfg.get("learning_rate"), 0.12)
        self._alpha = _positive_float(cfg.get("learning_rate_exponent"), 0.602)
        self._gamma = _positive_float(cfg.get("perturbation_exponent"), 0.101)
        self._stability = max(float(cfg.get("stability_constant", 10.0) or 10.0), 0.0)
        self._beta1 = _unit_interval(cfg.get("beta1"), 0.9)
        self._beta2 = _unit_interval(cfg.get("beta2"), 0.999)
        self._epsilon = _positive_float(cfg.get("epsilon"), 1e-8)
        self._reject_patience = max(int(cfg.get("reject_patience", 8) or 8), 1)
        self._reject_decay = min(max(float(cfg.get("reject_decay", 0.5) or 0.5), 0.1), 1.0)
        self._directions_per_update = max(int(cfg.get("directions_per_update", 8) or 8), 1)
        self._momentum = np.zeros(len(self._coordinates), dtype=np.float64)
        self._variance = np.zeros(len(self._coordinates), dtype=np.float64)
        self._step = 0
        self._rejection_streak = 0
        self._learning_rate_multiplier = 1.0
        self._last_role: str | None = None
        self._delta: np.ndarray | None = None
        self._plus_loss: float | None = None
        self._cycle_center: np.ndarray | None = None
        self._cycle_c = 0.0
        self._direction_index = 0
        self._gradient_sum = np.zeros(len(self._coordinates), dtype=np.float64)

    @property
    def trainable_dim(self) -> int:
        return len(self._coordinates)

    def wants_global_no_improve_check(self) -> bool:
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._last_role is None:
            self._center = self._encode(ctx.current_params)
            self._center_fit = float(ctx.fit_score)
            return self._propose_plus()
        if self._last_role == "plus":
            self._plus_loss = 1.0 - float(ctx.fit_score)
            return self._propose_minus()
        if self._last_role == "minus":
            return self._consume_minus(1.0 - float(ctx.fit_score))
        if self._last_role == "update":
            accepted = float(ctx.fit_score) >= self._center_fit
            if accepted:
                self._center = self._encode(ctx.current_params)
                self._center_fit = float(ctx.fit_score)
                self._rejection_streak = 0
            else:
                self._rejection_streak += 1
                if self._rejection_streak >= self._reject_patience:
                    self._learning_rate_multiplier *= self._reject_decay
                    self._rejection_streak = 0
            self._step += 1
            params, decision = self._propose_plus()
            decision["previous_update_accepted"] = accepted
            decision["center_fit_score"] = self._center_fit
            return params, decision
        raise RuntimeError(f"unknown fish_spsa proposal role: {self._last_role}")

    def _propose_plus(self, *, start_cycle: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        if start_cycle:
            self._cycle_center = self._center.copy()
            self._direction_index = 0
            self._gradient_sum.fill(0.0)
        assert self._cycle_center is not None
        self._delta = self._rng.choice(np.asarray([-1.0, 1.0]), size=len(self._center))
        self._cycle_c = self._perturbation_scale / ((self._step + 1.0) ** self._gamma)
        proposal = np.clip(self._cycle_center + self._cycle_c * self._delta, 0.0, 1.0)
        self._last_role = "plus"
        return self._decode(proposal), self._decision("plus", proposal)

    def _propose_minus(self) -> tuple[dict[str, Any], dict[str, Any]]:
        assert self._cycle_center is not None
        assert self._delta is not None
        proposal = np.clip(self._cycle_center - self._cycle_c * self._delta, 0.0, 1.0)
        self._last_role = "minus"
        return self._decode(proposal), self._decision("minus", proposal)

    def _consume_minus(self, minus_loss: float) -> tuple[dict[str, Any], dict[str, Any]]:
        assert self._cycle_center is not None
        assert self._delta is not None
        assert self._plus_loss is not None
        gradient = ((self._plus_loss - minus_loss) / max(2.0 * self._cycle_c, 1e-12)) * self._delta
        self._gradient_sum += gradient
        self._direction_index += 1
        if self._direction_index < self._directions_per_update:
            return self._propose_plus(start_cycle=False)
        return self._propose_update(self._gradient_sum / float(self._directions_per_update))

    def _propose_update(self, gradient: np.ndarray) -> tuple[dict[str, Any], dict[str, Any]]:
        assert self._cycle_center is not None
        adam_step = self._step + 1
        self._momentum = self._beta1 * self._momentum + (1.0 - self._beta1) * gradient
        self._variance = self._beta2 * self._variance + (1.0 - self._beta2) * np.square(gradient)
        momentum_hat = self._momentum / max(1.0 - self._beta1**adam_step, 1e-12)
        variance_hat = self._variance / max(1.0 - self._beta2**adam_step, 1e-12)
        learning_rate = (
            self._learning_rate
            * self._learning_rate_multiplier
            / ((self._stability + adam_step) ** self._alpha)
        )
        proposal = np.clip(
            self._cycle_center - learning_rate * momentum_hat / (np.sqrt(variance_hat) + self._epsilon),
            0.0,
            1.0,
        )
        self._last_role = "update"
        decision = self._decision("update", proposal)
        decision["gradient_rms"] = float(np.sqrt(np.mean(np.square(gradient))))
        decision["learning_rate"] = float(learning_rate)
        return self._decode(proposal), decision

    def _encode(self, params: dict[str, Any]) -> np.ndarray:
        return np.asarray(
            [
                (coordinate.read(params) - coordinate.low) / max(coordinate.high - coordinate.low, 1e-12)
                for coordinate in self._coordinates
            ],
            dtype=np.float64,
        ).clip(0.0, 1.0)

    def _decode(self, vector: np.ndarray) -> dict[str, Any]:
        result = copy.deepcopy(self._base_params)
        vector_buffers: dict[str, list[Any]] = {}
        for coordinate, normalized in zip(self._coordinates, vector, strict=True):
            value = coordinate.low + float(normalized) * (coordinate.high - coordinate.low)
            if coordinate.component is None:
                result[coordinate.param_name] = value
                continue
            buffer = vector_buffers.setdefault(
                coordinate.param_name,
                list(result[coordinate.param_name]),
            )
            buffer[coordinate.component] = value
        result.update(vector_buffers)
        return result

    def _decision(self, role: str, proposal: np.ndarray) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {"name": f"fish_spsa_{role}"},
            "fish_spsa": {
                "role": role,
                "step": self._step,
                "trainable_dim": self.trainable_dim,
                "direction_index": self._direction_index,
                "directions_per_update": self._directions_per_update,
                "perturbation_scale": self._cycle_c,
                "learning_rate_multiplier": self._learning_rate_multiplier,
                "proposal_distance_rms": float(np.sqrt(np.mean(np.square(proposal - self._center)))),
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
        }


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0.0 else default


def _unit_interval(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 0.0), 0.999999) if math.isfinite(parsed) else default


__all__ = ["FishSpsaStrategy"]
