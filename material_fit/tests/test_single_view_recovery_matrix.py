from __future__ import annotations

from material_fit.experiments.single_view_recovery_matrix import (
    build_identifiability_recovery_matrix,
    build_single_view_recovery_matrix,
)
from material_fit.optimizer.material_discrete_space import (
    build_legal_discrete_candidates,
    find_candidate_for_patch,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
)


def _target_params() -> dict[str, object]:
    params: dict[str, object] = {}
    for coordinate in STRUCTURED_MATERIAL_ONLY_COORDINATES:
        if coordinate.component is None:
            params[coordinate.param_name] = (coordinate.low + coordinate.high) * 0.5
        else:
            vector = params.setdefault(coordinate.param_name, [0.0, 0.0, 0.0, 0.0])
            assert isinstance(vector, list)
            vector[coordinate.component] = (coordinate.low + coordinate.high) * 0.5
    return params


def test_single_view_recovery_matrix_has_fixed_families_and_no_target_copy() -> None:
    params = _target_params()
    start_patch = {
        "defines": {
            "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
            "enabled": ["NORMALMAP"],
        },
        "render_states": {"s_Blend": 1, "s_BlendSrc": 1},
    }
    legal = build_legal_discrete_candidates(start_patch)
    target = find_candidate_for_patch(legal, start_patch)

    rows = build_single_view_recovery_matrix(
        params,
        target_candidate=target,
        legal_candidates=legal,
    )

    assert len(rows) == 12
    assert [row.family for row in rows].count("mild_continuous") == 4
    assert [row.family for row in rows].count("strong_continuous") == 4
    assert [row.family for row in rows].count("mixed_hard_state") == 4
    assert all(row.perturbation["changed_coordinate_count"] == 40 for row in rows)
    assert all(row.params != params for row in rows)
    assert all(
        row.discrete_candidate["candidate_id"] == target["candidate_id"]
        for row in rows[:8]
    )
    assert all(
        row.discrete_candidate["candidate_id"] != target["candidate_id"]
        for row in rows[8:]
    )


def test_identifiability_matrix_separates_parameter_and_image_acceptance() -> None:
    params = _target_params()
    start_patch = {
        "defines": {
            "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
            "enabled": ["NORMALMAP"],
        },
        "render_states": {"s_Blend": 1, "s_BlendSrc": 1},
    }
    legal = build_legal_discrete_candidates(start_patch)
    target = find_candidate_for_patch(legal, start_patch)

    rows = build_identifiability_recovery_matrix(
        params,
        target_candidate=target,
        legal_candidates=legal,
    )

    assert [row.family for row in rows] == [
        "single_axis",
        "single_axis",
        "identifiable_group",
        "joint_image_equivalence",
        "mixed_hard_state",
    ]
    assert [row.perturbation["changed_coordinate_count"] for row in rows[:3]] == [1, 1, 3]
    assert rows[2].case_id == "group_shadow_color"
    assert rows[3].perturbation["changed_coordinate_count"] == 40
    assert rows[4].perturbation["changed_coordinate_count"] == 40
    assert rows[4].discrete_candidate["candidate_id"] != target["candidate_id"]
