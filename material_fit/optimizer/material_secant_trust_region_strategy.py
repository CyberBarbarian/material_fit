"""Multi-anchor secant trust-region optimizer for coupled materials."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

import numpy as np

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_proposals import parameter_changes, residual_feature_vector
from .structured_fish_space import FishSearchCoordinate, structured_fish_coordinates


class MaterialSecantTrustRegionStrategy(OptimizerStrategy):
    """Fit a regional residual model from deterministic joint probes."""

    name = "material_secant_trust_region"

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
            raise ValueError("material_secant_trust_region has no searchable coordinates")
        full_rank_design_size = _next_power_of_two(len(self._coordinates))
        configured_design_size = max(
            int(cfg.get("design_size", full_rank_design_size)),
            1,
        )
        self._compressed_design = bool(cfg.get("compressed_design", False))
        self._design_size = _next_power_of_two(
            configured_design_size
            if self._compressed_design
            else max(configured_design_size, full_rank_design_size)
        )
        self._design_order = _next_power_of_two(
            max(len(self._coordinates), self._design_size)
        )
        self._antithetic = bool(cfg.get("antithetic", True))
        self._radius = _bounded_float(cfg.get("probe_radius"), 0.20, 0.01, 0.75)
        self._minimum_radius = _bounded_float(cfg.get("minimum_probe_radius"), 0.025, 0.001, self._radius)
        self._maximum_radius = _bounded_float(cfg.get("maximum_probe_radius"), 0.35, self._radius, 1.0)
        self._radius_growth = _bounded_float(cfg.get("radius_growth"), 1.15, 1.0, 2.0)
        self._radius_shrink = _bounded_float(cfg.get("radius_shrink"), 0.70, 0.1, 0.95)
        self._ridge = _bounded_float(cfg.get("ridge"), 0.01, 1.0e-8, 10.0)
        self._trust_radius = _bounded_float(cfg.get("trust_radius"), 0.35, 0.01, 1.0)
        self._max_axis_update = _bounded_float(cfg.get("max_axis_update"), 0.65, 0.01, 1.0)
        self._score_feature_weight = max(float(cfg.get("score_feature_weight", 20.0)), 0.0)
        self._maximum_score_drop = max(float(cfg.get("maximum_score_drop", 0.03)), 0.0)
        self._model_reuse_updates = max(int(cfg.get("model_reuse_updates", 0)), 0)
        scales = cfg.get("line_search_scales", (1.0, 0.75, 0.5, 0.25, 0.125))
        self._line_search_scales = tuple(float(value) for value in scales if float(value) > 0.0)
        if not self._line_search_scales:
            self._line_search_scales = (1.0, 0.5, 0.25)

        self._base_params = copy.deepcopy(initial_params)
        self._center_params = copy.deepcopy(initial_params)
        self._center_vector = self._encode(initial_params)
        self._center_score: float | None = None
        self._center_features: np.ndarray | None = None
        self._center_merit: float | None = None
        self._best_params = copy.deepcopy(initial_params)
        self._best_score: float | None = None
        self._round_index = 0
        self._design_queue: list[dict[str, Any]] = []
        self._samples: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._update: np.ndarray | None = None
        self._response: np.ndarray | None = None
        self._reuse_updates_remaining = 0
        self._line_index = 0
        self._model_builds = 0
        self._accepted_updates = 0
        self._accepted_exploration_centers = 0
        self._model_reuse_attempts = 0
        self._model_reuse_accepts = 0
        self._rejected_updates = 0
        self._best_observed_score: float | None = None
        self._discarded_feature_samples = 0
        self._stop_reason: str | None = None

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._consume_pending(ctx)
        self._record_best(ctx)
        if self._center_score is None:
            features = self._objective_features(ctx)
            if features is None:
                self._stop_reason = "missing_structured_residual_features"
                return copy.deepcopy(ctx.current_params), self._decision("stopped")
            self._set_center(ctx.current_params, float(ctx.fit_score), features)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_score = float(ctx.fit_score)

        while True:
            if self._design_queue:
                design_item = self._design_queue.pop(0)
                vector = np.asarray(design_item["vector"], dtype=np.float64)
                candidate = self._decode(vector)
                self._pending = {
                    "role": "design_probe",
                    "vector": vector,
                    "params": candidate,
                    "direction_index": design_item["direction_index"],
                    "sign": design_item["sign"],
                }
                return candidate, self._decision("design_probe", candidate=candidate)
            if not self._samples and self._update is None:
                self._start_design_round()
                continue
            if self._update is None:
                self._update = self._fit_secant_update()
                self._line_index = 0
                self._model_builds += 1
                if self._update is None:
                    self._finish_failed_round()
                    continue
            if self._line_index < len(self._line_search_scales):
                scale = self._line_search_scales[self._line_index]
                self._line_index += 1
                vector = np.clip(self._center_vector + scale * self._update, 0.0, 1.0)
                candidate = self._decode(vector)
                self._pending = {
                    "role": "secant_trial",
                    "vector": vector,
                    "params": candidate,
                    "scale": scale,
                }
                return candidate, self._decision("secant_trial", candidate=candidate, scale=scale)
            self._finish_failed_round()

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": "material_secant_trust_region_v2",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
            "coordinate_count": len(self._coordinates),
            "design_size": self._design_size,
            "compressed_design": self._compressed_design,
            "design_rank_upper_bound": min(
                self._design_size,
                len(self._coordinates),
            ),
            "antithetic": self._antithetic,
            "design_evaluations_per_round": self._design_size * (2 if self._antithetic else 1),
            "round": self._round_index,
            "probe_radius": self._radius,
            "trust_radius": self._trust_radius,
            "model_builds": self._model_builds,
            "accepted_updates": self._accepted_updates,
            "accepted_exploration_centers": self._accepted_exploration_centers,
            "model_reuse_updates": self._model_reuse_updates,
            "model_reuse_attempts": self._model_reuse_attempts,
            "model_reuse_accepts": self._model_reuse_accepts,
            "rejected_updates": self._rejected_updates,
            "center_score": self._center_score,
            "center_merit": self._center_merit,
            "best_score": self._best_score,
            "best_observed_score": self._best_observed_score,
            "discarded_feature_samples": self._discarded_feature_samples,
            "stop_reason": self._stop_reason,
        }

    def _consume_pending(self, ctx: StrategyContext) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        features = self._objective_features(ctx)
        self._record_best(ctx)
        if features is None:
            return
        merit = _rms(features)
        if pending["role"] == "design_probe":
            self._samples.append(
                {
                    "vector": np.asarray(pending["vector"], dtype=np.float64),
                    "params": copy.deepcopy(ctx.current_params),
                    "score": float(ctx.fit_score),
                    "features": features,
                    "merit": merit,
                    "direction_index": int(pending["direction_index"]),
                    "sign": int(pending["sign"]),
                }
            )
            return
        if pending["role"] == "secant_trial" and self._accepts_center(float(ctx.fit_score), merit):
            self._set_center(ctx.current_params, float(ctx.fit_score), features)
            self._accepted_updates += 1
            self._radius = min(self._radius * self._radius_growth, self._maximum_radius)
            if self._prepare_reused_update():
                self._model_reuse_accepts += 1
                return
            self._reset_round()

    def _record_best(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if self._best_observed_score is None or score > self._best_observed_score:
            self._best_observed_score = score
        if self._best_score is None or score > self._best_score:
            self._best_score = score
            self._best_params = copy.deepcopy(ctx.current_params)

    def _objective_features(self, ctx: StrategyContext) -> np.ndarray | None:
        features = residual_feature_vector(ctx.analysis)
        if features is None:
            return None
        values = np.asarray(features, dtype=np.float64)
        if self._score_feature_weight > 0.0:
            values = np.concatenate(
                (values, np.asarray([(1.0 - float(ctx.fit_score)) * self._score_feature_weight]))
            )
        if not np.all(np.isfinite(values)):
            self._discarded_feature_samples += 1
            return None
        if self._center_features is not None and values.shape != self._center_features.shape:
            self._discarded_feature_samples += 1
            return None
        return values

    def _set_center(self, params: dict[str, Any], score: float, features: np.ndarray) -> None:
        self._center_params = copy.deepcopy(params)
        self._center_vector = self._encode(params)
        self._center_score = score
        self._center_features = np.asarray(features, dtype=np.float64)
        self._center_merit = _rms(self._center_features)

    def _start_design_round(self) -> None:
        design = _hadamard(self._design_order)[
            : self._design_size,
            : len(self._coordinates),
        ]
        self._design_queue = []
        for direction_index, row in enumerate(design):
            signs = (1, -1) if self._antithetic else (1,)
            for sign in signs:
                self._design_queue.append(
                    {
                        "vector": np.clip(
                            self._center_vector + sign * self._radius * row,
                            0.0,
                            1.0,
                        ),
                        "direction_index": direction_index,
                        "sign": sign,
                    }
                )

    def _fit_secant_update(self) -> np.ndarray | None:
        if self._center_features is None:
            return None
        if self._antithetic:
            pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
            by_direction: dict[int, dict[int, dict[str, Any]]] = {}
            for sample in self._samples:
                by_direction.setdefault(int(sample["direction_index"]), {})[
                    int(sample["sign"])
                ] = sample
            for samples in by_direction.values():
                if 1 in samples and -1 in samples:
                    pairs.append((samples[1], samples[-1]))
            if len(pairs) < self._design_size:
                return None
            x = np.vstack(
                [
                    (np.asarray(plus["vector"]) - np.asarray(minus["vector"])) / 2.0
                    for plus, minus in pairs
                ]
            )
            y = np.vstack(
                [
                    (np.asarray(plus["features"]) - np.asarray(minus["features"])) / 2.0
                    for plus, minus in pairs
                ]
            )
        else:
            if len(self._samples) < self._design_size:
                return None
            x = np.vstack([sample["vector"] - self._center_vector for sample in self._samples])
            y = np.vstack([sample["features"] - self._center_features for sample in self._samples])
        gram = x.T @ x + self._ridge * np.eye(x.shape[1])
        try:
            response = np.linalg.solve(gram, x.T @ y)
        except np.linalg.LinAlgError:
            return None
        self._response = response
        self._reuse_updates_remaining = self._model_reuse_updates
        return self._solve_response_update(response)

    def _solve_response_update(self, response: np.ndarray) -> np.ndarray | None:
        if self._center_features is None:
            return None
        try:
            normal = response @ response.T + self._ridge * np.eye(response.shape[0])
            gradient = response @ self._center_features
            update = -np.linalg.solve(normal, gradient)
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(update)):
            return None
        update = np.clip(update, -self._max_axis_update, self._max_axis_update)
        rms = float(np.sqrt(np.mean(np.square(update))))
        if rms > self._trust_radius:
            update *= self._trust_radius / rms
        if float(np.max(np.abs(update))) < 1.0e-4:
            return None
        return update

    def _prepare_reused_update(self) -> bool:
        if self._response is None or self._reuse_updates_remaining <= 0:
            return False
        self._reuse_updates_remaining -= 1
        update = self._solve_response_update(self._response)
        if update is None:
            return False
        self._design_queue = []
        self._samples = []
        self._update = update
        self._line_index = 0
        self._model_reuse_attempts += 1
        return True

    def _accepts_center(self, score: float, merit: float) -> bool:
        if self._center_score is None or self._center_merit is None:
            return True
        return (
            merit < self._center_merit - 1.0e-9
            and score >= self._center_score - self._maximum_score_drop
        )

    def _finish_failed_round(self) -> None:
        eligible = [
            sample
            for sample in self._samples
            if self._accepts_center(float(sample["score"]), float(sample["merit"]))
        ]
        if eligible:
            best = min(eligible, key=lambda sample: (float(sample["merit"]), -float(sample["score"])))
            self._set_center(best["params"], float(best["score"]), best["features"])
            self._accepted_exploration_centers += 1
        else:
            self._rejected_updates += 1
        self._radius = max(self._radius * self._radius_shrink, self._minimum_radius)
        self._reset_round()

    def _reset_round(self) -> None:
        self._round_index += 1
        self._design_queue = []
        self._samples = []
        self._update = None
        self._response = None
        self._reuse_updates_remaining = 0
        self._line_index = 0

    def _encode(self, params: dict[str, Any]) -> np.ndarray:
        return np.asarray(
            [
                (coordinate.read(params) - coordinate.low)
                / max(coordinate.high - coordinate.low, 1.0e-12)
                for coordinate in self._coordinates
            ],
            dtype=np.float64,
        ).clip(0.0, 1.0)

    def _decode(self, vector: np.ndarray) -> dict[str, Any]:
        result = copy.deepcopy(self._base_params)
        for coordinate, normalized in zip(self._coordinates, vector, strict=True):
            result = coordinate.write(
                result,
                coordinate.low + float(normalized) * (coordinate.high - coordinate.low),
            )
        return result

    def _decision(
        self,
        role: str,
        *,
        candidate: dict[str, Any] | None = None,
        scale: float | None = None,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"material_secant_trust_region_{role}",
                "description": "Multi-anchor regional residual model over shared material coordinates",
            },
            "material_secant_trust_region": {
                "role": role,
                "round": self._round_index,
                "coordinate_count": len(self._coordinates),
                "design_size": self._design_size,
                "compressed_design": self._compressed_design,
                "antithetic": self._antithetic,
                "probe_radius": self._radius,
                "line_search_scale": scale,
                "center_score": self._center_score,
                "center_merit": self._center_merit,
                "best_score": self._best_score,
                "model_reuse_updates": self._model_reuse_updates,
                "model_reuse_attempts": self._model_reuse_attempts,
                "model_reuse_accepts": self._model_reuse_accepts,
                "feedback_source": "online_target_png_score_and_signed_residuals_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._center_params, candidate or self._center_params),
            "stop_reason": self._stop_reason or "continue",
        }


def _next_power_of_two(value: int) -> int:
    return 1 << max(value - 1, 0).bit_length()


def _hadamard(order: int) -> np.ndarray:
    matrix = np.asarray([[1.0]])
    while matrix.shape[0] < order:
        matrix = np.block([[matrix, matrix], [matrix, -matrix]])
    return matrix


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if not math.isfinite(numeric):
        numeric = default
    return min(max(numeric, low), high)


__all__ = ["MaterialSecantTrustRegionStrategy"]
