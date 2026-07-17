"""Pure proposal math for the structured fish optimizer."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Sequence

from .structured_fish_space import FishSearchCoordinate


_DIRECTIONS = (-1.0, 1.0)
_EPS = 1.0e-9


@dataclass(frozen=True)
class GaussNewtonMove:
    candidate: dict[str, Any]
    coordinate_ids: list[str]
    normalized_updates: dict[str, float]
    applied_steps: dict[str, float]
    jacobian_column_count: int


def build_joint_pattern_move(
    *,
    best_params: dict[str, Any],
    coordinates: Sequence[FishSearchCoordinate],
    response: dict[str, dict[str, Any]],
    steps: dict[str, float],
    move_scale: float,
) -> tuple[dict[str, Any], list[str]] | None:
    ranked: list[tuple[float, FishSearchCoordinate, float]] = []
    for coordinate in coordinates:
        row = response[coordinate.coordinate_id]
        direction = row.get("best_direction")
        best_gain = float(row.get("best_gain", 0.0) or 0.0)
        if direction not in _DIRECTIONS or best_gain <= _EPS:
            continue
        fail_streak = int(row.get("fail_streak", 0) or 0)
        priority = best_gain / (1.0 + 0.5 * fail_streak)
        ranked.append((priority, coordinate, float(direction)))
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected = ranked[: min(12, len(ranked))]
    if len(selected) < 2:
        return None

    candidate = copy.deepcopy(best_params)
    coordinate_ids: list[str] = []
    for _, coordinate, direction in selected:
        before = coordinate.read(candidate)
        candidate = coordinate.write(
            candidate,
            before + direction * steps[coordinate.coordinate_id] * move_scale,
        )
        if abs(coordinate.read(candidate) - before) > 1.0e-12:
            coordinate_ids.append(coordinate.coordinate_id)
    if len(coordinate_ids) < 2:
        return None
    return candidate, coordinate_ids


def solve_gauss_newton_move(
    *,
    best_params: dict[str, Any],
    residual_features: Sequence[float],
    coordinates: Sequence[FishSearchCoordinate],
    jacobian_columns: dict[str, list[float]],
    steps: dict[str, float],
    damping: float,
    ridge: float,
) -> GaussNewtonMove | None:
    try:
        import numpy as np
    except Exception:
        return None

    feature_count = len(residual_features)
    active_coordinates: list[FishSearchCoordinate] = []
    columns: list[Any] = []
    active_steps: list[float] = []
    for coordinate in coordinates:
        derivative = jacobian_columns.get(coordinate.coordinate_id)
        if derivative is None or len(derivative) != feature_count:
            continue
        step = steps[coordinate.coordinate_id]
        column = np.asarray(derivative, dtype=np.float64) * step
        if not np.all(np.isfinite(column)) or float(np.linalg.norm(column)) <= 1.0e-8:
            continue
        active_coordinates.append(coordinate)
        columns.append(column)
        active_steps.append(step)
    if len(active_coordinates) < 2:
        return None

    jacobian = np.column_stack(columns)
    residual = np.asarray(residual_features, dtype=np.float64)
    if residual.shape != (feature_count,) or not np.all(np.isfinite(residual)):
        return None
    ridge_root = math.sqrt(max(ridge, 0.0))
    if ridge_root > 0.0:
        matrix = np.vstack((jacobian, ridge_root * np.eye(len(active_coordinates))))
        target = np.concatenate((-residual, np.zeros(len(active_coordinates))))
    else:
        matrix = jacobian
        target = -residual
    try:
        normalized_delta, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    normalized_delta = np.clip(normalized_delta, -2.0, 2.0) * damping

    candidate = copy.deepcopy(best_params)
    coordinate_ids: list[str] = []
    normalized_updates: dict[str, float] = {}
    applied_steps: dict[str, float] = {}
    for coordinate, step, delta_scale in zip(
        active_coordinates,
        active_steps,
        normalized_delta.tolist(),
    ):
        delta_scale = float(delta_scale)
        if not math.isfinite(delta_scale) or abs(delta_scale) <= 0.02:
            continue
        before = coordinate.read(candidate)
        candidate = coordinate.write(candidate, before + delta_scale * step)
        if abs(coordinate.read(candidate) - before) <= 1.0e-12:
            continue
        coordinate_ids.append(coordinate.coordinate_id)
        normalized_updates[coordinate.coordinate_id] = delta_scale
        applied_steps[coordinate.coordinate_id] = step
    if len(coordinate_ids) < 2:
        return None
    return GaussNewtonMove(
        candidate=candidate,
        coordinate_ids=coordinate_ids,
        normalized_updates=normalized_updates,
        applied_steps=applied_steps,
        jacobian_column_count=len(active_coordinates),
    )


def rank_coordinates(
    coordinates: Sequence[FishSearchCoordinate],
    response: dict[str, dict[str, Any]],
) -> list[FishSearchCoordinate]:
    rows: list[tuple[float, int, int, FishSearchCoordinate]] = []
    for index, coordinate in enumerate(coordinates):
        row = response[coordinate.coordinate_id]
        best_gain = max(float(row["best_gain"]), 0.0)
        last_gain = max(float(row["last_gain"]), 0.0)
        fail_streak = int(row["fail_streak"])
        priority = best_gain / (1.0 + 0.5 * fail_streak) + 0.35 * last_gain
        rows.append((-priority, int(row["attempts"]), index, coordinate))
    rows.sort(key=lambda row: row[:3])
    return [row[3] for row in rows]


def normalized_coordinate_distance(
    params: dict[str, Any],
    initial_params: dict[str, Any],
    coordinates: Sequence[FishSearchCoordinate],
) -> float:
    errors: list[float] = []
    for coordinate in coordinates:
        try:
            initial_value = coordinate.read(initial_params)
            value = coordinate.read(params)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        span = max(coordinate.high - coordinate.low, 1.0e-9)
        errors.append(abs(value - initial_value) / span)
    return sum(errors) / len(errors) if errors else 0.0


def parameter_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name in dict.fromkeys((*before.keys(), *after.keys())):
        old = before.get(name)
        new = after.get(name)
        if old != new:
            changes.append({"param": name, "before": old, "after": new})
    return changes


def residual_feature_vector(analysis: dict[str, Any]) -> list[float] | None:
    payload = analysis.get("structured_residual_features") if isinstance(analysis, dict) else None
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or not features:
        return None
    result: list[float] = []
    for value in features:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        result.append(number)
    return result


def vector_rms(values: Sequence[float] | None) -> float | None:
    if not values:
        return None
    return math.sqrt(sum(value * value for value in values) / len(values))


__all__ = [
    "GaussNewtonMove",
    "build_joint_pattern_move",
    "normalized_coordinate_distance",
    "parameter_changes",
    "rank_coordinates",
    "residual_feature_vector",
    "solve_gauss_newton_move",
    "vector_rms",
]
