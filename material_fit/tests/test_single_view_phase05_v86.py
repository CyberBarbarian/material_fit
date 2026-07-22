from __future__ import annotations

from material_fit.experiments.single_view_phase05_v86 import (
    CONTROLLED_RECOVERY_TARGET_SCORE,
    _case_target_score,
    _controlled_search_param_names,
    _frozen_start_matches_target_state,
    _private_case_audit,
)
from material_fit.experiments.single_view_recovery_matrix import RecoveryStart
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
)


def _params() -> dict[str, object]:
    result: dict[str, object] = {}
    for coordinate in STRUCTURED_MATERIAL_ONLY_COORDINATES:
        if coordinate.component is None:
            result[coordinate.param_name] = (coordinate.low + coordinate.high) * 0.5
        else:
            vector = result.setdefault(coordinate.param_name, [0.0, 0.0, 0.0, 0.0])
            assert isinstance(vector, list)
            vector[coordinate.component] = (coordinate.low + coordinate.high) * 0.5
    return result


def test_private_phase05_audit_requires_axis_recovery_but_not_joint_identity() -> None:
    target = _params()
    coordinate = STRUCTURED_MATERIAL_ONLY_COORDINATES[0]
    start = coordinate.write(target, coordinate.read(target) + coordinate.initial_step)
    candidate = {
        "candidate_id": "normal|rim=1|blend_src=1",
        "defines": {},
        "render_states": {},
    }
    case = RecoveryStart(
        case_id="axis",
        family="single_axis",
        seed=1,
        params=start,
        perturbation={
            "changed_coordinates": [
                {
                    "coordinate": coordinate.coordinate_id,
                    "name": coordinate.param_name,
                }
            ]
        },
        discrete_candidate=candidate,
    )
    stage_report = {
        "start_score": 0.8,
        "best_score": 0.99,
        "discrete_recovery_passed": True,
        "timing": {"gate_passed": True},
    }

    recovered = _private_case_audit(
        case=case,
        target_params=target,
        best_params=target,
        stage_report=stage_report,
        success_score=0.98,
    )
    missed = _private_case_audit(
        case=case,
        target_params=target,
        best_params=start,
        stage_report=stage_report,
        success_score=0.98,
    )

    assert recovered["accepted"] is True
    assert recovered["parameter_identity_required"] is True
    assert missed["known_coordinate_recovery_passed"] is False
    assert _controlled_search_param_names(case) == [coordinate.param_name]


def test_controlled_cases_do_not_stop_at_the_joint_image_threshold() -> None:
    params = _params()
    candidate = {
        "candidate_id": "normal|rim=1|blend_src=1",
        "defines": {},
        "render_states": {},
    }
    controlled = RecoveryStart(
        case_id="axis",
        family="single_axis",
        seed=1,
        params=params,
        perturbation={"changed_coordinates": []},
        discrete_candidate=candidate,
    )
    joint = RecoveryStart(
        case_id="joint",
        family="joint_image_equivalence",
        seed=2,
        params=params,
        perturbation={"changed_coordinates": []},
        discrete_candidate=candidate,
    )

    assert _case_target_score(
        controlled,
        requested_target_score=0.98,
    ) == CONTROLLED_RECOVERY_TARGET_SCORE
    assert _case_target_score(joint, requested_target_score=0.98) == 0.98


def test_frozen_start_state_audit_uses_recovery_case_candidate() -> None:
    candidate = {
        "candidate_id": "normal|rim=1|blend_src=1",
        "defines": {},
        "render_states": {},
    }
    case = RecoveryStart(
        case_id="joint",
        family="joint_image_equivalence",
        seed=2,
        params=_params(),
        perturbation={"changed_coordinates": []},
        discrete_candidate=candidate,
    )

    assert _frozen_start_matches_target_state(case, candidate) is True
    assert _frozen_start_matches_target_state(
        case,
        {**candidate, "candidate_id": "flat|rim=0|blend_src=0"},
    ) is False


def test_private_phase05_audit_separates_image_and_hard_state_gates() -> None:
    target = _params()
    candidate = {
        "candidate_id": "normal|rim=1|blend_src=1",
        "defines": {},
        "render_states": {},
    }
    case = RecoveryStart(
        case_id="joint",
        family="joint_continuous",
        seed=2,
        params=target,
        perturbation={"changed_coordinates": []},
        discrete_candidate=candidate,
    )

    audit = _private_case_audit(
        case=case,
        target_params=target,
        best_params=target,
        stage_report={
            "start_score": 0.95,
            "best_score": 0.99988,
            "discrete_recovery_passed": False,
            "discrete_state_recovery_passed": True,
            "timing": {"gate_passed": True},
        },
        success_score=0.9999,
    )

    assert audit["image_recovery_passed"] is False
    assert audit["hard_state_recovery_passed"] is True
    assert audit["accepted"] is False
