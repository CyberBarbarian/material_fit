import json
from pathlib import Path

import pytest

from material_fit.assets.stage2_sampling import resolve_stage2_sampling
from material_fit.experiments.material_cross_engine_stage2_single_view import (
    DEFAULT_ITERATIONS,
    DEFAULT_VIEW_ID,
    FINAL_REGISTERED_PATTERN_MAX_PROPOSALS,
    JOINT_PROFILE,
    MAXIMUM_ACCEPTANCE_DISTANCE_RATIO,
    ONLINE_DISTS_DEVICE,
    ONLINE_DISTS_IMAGE_SIZE,
    ONLINE_DISTS_TORCH_THREADS,
    ONLINE_SCORE_HEIGHT,
    ONLINE_SCORE_WIDTH,
    OPTIMIZER_ID,
    ROBUST_SCORE_METRIC,
    _adapt_joint_policy_for_single_view_material_only,
    _select_reference_view,
    _single_view_registration,
)
from material_fit.experiments.stage2_archive import (
    FINAL_ACCEPTANCE_RERANK_TOP_K,
    _browser_fit_score,
    _load_archive_rerank_candidates,
)
from material_fit.experiments.stage2_scoring import (
    _comparison_label,
    _load_acceptance_scorer_sanity,
)
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V42,
    JOINT_PROFILE_V86,
    MAX_OPTIMIZER_ITERATIONS,
    joint_profile_policy,
)
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    BROWSER_SCORE_OVERRIDE_PARAM,
    attach_discrete_candidate,
    build_legal_discrete_candidates,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.dists_score import DISTS_ALIGNED_RGB_V3_METRIC


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_single_view_helpers_select_only_requested_back_view() -> None:
    views = (
        {"view_id": DEFAULT_VIEW_ID, "reference_file_name": "back.png"},
        {"view_id": "v001_yaw45_pitch0", "reference_file_name": "side.png"},
    )
    selected = _select_reference_view(views, DEFAULT_VIEW_ID)
    registration = _single_view_registration(
        {
            "mode": "frozen_per_view_similarity",
            "output_size": [900, 700],
            "transforms": [
                {"view_id": DEFAULT_VIEW_ID, "scale": 1.2, "dx": 1.0, "dy": 2.0},
                {"view_id": "v001_yaw45_pitch0", "scale": 1.3, "dx": 3.0, "dy": 4.0},
            ],
        },
        DEFAULT_VIEW_ID,
    )

    assert selected["reference_file_name"] == "back.png"
    assert [item["view_id"] for item in registration["transforms"]] == [DEFAULT_VIEW_ID]


def test_single_view_helpers_fail_closed_for_unknown_view() -> None:
    with pytest.raises(ValueError, match="unknown Stage 2 view"):
        _select_reference_view(tuple(), DEFAULT_VIEW_ID)


def test_single_view_keeps_the_full_v86_search_contract() -> None:
    spec = resolve_stage2_sampling(REPO_ROOT, "turtle", material_variant="start")
    start_patch = material_patch_from_lmat(spec.material_path)
    candidates = build_legal_discrete_candidates(start_patch)
    policy = joint_profile_policy(JOINT_PROFILE)

    assert OPTIMIZER_ID == "material_discrete_joint"
    assert JOINT_PROFILE == JOINT_PROFILE_V86
    assert DEFAULT_ITERATIONS == MAX_OPTIMIZER_ITERATIONS == 1499
    assert ROBUST_SCORE_METRIC == "foreground_dists_aligned_rgb_v6"
    assert (ONLINE_SCORE_WIDTH, ONLINE_SCORE_HEIGHT) == (450, 350)
    assert ONLINE_DISTS_IMAGE_SIZE == 256
    assert ONLINE_DISTS_DEVICE == "auto"
    assert ONLINE_DISTS_TORCH_THREADS == 10
    assert FINAL_ACCEPTANCE_RERANK_TOP_K == 20
    assert FINAL_REGISTERED_PATTERN_MAX_PROPOSALS == 80
    assert MAXIMUM_ACCEPTANCE_DISTANCE_RATIO == pytest.approx(0.85)
    assert policy["max_scored_candidates"] == 1500
    assert len(candidates) == 16
    assert len(STRUCTURED_MATERIAL_ONLY_COORDINATES) == 40
    assert len(STRUCTURED_SCENE_PARAM_NAMES) == 6


def test_single_view_policy_uses_inverse_search_then_acceptance_objective() -> None:
    policy = joint_profile_policy(JOINT_PROFILE_V42)

    adapted, report = _adapt_joint_policy_for_single_view_material_only(policy)

    assert adapted["optimization_score_metric"] == DISTS_ALIGNED_RGB_V3_METRIC
    assert adapted["rescan_browser_score_overrides"] == [
        {},
        {"metric": ROBUST_SCORE_METRIC},
    ]
    assert report["optimization_score_metric"] == DISTS_ALIGNED_RGB_V3_METRIC
    assert report["acceptance_score_metric"] == ROBUST_SCORE_METRIC
    assert report["objective_changes_during_search"] is True


def test_acceptance_rerank_uses_scored_existing_materials_and_deduplicates(
    tmp_path: Path,
) -> None:
    spec = resolve_stage2_sampling(REPO_ROOT, "turtle", material_variant="start")
    start_patch = material_patch_from_lmat(spec.material_path)
    discrete = build_legal_discrete_candidates(start_patch)[0]

    def params(value: float) -> dict[str, object]:
        result = attach_discrete_candidate({"u_GammaPower": value}, discrete)
        result[BROWSER_SCORE_OVERRIDE_PARAM] = {"metric": ROBUST_SCORE_METRIC}
        return result

    archive = tmp_path / "optimizer_candidate_archive.json"
    archive.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "rank": 1,
                        "iteration": 9,
                        "fit_score": 0.9,
                        "scored_params": params(0.4),
                        "candidate_params": params(9.0),
                    },
                    {
                        "rank": 2,
                        "iteration": 10,
                        "fit_score": 0.8,
                        "scored_params": params(0.5),
                    },
                    {
                        "rank": 3,
                        "iteration": 11,
                        "fit_score": 0.7,
                        "scored_params": params(0.6),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    candidates = _load_archive_rerank_candidates(
        archive,
        optimizer_best_params=params(0.4),
        top_k=2,
    )

    assert [item["params"]["u_GammaPower"] for item in candidates] == [0.4, 0.5]
    assert all(
        BROWSER_SCORE_OVERRIDE_PARAM not in item["params"] for item in candidates
    )
    assert candidates[0]["archive_rank"] == 0
    assert candidates[1]["archive_rank"] == 2


def test_registered_browser_score_accepts_persisted_report_shape() -> None:
    result = {
        "status": "ok",
        "report": {"browser_score": {"fit_score": 0.75}},
    }

    assert _browser_fit_score(result) == pytest.approx(0.75)


def test_comparison_label_exposes_independent_dists_score() -> None:
    label = _comparison_label("Human-adjusted Laya", {"status": "ok", "score": 0.8311208})

    assert label == "Human-adjusted Laya | DISTS 0.831121"


def test_acceptance_scorer_sanity_prefers_current_report(tmp_path: Path) -> None:
    legacy = tmp_path / "frozen_confidence_scorer_sanity.json"
    current = tmp_path / "stage2_scorer_sanity.json"
    legacy.write_text('{"passed": false}', encoding="utf-8")
    current.write_text('{"passed": true}', encoding="utf-8")

    assert _load_acceptance_scorer_sanity(tmp_path) == {"passed": True}


def test_single_view_uses_the_same_staged_mixed_space_policy_as_stage1() -> None:
    policy = joint_profile_policy("v85_budget1500_v4_portfolio_scene_refine")

    adapted, report = _adapt_joint_policy_for_single_view_material_only(policy)
    assert report["single_view_spatial_residual_override"] is False
    assert report["scene_coordinates_searchable"] is True
    assert report["scene_coordinates_searchable_stage"] == (
        "pre_rescan_dedicated_scene_and_post_rescan_joint_then_frozen_material"
    )
    assert report["scene_coordinates_frozen_before_material_refine"] is True
    assert adapted["initial_continuous_warmup"] == {}
    assert adapted["continuous"]["frozen_param_names"] == []
    assert adapted["post_rescan_branch_race"]["enabled"] is False
    continuous_stages = adapted["continuous"]["cascade"]["stages"]
    assert continuous_stages[1]["name"] == "dedicated_scene_calibration"
    final = adapted["continuous_after_final_rescan"]
    assert final["strategy"] == "material_jacobian_cascade"
    stages = final["cascade"]["stages"]
    assert stages[0]["frozen_param_names"] == []
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        stages[1]["frozen_param_names"]
    )
    assert stages[1].get("optimizer", "jacobian") == "jacobian"
