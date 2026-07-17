"""Target-independent block probes for escaping flat material-score basins."""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from typing import Any, Sequence

from .structured_fish_space import FishSearchCoordinate, MATERIAL_GROUPS


DEFAULT_ESCAPE_PAIR_COUNT = 40
DEFAULT_ESCAPE_RADII: tuple[float, ...] = (2.5, 1.0)


@dataclass(frozen=True)
class BlockEscapeDirection:
    """One deterministic Rademacher direction over material coordinates."""

    direction_index: int
    coordinate_ids: tuple[str, ...]
    signs: tuple[float, ...]
    seed: int


@dataclass(frozen=True)
class BlockEscapeProbe:
    """A concrete positive or negative candidate on a block direction."""

    candidate: dict[str, Any]
    normalized_updates: dict[str, float]


@dataclass(frozen=True)
class BlockEscapeObservation:
    """Online scores and residuals for one antithetic probe pair."""

    direction: BlockEscapeDirection
    minus_params: dict[str, Any]
    plus_params: dict[str, Any]
    minus_fit_score: float
    plus_fit_score: float
    minus_objective_score: float
    plus_objective_score: float
    minus_features: list[float] | None
    plus_features: list[float] | None


@dataclass(frozen=True)
class BlockEscapeResponseMove:
    """A coupled response move reconstructed from online block probes."""

    method: str
    candidate: dict[str, Any]
    coordinate_ids: tuple[str, ...]
    normalized_updates: dict[str, float]
    direction_count: int
    residual_feature_count: int


def build_block_escape_directions(
    *,
    coordinates: Sequence[FishSearchCoordinate],
    pair_count: int,
    round_index: int,
    seed: int,
) -> list[BlockEscapeDirection]:
    """Build reproducible full-rank Hadamard directions without target data."""

    active = _material_coordinates(coordinates)
    count = max(int(pair_count), 1)
    if not active:
        return []
    order = 1
    while order < len(active):
        order *= 2
    rng = random.Random(int(seed))
    column_order = list(range(len(active)))
    rng.shuffle(column_order)
    column_signs = [1.0 if rng.random() < 0.5 else -1.0 for _ in active]
    directions: list[BlockEscapeDirection] = []
    for direction_index in range(min(count, order)):
        row_index = (int(round_index) * count + direction_index) % order
        signs = tuple(
            _hadamard_sign(row_index, source_column) * column_signs[target_column]
            for target_column, source_column in enumerate(column_order)
        )
        directions.append(
            BlockEscapeDirection(
                direction_index=direction_index,
                coordinate_ids=tuple(coordinate.coordinate_id for coordinate in active),
                signs=signs,
                seed=int(seed),
            )
        )
    return directions


def build_coordinate_escape_directions(
    *,
    coordinates: Sequence[FishSearchCoordinate],
    pair_count: int,
    round_index: int,
    seed: int,
) -> list[BlockEscapeDirection]:
    """Build one antithetic finite-difference direction per coordinate."""

    active = _material_coordinates(coordinates)
    order = list(range(len(active)))
    random.Random(int(seed) + int(round_index)).shuffle(order)
    directions: list[BlockEscapeDirection] = []
    for direction_index, coordinate_index in enumerate(order[: max(int(pair_count), 1)]):
        directions.append(
            BlockEscapeDirection(
                direction_index=direction_index,
                coordinate_ids=(active[coordinate_index].coordinate_id,),
                signs=(1.0,),
                seed=int(seed),
            )
        )
    return directions


def apply_block_escape_probe(
    center_params: dict[str, Any],
    *,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    direction: BlockEscapeDirection,
    radius: float,
    polarity: float,
) -> BlockEscapeProbe | None:
    """Apply one bounded block direction around a fixed round center."""

    coordinate_by_id = {
        coordinate.coordinate_id: coordinate for coordinate in _material_coordinates(coordinates)
    }
    candidate = copy.deepcopy(center_params)
    updates: dict[str, float] = {}
    for coordinate_id, sign in zip(direction.coordinate_ids, direction.signs):
        coordinate = coordinate_by_id.get(coordinate_id)
        if coordinate is None:
            continue
        step = float(steps[coordinate_id])
        before = coordinate.read(candidate)
        candidate = coordinate.write(
            candidate,
            before + float(polarity) * float(radius) * sign * step,
        )
        after = coordinate.read(candidate)
        if abs(after - before) > 1.0e-12 and step > 0.0:
            updates[coordinate_id] = (after - before) / step
    if not updates:
        return None
    return BlockEscapeProbe(candidate=candidate, normalized_updates=updates)


def build_block_escape_response_moves(
    center_params: dict[str, Any],
    *,
    center_features: Sequence[float] | None,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    radius: float,
    observations: Sequence[BlockEscapeObservation],
    damping: float,
    ridge: float,
    response_trust_radius: float | None = None,
    response_line_search_scales: Sequence[float] = (1.0,),
) -> list[BlockEscapeResponseMove]:
    """Reconstruct residual- and score-based moves from block secants."""

    moves: list[BlockEscapeResponseMove] = []
    scales = [
        float(scale)
        for scale in response_line_search_scales
        if math.isfinite(float(scale)) and abs(float(scale)) > 0.0
    ] or [1.0]
    for line_scale in scales:
        residual_move = _solve_residual_subspace_move(
            center_params,
            center_features=center_features,
            coordinates=coordinates,
            steps=steps,
            radius=radius,
            observations=observations,
            damping=float(damping) * line_scale,
            ridge=ridge,
            response_trust_radius=response_trust_radius,
        )
        if residual_move is not None and not any(
            move.candidate == residual_move.candidate for move in moves
        ):
            moves.append(residual_move)
        score_move = _solve_score_response_move(
            center_params,
            coordinates=coordinates,
            steps=steps,
            radius=radius,
            observations=observations,
            damping=float(damping) * line_scale,
            response_trust_radius=response_trust_radius,
        )
        if score_move is not None and not any(
            move.candidate == score_move.candidate for move in moves
        ):
            moves.append(score_move)
    return moves


def _solve_residual_subspace_move(
    center_params: dict[str, Any],
    *,
    center_features: Sequence[float] | None,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    radius: float,
    observations: Sequence[BlockEscapeObservation],
    damping: float,
    ridge: float,
    response_trust_radius: float | None,
) -> BlockEscapeResponseMove | None:
    if not center_features:
        return None
    try:
        import numpy as np
    except Exception:
        return None

    active = _material_coordinates(coordinates)
    feature_count = len(center_features)
    residual = np.asarray(center_features, dtype=np.float64)
    if residual.shape != (feature_count,) or not np.all(np.isfinite(residual)):
        return None
    secant_columns: list[Any] = []
    effective_directions: list[Any] = []
    valid_observations = 0
    for observation in observations:
        minus = observation.minus_features
        plus = observation.plus_features
        if minus is None or plus is None or len(minus) != feature_count or len(plus) != feature_count:
            continue
        column = (np.asarray(plus, dtype=np.float64) - np.asarray(minus, dtype=np.float64)) / 2.0
        if not np.all(np.isfinite(column)) or float(np.linalg.norm(column)) <= 1.0e-9:
            continue
        effective = _effective_direction(
            observation,
            coordinates=active,
            steps=steps,
            radius=radius,
        )
        if effective is None:
            continue
        secant_columns.append(column)
        effective_directions.append(np.asarray(effective, dtype=np.float64))
        valid_observations += 1
    if valid_observations < 2:
        return None

    secants = np.column_stack(secant_columns)
    ridge_root = math.sqrt(max(float(ridge), 0.0))
    if ridge_root > 0.0:
        matrix = np.vstack((secants, ridge_root * np.eye(valid_observations)))
        target = np.concatenate((-residual, np.zeros(valid_observations)))
    else:
        matrix = secants
        target = -residual
    try:
        coefficients, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    coefficient_limit = 2.0
    if response_trust_radius is not None and float(radius) > 0.0:
        configured_trust = float(response_trust_radius)
        if math.isfinite(configured_trust) and configured_trust > 0.0:
            coefficient_limit = max(coefficient_limit, configured_trust / float(radius))
    coefficients = np.clip(coefficients, -coefficient_limit, coefficient_limit)
    direction_matrix = np.vstack(effective_directions)
    updates = float(radius) * (direction_matrix.T @ coefficients)
    return _response_move_from_updates(
        center_params,
        method="residual_block_secant",
        coordinates=active,
        steps=steps,
        normalized_updates=updates.tolist(),
        radius=radius,
        damping=damping,
        response_trust_radius=response_trust_radius,
        direction_count=valid_observations,
        residual_feature_count=feature_count,
    )


def _solve_score_response_move(
    center_params: dict[str, Any],
    *,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    radius: float,
    observations: Sequence[BlockEscapeObservation],
    damping: float,
    response_trust_radius: float | None,
) -> BlockEscapeResponseMove | None:
    active = _material_coordinates(coordinates)
    response = [0.0] * len(active)
    valid_observations = 0
    for observation in observations:
        effective = _effective_direction(
            observation,
            coordinates=active,
            steps=steps,
            radius=radius,
        )
        if effective is None:
            continue
        score_delta = observation.plus_objective_score - observation.minus_objective_score
        if not math.isfinite(score_delta):
            continue
        for index, value in enumerate(effective):
            response[index] += score_delta * value
        valid_observations += 1
    max_response = max((abs(value) for value in response), default=0.0)
    if valid_observations < 2 or max_response <= 1.0e-12:
        return None
    normalized = [float(radius) * value / max_response for value in response]
    return _response_move_from_updates(
        center_params,
        method="scalar_score_response",
        coordinates=active,
        steps=steps,
        normalized_updates=normalized,
        radius=radius,
        damping=damping,
        response_trust_radius=response_trust_radius,
        direction_count=valid_observations,
        residual_feature_count=0,
    )


def _response_move_from_updates(
    center_params: dict[str, Any],
    *,
    method: str,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    normalized_updates: Sequence[float],
    radius: float,
    damping: float,
    response_trust_radius: float | None,
    direction_count: int,
    residual_feature_count: int,
) -> BlockEscapeResponseMove | None:
    finite_updates = [float(value) if math.isfinite(float(value)) else 0.0 for value in normalized_updates]
    max_abs = max((abs(value) for value in finite_updates), default=0.0)
    if max_abs <= 1.0e-12:
        return None
    configured_trust = float(response_trust_radius) if response_trust_radius is not None else 0.0
    trust_radius = (
        configured_trust
        if math.isfinite(configured_trust) and configured_trust > 0.0
        else max(float(radius), 0.25) * 1.25
    )
    raw_damping = float(damping)
    damping_sign = -1.0 if raw_damping < 0.0 else 1.0
    damping_magnitude = min(max(abs(raw_damping), 0.01), 1.0)
    scale = min(1.0, trust_radius / max_abs) * damping_sign * damping_magnitude
    candidate = copy.deepcopy(center_params)
    applied: dict[str, float] = {}
    for coordinate, raw_update in zip(coordinates, finite_updates):
        update = raw_update * scale
        if abs(update) <= 0.02:
            continue
        before = coordinate.read(candidate)
        candidate = coordinate.write(
            candidate,
            before + update * float(steps[coordinate.coordinate_id]),
        )
        after = coordinate.read(candidate)
        if abs(after - before) > 1.0e-12:
            applied[coordinate.coordinate_id] = (
                (after - before) / float(steps[coordinate.coordinate_id])
            )
    if len(applied) < 2:
        return None
    return BlockEscapeResponseMove(
        method=method,
        candidate=candidate,
        coordinate_ids=tuple(applied),
        normalized_updates=applied,
        direction_count=int(direction_count),
        residual_feature_count=int(residual_feature_count),
    )


def _effective_direction(
    observation: BlockEscapeObservation,
    *,
    coordinates: Sequence[FishSearchCoordinate],
    steps: dict[str, float],
    radius: float,
) -> list[float] | None:
    result: list[float] = []
    denominator_radius = 2.0 * float(radius)
    if denominator_radius <= 0.0:
        return None
    for coordinate in coordinates:
        step = float(steps[coordinate.coordinate_id])
        if step <= 0.0:
            return None
        minus = coordinate.read(observation.minus_params)
        plus = coordinate.read(observation.plus_params)
        result.append((plus - minus) / (denominator_radius * step))
    if not result or max(abs(value) for value in result) <= 1.0e-12:
        return None
    return result


def _material_coordinates(
    coordinates: Sequence[FishSearchCoordinate],
) -> list[FishSearchCoordinate]:
    return [coordinate for coordinate in coordinates if coordinate.group in MATERIAL_GROUPS]


def _hadamard_sign(row: int, column: int) -> float:
    return -1.0 if (int(row) & int(column)).bit_count() % 2 else 1.0


__all__ = [
    "BlockEscapeDirection",
    "BlockEscapeObservation",
    "BlockEscapeProbe",
    "BlockEscapeResponseMove",
    "DEFAULT_ESCAPE_PAIR_COUNT",
    "DEFAULT_ESCAPE_RADII",
    "apply_block_escape_probe",
    "build_block_escape_directions",
    "build_coordinate_escape_directions",
    "build_block_escape_response_moves",
]
