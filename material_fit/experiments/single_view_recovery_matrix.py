from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    normalize_discrete_candidate,
)
from material_fit.optimizer.material_recovery import perturb_material_params
from material_fit.optimizer.structured_material_space import structured_material_coordinates


RECOVERY_MATRIX_CONTRACT = "single_view_phase05_recovery_matrix_v1"
_MILD_SEEDS = (11, 23, 37, 53)
_STRONG_SEEDS = (71, 89, 107, 131)
_MIXED_SEEDS = (151, 173, 197, 223)
IDENTIFIABILITY_RECOVERY_MATRIX_CONTRACT = (
    "single_view_phase05_identifiability_recovery_matrix_v1"
)


@dataclass(frozen=True)
class RecoveryStart:
    case_id: str
    family: str
    seed: int
    params: dict[str, Any]
    perturbation: dict[str, Any]
    discrete_candidate: dict[str, Any]

    def manifest(self) -> dict[str, Any]:
        return {
            "contract": RECOVERY_MATRIX_CONTRACT,
            "case_id": self.case_id,
            "family": self.family,
            "seed": self.seed,
            "perturbation": copy.deepcopy(self.perturbation),
            "discrete_candidate": copy.deepcopy(self.discrete_candidate),
        }


def build_single_view_recovery_matrix(
    target_params: dict[str, Any],
    *,
    target_candidate: Mapping[str, Any],
    legal_candidates: Sequence[Mapping[str, Any]],
) -> list[RecoveryStart]:
    """Build the fixed 4 mild, 4 strong, and 4 mixed-state recovery cases."""

    normalized_target = normalize_discrete_candidate(target_candidate)
    normalized_legal = [normalize_discrete_candidate(row) for row in legal_candidates]
    target_id = normalized_target["candidate_id"]
    candidate_ids = [row["candidate_id"] for row in normalized_legal]
    if target_id not in candidate_ids:
        raise ValueError("target hard state is outside the legal candidate space")
    alternatives = [row for row in normalized_legal if row["candidate_id"] != target_id]
    if not alternatives:
        raise ValueError("recovery matrix requires at least one non-target hard state")

    rows: list[RecoveryStart] = []
    rows.extend(
        _continuous_cases(
            target_params,
            candidate=normalized_target,
            family="mild_continuous",
            preset="mild",
            seeds=_MILD_SEEDS,
        )
    )
    rows.extend(
        _continuous_cases(
            target_params,
            candidate=normalized_target,
            family="strong_continuous",
            preset="strong",
            seeds=_STRONG_SEEDS,
        )
    )
    for index, seed in enumerate(_MIXED_SEEDS):
        params, perturbation = perturb_material_params(
            target_params,
            preset="strong",
            seed=seed,
        )
        candidate = alternatives[index % len(alternatives)]
        rows.append(
            RecoveryStart(
                case_id=f"mixed_hard_state_seed{seed}",
                family="mixed_hard_state",
                seed=seed,
                params=attach_discrete_candidate(params, candidate),
                perturbation={
                    **perturbation,
                    "target_candidate_id": target_id,
                    "start_candidate_id": candidate["candidate_id"],
                    "hard_state_perturbed": True,
                },
                discrete_candidate=candidate,
            )
        )
    if len(rows) != 12 or len({row.case_id for row in rows}) != 12:
        raise AssertionError("single-view recovery matrix must contain 12 unique cases")
    return rows


def build_identifiability_recovery_matrix(
    target_params: dict[str, Any],
    *,
    target_candidate: Mapping[str, Any],
    legal_candidates: Sequence[Mapping[str, Any]],
) -> list[RecoveryStart]:
    """Build controlled axis, group, joint, and hard-state recovery cases."""

    normalized_target = normalize_discrete_candidate(target_candidate)
    normalized_legal = [normalize_discrete_candidate(row) for row in legal_candidates]
    if normalized_target["candidate_id"] not in {
        row["candidate_id"] for row in normalized_legal
    }:
        raise ValueError("target hard state is outside the legal candidate space")
    coordinates = {
        coordinate.coordinate_id: coordinate
        for coordinate in structured_material_coordinates(target_params, material_only=True)
    }
    rows = [
        _controlled_case(
            target_params,
            target_candidate=normalized_target,
            coordinates=coordinates,
            case_id="axis_gamma_positive",
            family="single_axis",
            seed=11,
            coordinate_directions={"u_GammaPower": 1.0},
        ),
        _controlled_case(
            target_params,
            target_candidate=normalized_target,
            coordinates=coordinates,
            case_id="axis_emission_negative",
            family="single_axis",
            seed=23,
            coordinate_directions={"u_EmissionPow": -1.0},
        ),
        _controlled_case(
            target_params,
            target_candidate=normalized_target,
            coordinates=coordinates,
            case_id="group_shadow_color",
            family="identifiable_group",
            seed=37,
            coordinate_directions={
                "u_ShadowColor1[0]": 1.0,
                "u_ShadowColor1[1]": -1.0,
                "u_ShadowColor1[2]": 1.0,
            },
        ),
    ]

    joint_params, joint_report = perturb_material_params(
        target_params,
        preset="mild",
        seed=53,
    )
    rows.append(
        RecoveryStart(
            case_id="joint_mild_seed53",
            family="joint_image_equivalence",
            seed=53,
            params=attach_discrete_candidate(joint_params, normalized_target),
            perturbation={
                **joint_report,
                "target_candidate_id": normalized_target["candidate_id"],
                "start_candidate_id": normalized_target["candidate_id"],
                "hard_state_perturbed": False,
                "acceptance_basis": "image_equivalence_not_exact_40d_parameter_identity",
            },
            discrete_candidate=copy.deepcopy(normalized_target),
        )
    )

    alternatives = [
        row
        for row in normalized_legal
        if row["candidate_id"] != normalized_target["candidate_id"]
    ]
    if not alternatives:
        raise ValueError("mixed recovery requires at least one alternate hard state")
    alternate = max(
        alternatives,
        key=lambda row: _candidate_difference_count(normalized_target, row),
    )
    mixed_params, mixed_report = perturb_material_params(
        target_params,
        preset="mild",
        seed=71,
    )
    rows.append(
        RecoveryStart(
            case_id="mixed_mild_seed71",
            family="mixed_hard_state",
            seed=71,
            params=attach_discrete_candidate(mixed_params, alternate),
            perturbation={
                **mixed_report,
                "target_candidate_id": normalized_target["candidate_id"],
                "start_candidate_id": alternate["candidate_id"],
                "hard_state_perturbed": True,
                "acceptance_basis": "image_and_observational_hard_state_equivalence",
            },
            discrete_candidate=copy.deepcopy(alternate),
        )
    )
    return rows


def _controlled_case(
    target_params: dict[str, Any],
    *,
    target_candidate: dict[str, Any],
    coordinates: Mapping[str, Any],
    case_id: str,
    family: str,
    seed: int,
    coordinate_directions: Mapping[str, float],
) -> RecoveryStart:
    params = copy.deepcopy(target_params)
    changes: list[dict[str, Any]] = []
    for coordinate_id, direction in coordinate_directions.items():
        coordinate = coordinates[coordinate_id]
        target_value = coordinate.read(params)
        candidate = coordinate.write(
            params,
            target_value + float(direction) * coordinate.initial_step,
        )
        start_value = coordinate.read(candidate)
        if abs(start_value - target_value) <= 1.0e-12:
            candidate = coordinate.write(
                params,
                target_value - float(direction) * coordinate.initial_step,
            )
            start_value = coordinate.read(candidate)
        if abs(start_value - target_value) <= 1.0e-12:
            raise ValueError(f"controlled perturbation did not move {coordinate_id}")
        params = candidate
        changes.append(
            {
                "coordinate": coordinate.coordinate_id,
                "name": coordinate.param_name,
                "component": coordinate.component,
                "target_value": target_value,
                "start_value": start_value,
                "delta": start_value - target_value,
                "bounds": [coordinate.low, coordinate.high],
            }
        )
    return RecoveryStart(
        case_id=case_id,
        family=family,
        seed=seed,
        params=attach_discrete_candidate(params, target_candidate),
        perturbation={
            "contract": IDENTIFIABILITY_RECOVERY_MATRIX_CONTRACT,
            "changed_coordinate_count": len(changes),
            "changed_coordinates": changes,
            "target_candidate_id": target_candidate["candidate_id"],
            "start_candidate_id": target_candidate["candidate_id"],
            "hard_state_perturbed": False,
            "acceptance_basis": "known_changed_coordinates_and_image_equivalence",
        },
        discrete_candidate=copy.deepcopy(target_candidate),
    )


def _candidate_difference_count(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    left_defines = left.get("defines", {})
    right_defines = right.get("defines", {})
    left_states = left.get("render_states", {})
    right_states = right.get("render_states", {})
    return sum(
        left_defines.get(key) != right_defines.get(key)
        for key in set(left_defines) | set(right_defines)
    ) + sum(
        left_states.get(key) != right_states.get(key)
        for key in set(left_states) | set(right_states)
    )


def _continuous_cases(
    target_params: dict[str, Any],
    *,
    candidate: dict[str, Any],
    family: str,
    preset: str,
    seeds: Sequence[int],
) -> list[RecoveryStart]:
    rows: list[RecoveryStart] = []
    for seed in seeds:
        params, perturbation = perturb_material_params(
            target_params,
            preset=preset,
            seed=seed,
        )
        rows.append(
            RecoveryStart(
                case_id=f"{family}_seed{seed}",
                family=family,
                seed=seed,
                params=attach_discrete_candidate(params, candidate),
                perturbation={
                    **perturbation,
                    "target_candidate_id": candidate["candidate_id"],
                    "start_candidate_id": candidate["candidate_id"],
                    "hard_state_perturbed": False,
                },
                discrete_candidate=copy.deepcopy(candidate),
            )
        )
    return rows


__all__ = [
    "RECOVERY_MATRIX_CONTRACT",
    "IDENTIFIABILITY_RECOVERY_MATRIX_CONTRACT",
    "RecoveryStart",
    "build_identifiability_recovery_matrix",
    "build_single_view_recovery_matrix",
]
