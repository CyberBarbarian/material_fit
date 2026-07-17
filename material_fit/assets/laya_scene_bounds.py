"""Geometry-derived framing for Laya prefab asset profiles."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


Matrix3 = tuple[tuple[float, float, float], ...]
Vector3 = tuple[float, float, float]
IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class SceneBounds:
    center: Vector3
    extent: Vector3

    @property
    def radius(self) -> float:
        return math.sqrt(sum(value * value for value in self.extent))


def target_bounds_from_lh(path: str | Path, target_name: str) -> SceneBounds:
    scene_path = Path(path).expanduser().resolve()
    payload = json.loads(scene_path.read_text(encoding="utf-8-sig"))
    boxes: list[tuple[Vector3, Vector3]] = []
    found_target = _collect_target_bounds(
        payload,
        target_name=target_name,
        parent_matrix=IDENTITY,
        parent_translation=(0.0, 0.0, 0.0),
        inside_target=False,
        boxes=boxes,
    )
    if not found_target:
        raise ValueError(f"target node {target_name!r} is unavailable in {scene_path}")
    if not boxes:
        raise ValueError(f"target node {target_name!r} has no inline localBounds in {scene_path}")
    minimum = tuple(min(box[0][axis] for box in boxes) for axis in range(3))
    maximum = tuple(max(box[1][axis] for box in boxes) for axis in range(3))
    return SceneBounds(
        center=tuple((minimum[axis] + maximum[axis]) / 2.0 for axis in range(3)),
        extent=tuple((maximum[axis] - minimum[axis]) / 2.0 for axis in range(3)),
    )


def perspective_camera_distance(
    bounds: SceneBounds,
    *,
    width: int,
    height: int,
    vertical_field_of_view: float,
    margin: float = 1.08,
) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("capture dimensions must be positive")
    vertical_half = math.radians(float(vertical_field_of_view)) / 2.0
    horizontal_half = math.atan(math.tan(vertical_half) * (float(width) / float(height)))
    limiting_half = min(vertical_half, horizontal_half)
    if not 0.0 < limiting_half < math.pi / 2.0:
        raise ValueError(f"invalid vertical field of view: {vertical_field_of_view}")
    return bounds.radius / math.sin(limiting_half) * float(margin)


def _collect_target_bounds(
    node: Any,
    *,
    target_name: str,
    parent_matrix: Matrix3,
    parent_translation: Vector3,
    inside_target: bool,
    boxes: list[tuple[Vector3, Vector3]],
) -> bool:
    if not isinstance(node, dict):
        return False
    local_matrix, local_translation = _node_transform(node.get("transform"))
    world_matrix = _matrix_multiply(parent_matrix, local_matrix)
    world_translation = _vector_add(
        _matrix_vector(parent_matrix, local_translation), parent_translation
    )
    active = inside_target or str(node.get("name") or "") == target_name
    found_target = active
    if active:
        for bounds in _component_local_bounds(node.get("_$comp")):
            boxes.append(_transform_bounds(bounds, world_matrix, world_translation))
    for child in node.get("_$child") or []:
        found_target = _collect_target_bounds(
            child,
            target_name=target_name,
            parent_matrix=world_matrix,
            parent_translation=world_translation,
            inside_target=active,
            boxes=boxes,
        ) or found_target
    return found_target


def _component_local_bounds(components: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(components, list):
        return
    for component in components:
        yield from _find_local_bounds(component)


def _find_local_bounds(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        bounds = value.get("localBounds")
        if isinstance(bounds, dict):
            yield bounds
        for key, child in value.items():
            if key != "localBounds":
                yield from _find_local_bounds(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_local_bounds(child)


def _node_transform(raw: Any) -> tuple[Matrix3, Vector3]:
    transform = raw if isinstance(raw, dict) else {}
    position = _vector(transform.get("localPosition"), default=(0.0, 0.0, 0.0))
    scale = _vector(transform.get("localScale"), default=(1.0, 1.0, 1.0))
    quaternion = transform.get("localRotation")
    rotation = _quaternion_matrix(quaternion if isinstance(quaternion, dict) else {})
    matrix = tuple(
        tuple(rotation[row][column] * scale[column] for column in range(3))
        for row in range(3)
    )
    return matrix, position


def _quaternion_matrix(raw: dict[str, Any]) -> Matrix3:
    x = float(raw.get("x", 0.0) or 0.0)
    y = float(raw.get("y", 0.0) or 0.0)
    z = float(raw.get("z", 0.0) or 0.0)
    w = float(raw.get("w", 1.0) if raw.get("w") is not None else 1.0)
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length == 0.0:
        return IDENTITY
    x, y, z, w = x / length, y / length, z / length, w / length
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def _transform_bounds(
    raw: dict[str, Any], matrix: Matrix3, translation: Vector3
) -> tuple[Vector3, Vector3]:
    minimum = _vector(raw.get("min"), default=(0.0, 0.0, 0.0))
    maximum = _vector(raw.get("max"), default=(0.0, 0.0, 0.0))
    center = tuple((minimum[axis] + maximum[axis]) / 2.0 for axis in range(3))
    extent = tuple((maximum[axis] - minimum[axis]) / 2.0 for axis in range(3))
    world_center = _vector_add(_matrix_vector(matrix, center), translation)
    world_extent = tuple(
        sum(abs(matrix[row][column]) * extent[column] for column in range(3))
        for row in range(3)
    )
    return (
        tuple(world_center[axis] - world_extent[axis] for axis in range(3)),
        tuple(world_center[axis] + world_extent[axis] for axis in range(3)),
    )


def _vector(raw: Any, *, default: Vector3) -> Vector3:
    value = raw if isinstance(raw, dict) else {}
    return tuple(float(value.get(axis, fallback) or 0.0) for axis, fallback in zip("xyz", default))


def _matrix_multiply(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )


def _matrix_vector(matrix: Matrix3, vector: Sequence[float]) -> Vector3:
    return tuple(sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3))


def _vector_add(left: Sequence[float], right: Sequence[float]) -> Vector3:
    return tuple(left[index] + right[index] for index in range(3))


__all__ = ["SceneBounds", "perspective_camera_distance", "target_bounds_from_lh"]
