"""Asset-independent finite-difference trust-region material optimizer."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_proposals import parameter_changes, residual_feature_vector
from .structured_fish_space import FishSearchCoordinate, structured_fish_coordinates


_EPS = 1.0e-9


class MaterialJacobianTrustRegionStrategy(OptimizerStrategy):
    """Recover continuous material parameters from signed image residuals.

    A complete central-difference Jacobian is measured around one fixed base
    point before each update. The optimizer sees rendered residual features and
    scalar fit scores only; target material parameters are never an input.
    """

    name = "material_jacobian_trust_region"

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
            raise ValueError("material_jacobian_trust_region has no searchable coordinates")

        self._shader_default_anchor_enabled = bool(cfg.get("shader_default_anchor_enabled", True))
        self._shader_default_anchor = _build_shader_default_anchor(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        self._shader_default_anchor_evaluated = not self._shader_default_anchor_enabled
        self._shader_default_anchor_fit_score: float | None = None

        self._difference_mode = str(cfg.get("difference_mode", "forward")).strip().lower()
        if self._difference_mode not in {"forward", "central"}:
            raise ValueError("material_jacobian_trust_region difference_mode must be 'forward' or 'central'")
        self._solve_mode = str(cfg.get("solve_mode", "full_least_squares")).strip().lower()
        if self._solve_mode not in {
            "diagonal_gauss_newton",
            "full_least_squares",
            "groupwise_least_squares",
            "score_gradient",
        }:
            raise ValueError(
                "material_jacobian_trust_region solve_mode must be "
                "'diagonal_gauss_newton', 'full_least_squares', "
                "'groupwise_least_squares', or 'score_gradient'"
            )
        self._probe_step = _bounded_float(cfg.get("probe_step"), 0.025, 0.005, 0.25)
        self._minimum_probe_step = _bounded_float(
            cfg.get("minimum_probe_step"),
            0.006,
            0.001,
            self._probe_step,
        )
        self._ridge = _bounded_float(cfg.get("ridge"), 0.10, 1.0e-6, 1.0e3)
        self._group_weight_ridge = _bounded_float(
            cfg.get("group_weight_ridge"), 1.0e-4, 1.0e-8, 1.0e3
        )
        self._group_weight_clip = _bounded_float(
            cfg.get("group_weight_clip"), 2.0, 0.1, 10.0
        )
        self._trust_radius = _bounded_float(cfg.get("trust_radius"), 0.12, 0.01, 1.0)
        self._maximum_trust_radius = _bounded_float(
            cfg.get("maximum_trust_radius"),
            0.24,
            self._trust_radius,
            1.0,
        )
        self._max_axis_update = _bounded_float(cfg.get("max_axis_update"), 0.18, 0.02, 1.0)
        raw_scales = cfg.get("line_search_scales", (1.0, 0.5, 0.25, 0.125))
        self._line_search_scales = tuple(
            value
            for value in (_positive_float(item) for item in raw_scales)
            if value is not None
        )
        if not self._line_search_scales:
            self._line_search_scales = (1.0, 0.5, 0.25, 0.125)

        self._acceptance_objective = str(
            cfg.get("acceptance_objective", "fit_score")
        ).strip().lower()
        if self._acceptance_objective not in {"fit_score", "residual_merit"}:
            raise ValueError(
                "material_jacobian_trust_region acceptance_objective must be "
                "'fit_score' or 'residual_merit'"
            )
        self._score_feature_weight = _nonnegative_float(
            cfg.get("score_feature_weight"),
            20.0,
        )
        self._maximum_score_drop = _nonnegative_float(
            cfg.get("maximum_score_drop"),
            0.015,
        )
        self._active_coordinate_count = min(
            max(int(cfg.get("active_coordinate_count", 0)), 0),
            len(self._coordinates),
        )
        self._full_refresh_interval = max(
            int(cfg.get("full_refresh_interval", 0)),
            0,
        )
        self._accept_improving_probes = bool(
            cfg.get("accept_improving_probes", False)
        )
        self._minimum_probe_score_gain = _nonnegative_float(
            cfg.get("minimum_probe_score_gain"),
            0.0,
        )
        self._model_reuse_updates = max(int(cfg.get("model_reuse_updates", 0)), 0)
        self._model_reuse_min_score = min(
            _nonnegative_float(cfg.get("model_reuse_min_score"), 0.0),
            1.0,
        )
        raw_reuse_frozen_names = cfg.get("model_reuse_frozen_param_names", ())
        if not isinstance(raw_reuse_frozen_names, (list, tuple)):
            raise ValueError(
                "material_jacobian_trust_region model_reuse_frozen_param_names "
                "must be a list"
            )
        self._model_reuse_frozen_param_names = {
            str(name) for name in raw_reuse_frozen_names
        }
        raw_log_coordinate_ids = cfg.get("log_coordinate_ids", ())
        if not isinstance(raw_log_coordinate_ids, (list, tuple)):
            raise ValueError(
                "material_jacobian_trust_region log_coordinate_ids must be a list"
            )
        self._log_coordinate_ids = {str(value) for value in raw_log_coordinate_ids}
        invalid_log_coordinates = sorted(
            coordinate.coordinate_id
            for coordinate in self._coordinates
            if coordinate.coordinate_id in self._log_coordinate_ids
            and coordinate.low < 0.0
        )
        if invalid_log_coordinates:
            raise ValueError(
                "log1p coordinates require nonnegative bounds: "
                f"{invalid_log_coordinates}"
            )

        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._best_observed_fit_score: float | None = None
        self._best_features: list[float] | None = None
        self._best_merit: float | None = None
        self._round_index = 0
        self._coordinate_index = 0
        self._direction_index = 0
        self._round_coordinates = list(self._coordinates)
        self._selected_coordinate_ids: tuple[str, ...] = ()
        self._coordinate_priorities: dict[str, float] = {}
        self._probe_samples: dict[
            str,
            dict[float, tuple[float, list[float], float]],
        ] = {}
        self._best_probe: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._normalized_update: dict[str, float] | None = None
        self._last_jacobian: Any | None = None
        self._last_jacobian_coordinates: list[FishSearchCoordinate] = []
        self._reuse_updates_remaining = 0
        self._model_reuse_activated = False
        self._line_index = 0
        self._accepted_updates = 0
        self._accepted_probe_moves = 0
        self._accepted_score_regressions = 0
        self._rejected_updates = 0
        self._jacobian_builds = 0
        self._active_column_count = 0
        self._model_reuse_attempts = 0
        self._model_reuse_accepts = 0
        self._stop_reason: str | None = None

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._consume_pending(ctx)
        self._record_observed_fit_score(ctx.fit_score)
        if self._best_fit_score is None:
            self._best_fit_score = float(ctx.fit_score)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_features = self._objective_features(ctx)
            self._best_merit = _vector_rms(self._best_features)
        if self._best_features is None:
            self._stop_reason = "missing_structured_residual_features"
            return copy.deepcopy(self._best_params), self._decision("stopped", stop=True)

        if not self._shader_default_anchor_evaluated:
            self._shader_default_anchor_evaluated = True
            if self._shader_default_anchor != self._best_params:
                self._pending = {"role": "shader_default_anchor"}
                return copy.deepcopy(self._shader_default_anchor), self._decision(
                    "shader_default_anchor",
                    changes=parameter_changes(self._best_params, self._shader_default_anchor),
                )

        while True:
            if self._normalized_update is not None:
                if self._line_index < len(self._line_search_scales):
                    return self._line_search_candidate()
                self._reject_update()
                continue
            if self._coordinate_index < len(self._round_coordinates):
                candidate = self._jacobian_probe_candidate()
                if candidate is not None:
                    return candidate
                continue
            update_ready = self._build_normalized_update()
            if update_ready:
                continue
            if self._accept_best_probe_center():
                continue
            self._stop_reason = "jacobian_rank_or_update_too_small"
            return copy.deepcopy(self._best_params), self._decision("stopped", stop=True)

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": "material_jacobian_trust_region_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
            "coordinate_count": len(self._coordinates),
            "total_coordinate_count": len(self._coordinates),
            "difference_mode": self._difference_mode,
            "solve_mode": self._solve_mode,
            "acceptance_objective": self._acceptance_objective,
            "score_feature_weight": self._score_feature_weight,
            "maximum_score_drop": self._maximum_score_drop,
            "active_coordinate_count": self._active_coordinate_count,
            "full_refresh_interval": self._full_refresh_interval,
            "accept_improving_probes": self._accept_improving_probes,
            "minimum_probe_score_gain": self._minimum_probe_score_gain,
            "model_reuse_updates": self._model_reuse_updates,
            "model_reuse_min_score": self._model_reuse_min_score,
            "model_reuse_frozen_param_names": sorted(
                self._model_reuse_frozen_param_names
            ),
            "log_coordinate_ids": sorted(self._log_coordinate_ids),
            "model_reuse_activated": self._model_reuse_activated,
            "model_reuse_attempts": self._model_reuse_attempts,
            "model_reuse_accepts": self._model_reuse_accepts,
            "round_coordinate_count": len(self._round_coordinates),
            "selected_coordinate_ids": list(self._selected_coordinate_ids),
            "coordinate_priorities": copy.deepcopy(self._coordinate_priorities),
            "shader_default_anchor_enabled": self._shader_default_anchor_enabled,
            "shader_default_anchor_evaluated": self._shader_default_anchor_evaluated,
            "shader_default_anchor_fit_score": self._shader_default_anchor_fit_score,
            "round": self._round_index,
            "jacobian_builds": self._jacobian_builds,
            "active_column_count": self._active_column_count,
            "accepted_updates": self._accepted_updates,
            "accepted_probe_moves": self._accepted_probe_moves,
            "accepted_score_regressions": self._accepted_score_regressions,
            "rejected_updates": self._rejected_updates,
            "probe_step": self._probe_step,
            "ridge": self._ridge,
            "group_weight_ridge": self._group_weight_ridge,
            "group_weight_clip": self._group_weight_clip,
            "trust_radius": self._trust_radius,
            "best_fit_score": self._best_fit_score,
            "best_observed_fit_score": self._best_observed_fit_score,
            "residual_merit": self._best_merit,
            "residual_feature_count": len(self._best_features or []),
            "stop_reason": self._stop_reason,
        }

    def _consume_pending(self, ctx: StrategyContext) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        self._record_observed_fit_score(ctx.fit_score)
        features = self._objective_features(ctx)
        if pending["role"] == "shader_default_anchor":
            self._shader_default_anchor_fit_score = float(ctx.fit_score)
            if self._candidate_improves_center(ctx, features):
                self._accept_center(ctx, features)
            return
        if pending["role"] == "probe":
            if features is not None and len(features) == len(self._best_features or features):
                coordinate_id = str(pending["coordinate_id"])
                direction = float(pending["direction"])
                self._probe_samples.setdefault(coordinate_id, {})[direction] = (
                    float(pending["delta_normalized"]),
                    features,
                    float(ctx.fit_score),
                )
                self._consider_probe_center(ctx, features)
            self._advance_probe()
            return
        if pending["role"] != "trial":
            return
        improved = self._candidate_improves_center(ctx, features)
        if improved:
            self._accept_center(ctx, features)
            self._accepted_updates += 1
            self._ridge = max(self._ridge * 0.5, 1.0e-8)
            self._trust_radius = min(self._trust_radius * 1.2, self._maximum_trust_radius)
            if self._prepare_reused_update():
                self._model_reuse_accepts += 1
                return
            self._start_next_round()
            return
        self._line_index += 1

    def _objective_features(self, ctx: StrategyContext) -> list[float] | None:
        features = residual_feature_vector(ctx.analysis)
        if features is None or self._acceptance_objective == "fit_score":
            return features
        score_error = max(0.0, 1.0 - float(ctx.fit_score))
        return [*features, self._score_feature_weight * score_error]

    def _record_observed_fit_score(self, value: float) -> None:
        score = float(value)
        if not math.isfinite(score):
            return
        if self._best_observed_fit_score is None or score > self._best_observed_fit_score:
            self._best_observed_fit_score = score

    def _candidate_improves_center(
        self,
        ctx: StrategyContext,
        features: list[float] | None,
    ) -> bool:
        score = float(ctx.fit_score)
        if not math.isfinite(score) or features is None or self._best_fit_score is None:
            return False
        if self._acceptance_objective == "fit_score":
            return score > self._best_fit_score + _EPS
        merit = _vector_rms(features)
        if merit is None or self._best_merit is None or merit >= self._best_merit - _EPS:
            return False
        best_observed = self._best_observed_fit_score
        if best_observed is not None and score < best_observed - self._maximum_score_drop:
            return False
        return True

    def _accept_center(
        self,
        ctx: StrategyContext,
        features: list[float] | None,
    ) -> None:
        if features is None:
            return
        previous_score = self._best_fit_score
        self._best_fit_score = float(ctx.fit_score)
        self._best_params = copy.deepcopy(ctx.current_params)
        self._best_features = features
        self._best_merit = _vector_rms(features)
        if previous_score is not None and self._best_fit_score < previous_score - _EPS:
            self._accepted_score_regressions += 1

    def _consider_probe_center(
        self,
        ctx: StrategyContext,
        features: list[float],
    ) -> None:
        if not self._accept_improving_probes:
            return
        score = float(ctx.fit_score)
        if self._best_fit_score is None:
            return
        if self._acceptance_objective == "fit_score":
            if score <= self._best_fit_score + self._minimum_probe_score_gain:
                return
            if self._best_probe is not None and score <= float(self._best_probe["score"]):
                return
        else:
            if not self._candidate_improves_center(ctx, features):
                return
            merit = _vector_rms(features)
            if merit is None:
                return
            if (
                self._best_probe is not None
                and merit >= float(self._best_probe["merit"])
            ):
                return
        self._best_probe = {
            "params": copy.deepcopy(ctx.current_params),
            "score": score,
            "features": list(features),
            "merit": _vector_rms(features),
        }

    def _accept_best_probe_center(self) -> bool:
        probe = self._best_probe
        if probe is None:
            return False
        previous_score = self._best_fit_score
        self._best_params = copy.deepcopy(probe["params"])
        self._best_fit_score = float(probe["score"])
        self._best_features = list(probe["features"])
        self._best_merit = probe["merit"]
        if previous_score is not None and self._best_fit_score < previous_score - _EPS:
            self._accepted_score_regressions += 1
        self._accepted_updates += 1
        self._accepted_probe_moves += 1
        self._ridge = max(self._ridge * 0.75, 1.0e-8)
        self._trust_radius = min(self._trust_radius * 1.05, self._maximum_trust_radius)
        self._start_next_round()
        return True

    def _jacobian_probe_candidate(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        coordinate = self._round_coordinates[self._coordinate_index]
        if coordinate.coordinate_id not in self._log_coordinate_ids:
            span = max(coordinate.high - coordinate.low, 1.0e-12)
            before = coordinate.read(self._best_params)
            if self._difference_mode == "central":
                direction = (1.0, -1.0)[self._direction_index]
            else:
                positive_room = (coordinate.high - before) / span
                negative_room = (before - coordinate.low) / span
                direction = 1.0 if positive_room >= negative_room else -1.0
            requested = direction * self._probe_step * span
            candidate = coordinate.write(self._best_params, before + requested)
            after = coordinate.read(candidate)
            delta_normalized = (after - before) / span
            if abs(delta_normalized) <= 1.0e-12:
                self._advance_probe()
                return None
            self._pending = {
                "role": "probe",
                "coordinate_id": coordinate.coordinate_id,
                "direction": direction,
                "delta_normalized": delta_normalized,
            }
            return candidate, self._decision(
                "jacobian_probe",
                coordinate=coordinate,
                direction=direction,
                delta_normalized=delta_normalized,
            )

        before_normalized = self._coordinate_normalized_value(
            coordinate,
            self._best_params,
        )
        if self._difference_mode == "central":
            direction = (1.0, -1.0)[self._direction_index]
        else:
            positive_room = 1.0 - before_normalized
            negative_room = before_normalized
            direction = 1.0 if positive_room >= negative_room else -1.0
        candidate = self._write_coordinate_normalized_value(
            coordinate,
            self._best_params,
            before_normalized + direction * self._probe_step,
        )
        after_normalized = self._coordinate_normalized_value(coordinate, candidate)
        delta_normalized = after_normalized - before_normalized
        if abs(delta_normalized) <= 1.0e-12:
            self._advance_probe()
            return None
        self._pending = {
            "role": "probe",
            "coordinate_id": coordinate.coordinate_id,
            "direction": direction,
            "delta_normalized": delta_normalized,
        }
        return candidate, self._decision(
            "jacobian_probe",
            coordinate=coordinate,
            direction=direction,
            delta_normalized=delta_normalized,
        )

    def _advance_probe(self) -> None:
        self._direction_index += 1
        required_directions = 2 if self._difference_mode == "central" else 1
        if self._direction_index < required_directions:
            return
        self._direction_index = 0
        self._coordinate_index += 1

    def _build_normalized_update(self) -> bool:
        if self._best_features is None:
            return False
        try:
            import numpy as np
        except Exception:
            return False

        residual = np.asarray(self._best_features, dtype=np.float64)
        active_coordinates: list[FishSearchCoordinate] = []
        columns: list[Any] = []
        score_slopes: list[float] = []
        priorities: dict[str, float] = {}
        for coordinate in self._round_coordinates:
            samples = self._probe_samples.get(coordinate.coordinate_id, {})
            minus = samples.get(-1.0)
            plus = samples.get(1.0)
            if minus is not None and plus is not None:
                denominator = plus[0] - minus[0]
                if abs(denominator) <= 1.0e-12:
                    continue
                column = (np.asarray(plus[1]) - np.asarray(minus[1])) / denominator
                score_slope = (plus[2] - minus[2]) / denominator
            else:
                sample = plus or minus
                if sample is None or abs(sample[0]) <= 1.0e-12:
                    continue
                column = (np.asarray(sample[1]) - residual) / sample[0]
                score_slope = (
                    sample[2] - float(self._best_fit_score or 0.0)
                ) / sample[0]
            if self._solve_mode == "score_gradient":
                if not math.isfinite(score_slope) or abs(score_slope) <= 1.0e-8:
                    continue
                active_coordinates.append(coordinate)
                score_slopes.append(float(score_slope))
                priorities[coordinate.coordinate_id] = abs(float(score_slope))
                continue
            if column.shape != residual.shape or not np.all(np.isfinite(column)):
                continue
            if float(np.linalg.norm(column)) <= 1.0e-8:
                continue
            active_coordinates.append(coordinate)
            columns.append(column)
            column_norm = float(np.linalg.norm(column))
            priorities[coordinate.coordinate_id] = float(
                abs(np.dot(column, residual)) / max(column_norm, 1.0e-12)
            )
        self._active_column_count = len(active_coordinates)
        self._coordinate_priorities = priorities
        if (
            self._active_coordinate_count > 0
            and len(self._round_coordinates) == len(self._coordinates)
            and priorities
        ):
            ranked = sorted(
                priorities,
                key=lambda coordinate_id: priorities[coordinate_id],
                reverse=True,
            )
            self._selected_coordinate_ids = tuple(
                ranked[: self._active_coordinate_count]
            )
        self._jacobian_builds += 1
        minimum_active = 1 if self._solve_mode == "score_gradient" else 2
        if len(active_coordinates) < minimum_active:
            return False

        if self._solve_mode == "score_gradient":
            delta = np.asarray(score_slopes, dtype=np.float64)
            gradient_rms = float(np.sqrt(np.mean(delta * delta)))
            if not math.isfinite(gradient_rms) or gradient_rms <= 1.0e-8:
                return False
            delta *= self._trust_radius / gradient_rms
        else:
            jacobian = np.column_stack(columns)
            mean_column_energy = float(np.mean(np.sum(jacobian * jacobian, axis=0)))
            ridge_absolute = self._ridge * max(mean_column_energy, 1.0e-12)
        if self._solve_mode == "diagonal_gauss_newton":
            gradient = jacobian.T @ residual
            diagonal = np.sum(jacobian * jacobian, axis=0)
            delta = -gradient / (diagonal + ridge_absolute)
        elif self._solve_mode == "full_least_squares":
            delta = self._solve_full_least_squares_delta(jacobian, residual)
            if delta is None:
                return False
        elif self._solve_mode == "groupwise_least_squares":
            grouped_indices: dict[str, list[int]] = {}
            for index, coordinate in enumerate(active_coordinates):
                grouped_indices.setdefault(coordinate.group, []).append(index)
            group_directions: list[Any] = []
            group_effects: list[Any] = []
            for indices in grouped_indices.values():
                group_jacobian = jacobian[:, indices]
                group_energy = float(
                    np.mean(np.sum(group_jacobian * group_jacobian, axis=0))
                )
                group_ridge_root = math.sqrt(
                    self._ridge * max(group_energy, 1.0e-12)
                )
                group_matrix = np.vstack(
                    (
                        group_jacobian,
                        group_ridge_root * np.eye(len(indices)),
                    )
                )
                group_target = np.concatenate((-residual, np.zeros(len(indices))))
                try:
                    group_delta, *_ = np.linalg.lstsq(
                        group_matrix, group_target, rcond=None
                    )
                except np.linalg.LinAlgError:
                    return False
                group_delta = np.clip(
                    group_delta, -self._max_axis_update, self._max_axis_update
                )
                direction = np.zeros(len(active_coordinates), dtype=np.float64)
                direction[indices] = group_delta
                group_directions.append(direction)
                group_effects.append(jacobian @ direction)
            if not group_directions:
                return False
            effect_matrix = np.column_stack(group_effects)
            weight_energy = float(
                np.mean(np.sum(effect_matrix * effect_matrix, axis=0))
            )
            weight_ridge_root = math.sqrt(
                self._group_weight_ridge * max(weight_energy, 1.0e-12)
            )
            weight_matrix = np.vstack(
                (
                    effect_matrix,
                    weight_ridge_root * np.eye(len(group_directions)),
                )
            )
            weight_target = np.concatenate(
                (-residual, np.zeros(len(group_directions)))
            )
            try:
                weights, *_ = np.linalg.lstsq(
                    weight_matrix, weight_target, rcond=None
                )
            except np.linalg.LinAlgError:
                return False
            weights = np.clip(
                weights, -self._group_weight_clip, self._group_weight_clip
            )
            delta = sum(
                (
                    weight * direction
                    for weight, direction in zip(
                        weights, group_directions, strict=True
                    )
                ),
                start=np.zeros(len(active_coordinates), dtype=np.float64),
            )
        delta = np.clip(delta, -self._max_axis_update, self._max_axis_update)
        rms = float(np.sqrt(np.mean(delta * delta)))
        if not math.isfinite(rms) or rms <= 1.0e-5:
            return False
        if rms > self._trust_radius:
            delta *= self._trust_radius / rms
        self._normalized_update = {
            coordinate.coordinate_id: float(value)
            for coordinate, value in zip(active_coordinates, delta.tolist())
            if math.isfinite(float(value)) and abs(float(value)) > 1.0e-5
        }
        if self._solve_mode == "full_least_squares":
            self._last_jacobian = jacobian.copy()
            self._last_jacobian_coordinates = list(active_coordinates)
            self._reuse_updates_remaining = self._model_reuse_updates
        self._line_index = 0
        return len(self._normalized_update) >= minimum_active

    def _solve_full_least_squares_delta(
        self,
        jacobian: Any,
        residual: Any,
    ) -> Any | None:
        try:
            import numpy as np
        except Exception:
            return None
        mean_column_energy = float(
            np.mean(np.sum(jacobian * jacobian, axis=0))
        )
        ridge_absolute = self._ridge * max(mean_column_energy, 1.0e-12)
        ridge_root = math.sqrt(ridge_absolute)
        matrix = np.vstack(
            (jacobian, ridge_root * np.eye(jacobian.shape[1]))
        )
        target = np.concatenate((-residual, np.zeros(jacobian.shape[1])))
        try:
            delta, *_ = np.linalg.lstsq(matrix, target, rcond=None)
        except np.linalg.LinAlgError:
            return None
        return delta

    def _prepare_reused_update(self) -> bool:
        if (
            self._model_reuse_updates <= 0
            or self._reuse_updates_remaining <= 0
            or self._last_jacobian is None
            or self._best_features is None
            or self._best_fit_score is None
            or self._best_fit_score < self._model_reuse_min_score
        ):
            return False
        try:
            import numpy as np
        except Exception:
            return False
        active_indices = [
            index
            for index, coordinate in enumerate(self._last_jacobian_coordinates)
            if coordinate.param_name not in self._model_reuse_frozen_param_names
        ]
        if len(active_indices) < 2:
            return False
        coordinates = [
            self._last_jacobian_coordinates[index] for index in active_indices
        ]
        jacobian = self._last_jacobian[:, active_indices]
        residual = np.asarray(self._best_features, dtype=np.float64)
        delta = self._solve_full_least_squares_delta(jacobian, residual)
        if delta is None or not np.all(np.isfinite(delta)):
            return False
        delta = np.clip(delta, -self._max_axis_update, self._max_axis_update)
        rms = float(np.sqrt(np.mean(delta * delta)))
        if not math.isfinite(rms) or rms <= 1.0e-5:
            return False
        if rms > self._trust_radius:
            delta *= self._trust_radius / rms
        update = {
            coordinate.coordinate_id: float(value)
            for coordinate, value in zip(coordinates, delta.tolist(), strict=True)
            if math.isfinite(float(value)) and abs(float(value)) > 1.0e-5
        }
        if len(update) < 2:
            return False
        self._reuse_updates_remaining -= 1
        self._model_reuse_activated = True
        self._normalized_update = update
        self._probe_samples = {}
        self._best_probe = None
        self._line_index = 0
        self._model_reuse_attempts += 1
        return True

    def _line_search_candidate(self) -> tuple[dict[str, Any], dict[str, Any]]:
        assert self._normalized_update is not None
        scale = self._line_search_scales[self._line_index]
        candidate = copy.deepcopy(self._best_params)
        for coordinate in self._coordinates:
            delta = self._normalized_update.get(coordinate.coordinate_id)
            if delta is None:
                continue
            if coordinate.coordinate_id not in self._log_coordinate_ids:
                span = coordinate.high - coordinate.low
                candidate = coordinate.write(
                    candidate,
                    coordinate.read(candidate) + scale * delta * span,
                )
                continue
            before_normalized = self._coordinate_normalized_value(coordinate, candidate)
            candidate = self._write_coordinate_normalized_value(
                coordinate,
                candidate,
                before_normalized + scale * delta,
            )
        self._pending = {"role": "trial", "scale": scale}
        return candidate, self._decision(
            "trust_region_trial",
            scale=scale,
            changes=parameter_changes(self._best_params, candidate),
        )

    def _coordinate_normalized_value(
        self,
        coordinate: FishSearchCoordinate,
        params: dict[str, Any],
    ) -> float:
        value = coordinate.read(params)
        if coordinate.coordinate_id in self._log_coordinate_ids:
            value = min(max(value, coordinate.low), coordinate.high)
            low = math.log1p(coordinate.low)
            high = math.log1p(coordinate.high)
            return (math.log1p(value) - low) / max(high - low, 1.0e-12)
        return (value - coordinate.low) / max(
            coordinate.high - coordinate.low,
            1.0e-12,
        )

    def _write_coordinate_normalized_value(
        self,
        coordinate: FishSearchCoordinate,
        params: dict[str, Any],
        normalized: float,
    ) -> dict[str, Any]:
        unit = min(max(float(normalized), 0.0), 1.0)
        if coordinate.coordinate_id in self._log_coordinate_ids:
            low = math.log1p(coordinate.low)
            high = math.log1p(coordinate.high)
            value = math.expm1(low + unit * (high - low))
        else:
            value = coordinate.low + unit * (coordinate.high - coordinate.low)
        return coordinate.write(params, value)

    def _reject_update(self) -> None:
        if self._accept_best_probe_center():
            return
        self._rejected_updates += 1
        self._ridge = min(self._ridge * 4.0, 1.0e3)
        self._trust_radius = max(self._trust_radius * 0.5, 0.01)
        self._probe_step = max(self._probe_step * 0.7, self._minimum_probe_step)
        self._start_next_round()

    def _start_next_round(self) -> None:
        self._round_index += 1
        self._round_coordinates = self._coordinates_for_round()
        self._coordinate_index = 0
        self._direction_index = 0
        self._probe_samples = {}
        self._best_probe = None
        self._normalized_update = None
        self._last_jacobian = None
        self._last_jacobian_coordinates = []
        self._reuse_updates_remaining = 0
        self._line_index = 0

    def _coordinates_for_round(self) -> list[FishSearchCoordinate]:
        if self._active_coordinate_count <= 0 or not self._selected_coordinate_ids:
            coordinates = list(self._coordinates)
        elif (
            self._full_refresh_interval > 0
            and self._round_index % self._full_refresh_interval == 0
        ):
            coordinates = list(self._coordinates)
        else:
            selected = set(self._selected_coordinate_ids)
            coordinates = [
                coordinate
                for coordinate in self._coordinates
                if coordinate.coordinate_id in selected
            ]
        if self._model_reuse_activated and self._model_reuse_frozen_param_names:
            filtered = [
                coordinate
                for coordinate in coordinates
                if coordinate.param_name not in self._model_reuse_frozen_param_names
            ]
            if filtered:
                return filtered
            return [
                coordinate
                for coordinate in self._coordinates
                if coordinate.param_name not in self._model_reuse_frozen_param_names
            ]
        return coordinates

    def _decision(
        self,
        role: str,
        *,
        stop: bool = False,
        coordinate: FishSearchCoordinate | None = None,
        direction: float | None = None,
        delta_normalized: float | None = None,
        scale: float | None = None,
        changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"material_jacobian_trust_region_{role}",
                "description": "Full image-residual Jacobian with trust-region line search",
            },
            "material_jacobian_trust_region": {
                "profile": "material_jacobian_trust_region_v1",
                "role": role,
                "round": self._round_index,
                "difference_mode": self._difference_mode,
                "solve_mode": self._solve_mode,
                "acceptance_objective": self._acceptance_objective,
                "score_feature_weight": self._score_feature_weight,
                "maximum_score_drop": self._maximum_score_drop,
                "shader_default_anchor_enabled": self._shader_default_anchor_enabled,
                "shader_default_anchor_evaluated": self._shader_default_anchor_evaluated,
                "shader_default_anchor_fit_score": self._shader_default_anchor_fit_score,
                "coordinate_index": self._coordinate_index,
                "coordinate_count": len(self._round_coordinates),
                "total_coordinate_count": len(self._coordinates),
                "active_coordinate_count": self._active_coordinate_count,
                "full_refresh_interval": self._full_refresh_interval,
                "accept_improving_probes": self._accept_improving_probes,
                "minimum_probe_score_gain": self._minimum_probe_score_gain,
                "model_reuse_updates": self._model_reuse_updates,
                "model_reuse_min_score": self._model_reuse_min_score,
                "model_reuse_frozen_param_names": sorted(
                    self._model_reuse_frozen_param_names
                ),
                "model_reuse_activated": self._model_reuse_activated,
                "model_reuse_attempts": self._model_reuse_attempts,
                "model_reuse_accepts": self._model_reuse_accepts,
                "selected_coordinate_ids": list(self._selected_coordinate_ids),
                "coordinate": coordinate.coordinate_id if coordinate else None,
                "direction": direction,
                "delta_normalized": delta_normalized,
                "line_search_scale": scale,
                "probe_step": self._probe_step,
                "ridge": self._ridge,
                "trust_radius": self._trust_radius,
                "active_column_count": self._active_column_count,
                "best_fit_score": self._best_fit_score,
                "best_observed_fit_score": self._best_observed_fit_score,
                "residual_merit": self._best_merit,
                "feedback_source": "online_target_png_score_and_signed_residuals_only",
                "target_params_visible": False,
            },
            "changes": changes or [],
            "stop_reason": self._stop_reason if stop else "continue",
        }


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0.0 else None


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    parsed = _positive_float(value)
    if parsed is None:
        parsed = default
    return min(max(parsed, low), high)


def _nonnegative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else default


def _vector_rms(values: Sequence[float] | None) -> float | None:
    if not values:
        return None
    return math.sqrt(sum(float(value) ** 2 for value in values) / len(values))


def _build_shader_default_anchor(
    *,
    initial_params: dict[str, Any],
    shader_params: Sequence[ShaderParam],
    search_param_names: Sequence[str] | None,
) -> dict[str, Any]:
    allowed = set(search_param_names or initial_params)
    result = copy.deepcopy(initial_params)
    for shader_param in shader_params:
        if shader_param.name not in allowed or shader_param.name not in result:
            continue
        default = shader_param.default
        if isinstance(default, bool) or default is None:
            continue
        if isinstance(default, (int, float)) and math.isfinite(float(default)):
            result[shader_param.name] = float(default)
            continue
        if isinstance(default, (list, tuple)) and default:
            try:
                values = [float(value) for value in default]
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(value) for value in values):
                result[shader_param.name] = values
    return result


__all__ = ["MaterialJacobianTrustRegionStrategy"]
