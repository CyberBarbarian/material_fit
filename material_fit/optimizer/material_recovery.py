"""Asset-independent helpers for continuous material perturbation recovery."""

from __future__ import annotations

import copy
import random
from typing import Any

from .structured_material_space import (
    structured_material_coordinates,
    structured_material_space_manifest,
)


PERTURBATION_PRESETS = {
    "tiny": 0.0001,
    "mild": 1.0,
    "medium": 1.5,
    "strong": 2.5,
}


def perturb_material_params(
    params: dict[str, Any],
    *,
    preset: str,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Perturb all 40 material coordinates while preserving scene state."""

    if preset not in PERTURBATION_PRESETS:
        raise ValueError(f"unsupported perturbation preset: {preset}")
    scale = PERTURBATION_PRESETS[preset]
    rng = random.Random(int(seed))
    result = copy.deepcopy(params)
    changes: list[dict[str, Any]] = []
    coordinates = structured_material_coordinates(params, material_only=True)
    for coordinate in coordinates:
        target_value = coordinate.read(result)
        step = coordinate.initial_step * scale
        direction = -1.0 if rng.random() < 0.5 else 1.0
        candidate_params = coordinate.write(result, target_value + direction * step)
        candidate_value = coordinate.read(candidate_params)
        if abs(candidate_value - target_value) <= 1.0e-12:
            candidate_params = coordinate.write(result, target_value - direction * step)
            candidate_value = coordinate.read(candidate_params)
        if abs(candidate_value - target_value) <= 1.0e-12:
            continue
        result = candidate_params
        changes.append(
            {
                "coordinate": coordinate.coordinate_id,
                "name": coordinate.param_name,
                "component": coordinate.component,
                "group": coordinate.group,
                "target_value": target_value,
                "start_value": candidate_value,
                "delta": candidate_value - target_value,
                "step": step,
                "bounds": [coordinate.low, coordinate.high],
            }
        )
    return result, {
        "profile": "structured_material_v1_material_only",
        "preset": preset,
        "seed": int(seed),
        "step_scale": scale,
        "changed_coordinate_count": len(changes),
        "changed_param_count": len({row["name"] for row in changes}),
        "scene_alignment_perturbed": False,
        "changed_coordinates": changes,
        "search_space": structured_material_space_manifest(params),
    }


def material_parameter_distance(
    target: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return bounded coordinate error for the 40 continuous material axes."""

    rows: dict[str, dict[str, Any]] = {}
    absolute: list[float] = []
    normalized: list[float] = []
    groups: dict[str, list[float]] = {}
    for coordinate in structured_material_coordinates(target, material_only=True):
        target_value = coordinate.read(target)
        candidate_value = coordinate.read(candidate)
        span = max(coordinate.high - coordinate.low, 1.0e-9)
        abs_error = abs(candidate_value - target_value)
        normalized_error = abs_error / span
        absolute.append(abs_error)
        normalized.append(normalized_error)
        groups.setdefault(coordinate.group, []).append(normalized_error)
        rows[coordinate.coordinate_id] = {
            "param": coordinate.param_name,
            "component": coordinate.component,
            "group": coordinate.group,
            "target": target_value,
            "value": candidate_value,
            "abs_error": abs_error,
            "normalized_abs_error": normalized_error,
        }
    return {
        "coordinate_count": len(absolute),
        "mean_abs_error": _mean(absolute),
        "max_abs_error": max(absolute) if absolute else 0.0,
        "mean_normalized_abs_error": _mean(normalized),
        "max_normalized_abs_error": max(normalized) if normalized else 0.0,
        "groups": {
            name: {
                "coordinate_count": len(values),
                "mean_normalized_abs_error": _mean(values),
                "max_normalized_abs_error": max(values),
            }
            for name, values in groups.items()
        },
    }, rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


__all__ = [
    "PERTURBATION_PRESETS",
    "material_parameter_distance",
    "perturb_material_params",
]
