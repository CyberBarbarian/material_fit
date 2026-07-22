from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from material_fit.assets.material_stage1 import resolve_material_stage1_asset
from material_fit.experiments.material_human_reference_stage1 import (
    JOINT_PROFILE_V30,
    JOINT_PROFILE_V42,
    JOINT_PROFILE_V85,
    JOINT_PROFILE_V86,
    STAGE1_SEARCH_PARAM_NAMES,
    V83_MAX_OPTIMIZER_ITERATIONS,
    _artifact_resolution,
    _build_fit_config,
    _finite_score,
    _joint_profile_policy,
    _joint_profile_runtime_contract,
    _optimizer_boundary_report,
    _optimizer_score_resolution,
    _parse_args,
    _resolve_v86_initial_score_route,
    _single_view_material_only_search,
    _score_metric_after_route,
    _write_optimizer_profile,
    _write_profile,
)
from material_fit.experiments.single_view_v86_policy import (
    adapt_v86_policy_for_material_only,
)
from material_fit.experiments.stage1_reporting import _discrete_recovery_report
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    build_legal_discrete_candidates,
    compress_observationally_equivalent_candidates,
    find_candidate_for_patch,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.dists_score import DISTS_METRIC


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_single_view_uses_requested_scene_scope() -> None:
    assert _single_view_material_only_search(
        view_count=1,
        jacobian_search_scope="all",
    ) is False
    assert _single_view_material_only_search(
        view_count=1,
        jacobian_search_scope="material",
    ) is True
    assert _single_view_material_only_search(
        view_count=8,
        jacobian_search_scope="material",
    ) is False


def test_single_view_keeps_the_requested_unified_score_after_routing() -> None:
    assert _score_metric_after_route(
        single_view=True,
        requested_metric="foreground_dists_material_v1",
        routed_metric="cross_engine_foreground_components_v5_strict_core",
    ) == "foreground_dists_material_v1"
    assert _score_metric_after_route(
        single_view=False,
        requested_metric="foreground_dists_material_v1",
        routed_metric="cross_engine_foreground_components_v5_strict_core",
    ) == "cross_engine_foreground_components_v5_strict_core"


def test_discrete_state_recovery_is_independent_of_image_threshold() -> None:
    candidate = {
        "candidate_id": "normal=legacy_y_invert_only|rim=0|blend_src=1",
        "defines": {},
        "render_states": {},
    }
    report = _discrete_recovery_report(
        start_candidate=candidate,
        target_candidate=candidate,
        best_candidate=candidate,
        best_score=0.99988,
        target_discrete_audit_score=0.99988,
        success_score=0.9999,
    )

    assert report["state_recovery_passed"] is True
    assert report["passed"] is False


def _write_material(path: Path, *, target: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "LAYAMATERIAL:04",
                "props": {
                    "type": "Custom/Test",
                    "renderQueue": 2000,
                    "materialRenderMode": 0,
                    "s_BlendSrc": 0 if target else 1,
                    "s_DepthWrite": True,
                    "defines": (
                        ["NORMALMAP", "RIMSMOOTHNESS"]
                        if target
                        else ["NORMALMAP_Y_INVERT"]
                    ),
                    "textures": [
                        {"name": "u_MainTex", "path": "target" if target else "start"}
                    ],
                    "u_Value": 0.9 if target else 0.1,
                    "u_Toggle": target,
                },
            }
        ),
        encoding="utf-8",
    )


def test_discrete_alignment_preserves_start_continuous_values_and_textures(
    tmp_path: Path,
) -> None:
    start = tmp_path / "start.lmat"
    target = tmp_path / "target.lmat"
    output = tmp_path / "aligned.lmat"
    _write_material(start, target=False)
    _write_material(target, target=True)

    report = lmat_io.write_discrete_aligned_lmat(start, target, output)
    props = lmat_io.get_props(lmat_io.load_lmat(output))

    assert props["defines"] == ["NORMALMAP", "RIMSMOOTHNESS"]
    assert props["s_BlendSrc"] == 0
    assert props["u_Toggle"] is True
    assert props["u_Value"] == 0.1
    assert props["textures"] == [{"name": "u_MainTex", "path": "start"}]
    assert report["continuous_uniforms_copied_from_target"] is False
    assert report["textures_copied_from_target"] is False


@pytest.mark.parametrize(
    ("asset_id", "expected_scene", "expected_start", "expected_target"),
    [
        ("fish", "game.ls", "1504_new_test.lmat", "1504_body.lmat"),
        ("turtle", "1506_start.lh", "1506_test.lmat", "1506_mat.lmat"),
        ("crocodile", "1503.lh", "1503_test.lmat", "1503_body.lmat"),
    ],
)
def test_stage1_asset_adapters_are_self_contained_and_static(
    asset_id: str,
    expected_scene: str,
    expected_start: str,
    expected_target: str,
) -> None:
    asset = resolve_material_stage1_asset(REPO_ROOT, asset_id)

    assert asset.scene_path.name == expected_scene
    assert asset.start_material_path.name == expected_start
    assert asset.target_material_path.name == expected_target
    assert asset.start_material_path != asset.target_material_path
    assert asset.project_root.is_relative_to(REPO_ROOT / "examples")
    assert asset.profile["capture_defaults"]["animation_mode"] == "disabled"
    assert len(asset.profile["capture_defaults"]["views"]) == 8
    assert "fixed_animation_state" not in asset.profile["capture_defaults"]
    assert lmat_io.extract_textures(lmat_io.load_lmat(asset.start_material_path)) == (
        lmat_io.extract_textures(lmat_io.load_lmat(asset.target_material_path))
    )


def test_v86_is_the_only_public_profile_and_routes_without_asset_names() -> None:
    args = _parse_args(["--asset", "fish"])
    policy = _joint_profile_policy(JOINT_PROFILE_V86)
    routes = policy["initial_score_strategy_routes"]

    assert args.joint_profile == JOINT_PROFILE_V86
    assert args.iterations == V83_MAX_OPTIMIZER_ITERATIONS == 1499
    assert policy["max_scored_candidates"] == 1500
    assert [route["budget_profile"] for route in routes] == [
        JOINT_PROFILE_V85,
        JOINT_PROFILE_V42,
        JOINT_PROFILE_V30,
    ]
    serialized = json.dumps(routes)
    assert all(name not in serialized for name in ("fish", "turtle", "crocodile"))


def test_stage1_cli_exposes_pattern_initial_grid_points() -> None:
    args = _parse_args(
        [
            "--asset",
            "fish",
            "--pattern-initial-grid-points",
            "5",
            "--restrict-discrete-candidates-to-start",
        ]
    )

    assert args.pattern_initial_grid_points == 5
    assert args.restrict_discrete_candidates_to_start is True


def test_v86_runtime_contract_rejects_more_than_1499_proposals() -> None:
    policy = _joint_profile_policy(JOINT_PROFILE_V86)
    with pytest.raises(ValueError, match="initial material render plus proposals"):
        _joint_profile_runtime_contract(
            profile=JOINT_PROFILE_V86,
            policy=policy,
            iterations=1500,
            score_metric="cross_engine_foreground_components_v3",
            score_width=720,
            score_height=0,
            residual_grid_size=16,
            residual_sketch_size=128,
        )


@pytest.mark.parametrize(
    (
        "initial_score",
        "asset_profile",
        "expected_route",
        "expected_profile",
        "expected_metric",
        "expected_resolution",
        "expected_reference_resolution",
        "expected_equivalence",
    ),
    [
        (
            0.719121,
            {"width": 800, "height": 484},
            "low_initial_score",
            JOINT_PROFILE_V85,
            "cross_engine_foreground_components_v5_strict_core",
            (400, 242),
            (400, 242),
            True,
        ),
        (
            0.774743,
            {"width": 900, "height": 700},
            "medium_initial_score",
            JOINT_PROFILE_V42,
            "cross_engine_foreground_components_v3",
            (720, 560),
            (400, 311),
            True,
        ),
        (
            0.871293,
            {"width": 900, "height": 700},
            "high_initial_score",
            JOINT_PROFILE_V30,
            "cross_engine_foreground_components_v4",
            (544, 423),
            (544, 423),
            False,
        ),
    ],
)
def test_v86_resolves_child_from_initial_png_score(
    initial_score: float,
    asset_profile: dict,
    expected_route: str,
    expected_profile: str,
    expected_metric: str,
    expected_resolution: tuple[int, int],
    expected_reference_resolution: tuple[int, int],
    expected_equivalence: bool,
) -> None:
    (
        selected_profile,
        selected_policy,
        selected_iterations,
        selected_metric,
        selected_width,
        selected_height,
        _residual_grid,
        _residual_sketch,
        report,
    ) = _resolve_v86_initial_score_route(
        policy=_joint_profile_policy(JOINT_PROFILE_V86),
        initial_score=initial_score,
        asset_profile=asset_profile,
        requested_iterations=1499,
        score_metric="cross_engine_foreground_components_v3",
        score_width=720,
        score_height=0,
        residual_grid_size=16,
        residual_sketch_size=128,
    )
    assert selected_profile == expected_profile
    assert selected_iterations == 1499
    assert selected_metric == expected_metric
    assert (selected_width, selected_height) == expected_resolution
    assert tuple(report["selected_reference_resolution"]) == expected_reference_resolution
    assert report["route_id"] == expected_route
    assert report["selected_max_scored_candidates"] == 1500
    assert selected_policy["max_scored_candidates"] == 1500
    assert selected_policy["discrete_observation_equivalence"] is expected_equivalence
    assert report["asset_id_visible"] is False
    assert report["target_params_visible"] is False

    if expected_route == "high_initial_score":
        assert selected_policy["rescan_at"] == [650]
        assert selected_policy["max_rescans"] == 1
        assert selected_policy["post_rescan_branch_race"]["enabled"] is False
        assert selected_policy["planned_proposal_budget"]["total"] == 1498
        assert report["late_common_state_rescan"]["candidate_count"] == 16


def test_materialized_medium_route_keeps_png_only_boundary(tmp_path: Path) -> None:
    asset = resolve_material_stage1_asset(REPO_ROOT, "fish")
    profile = _write_profile(asset, tmp_path / "inputs/asset_profile.json")
    start_patch = material_patch_from_lmat(asset.start_material_path)
    candidates = build_legal_discrete_candidates(start_patch)
    start_candidate = find_candidate_for_patch(candidates, start_patch)
    (
        selected_profile,
        selected_policy,
        _selected_iterations,
        selected_metric,
        selected_width,
        selected_height,
        residual_grid,
        residual_sketch,
        _report,
    ) = _resolve_v86_initial_score_route(
        policy=_joint_profile_policy(JOINT_PROFILE_V86),
        initial_score=0.774743,
        asset_profile=asset.profile,
        requested_iterations=1499,
        score_metric="cross_engine_foreground_components_v3",
        score_width=720,
        score_height=0,
        residual_grid_size=16,
        residual_sketch_size=128,
    )
    selected_policy, _adaptation = adapt_v86_policy_for_material_only(
        selected_policy,
        scene_searchable=False,
    )

    config = _build_fit_config(
        asset=asset,
        profile_path=profile,
        run_dir=tmp_path / "run",
        start_material_path=asset.start_material_path,
        target_dir=tmp_path / "target_render",
        optimizer_start_patch=start_patch,
        discrete_candidates=candidates,
        discrete_equivalence_report={},
        start_candidate=start_candidate,
        target_score=0.995,
        optimizer="material_discrete_joint",
        warmup_iterations=1000,
        block_iterations=400,
        block_population_size=16,
        refine_iterations=800,
        node_modules=None,
        views=asset.profile["capture_defaults"]["views"],
        joint_profile=selected_profile,
        joint_policy_override=selected_policy,
        optimization_score_metric=_adaptation["optimization_score_metric"],
        browser_score_width=selected_width,
        browser_score_height=selected_height,
        residual_grid_size=residual_grid,
        residual_sketch_size=residual_sketch,
        material_only=True,
    )
    boundary = _optimizer_boundary_report(
        config,
        private_dir=tmp_path / "private_audit",
        target_material_path=asset.target_material_path,
    )

    assert boundary["passed"] is True
    assert set(config["search_param_names"]).isdisjoint(STRUCTURED_SCENE_PARAM_NAMES)
    assert len(config["material_discrete_joint"]["candidates"]) == 16
    assert len(config["material_discrete_joint"]["initial_candidate_ids"]) == 16
    assert config["material_discrete_joint"]["max_scored_candidates"] == 1500
    assert config["material_discrete_joint"]["activation_selects_initial_winner"] is True
    assert config["material_discrete_joint"]["activation_commits_initial_seed"] is False
    assert config["material_discrete_joint"][
        "skip_initial_discrete_probes_when_activation_selects"
    ] is True
    assert config["material_discrete_joint"]["round_widths"] == [1]
    assert config["material_discrete_joint"]["round_budgets"] == [1]
    assert config["material_discrete_joint"]["round_sigmas"] == [0.18]
    assert config["material_discrete_joint"]["branch_strategy"] == "cmaes"
    assert config["material_discrete_joint"]["rescan_at"] == [110, 476]
    assert config["material_discrete_joint"]["rescan_candidate_modes"] == [
        "initial_representatives",
        "initial_representatives",
    ]
    assert list(
        config["material_discrete_joint"]["rescan_browser_score_overrides"]
    ) == []
    assert config["material_discrete_joint"]["minimum_final_refine_proposals"] == 0
    assert config["material_discrete_joint"]["initial_score_rescan_schedule"] == {}
    assert config["material_discrete_joint"]["restart_continuous_after_rescan"] is True
    assert config["material_discrete_joint"][
        "restart_continuous_after_first_rescan"
    ] is False
    warmup = config["material_discrete_joint"]["initial_continuous_warmup"]
    assert warmup["max_proposals"] == 110
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        warmup["frozen_param_names"]
    )
    continuous = config["material_discrete_joint"]["continuous"]
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        continuous["frozen_param_names"]
    )
    final = config["material_discrete_joint"]["continuous_after_final_rescan"]
    assert final["strategy"] == "material_coordinate_pattern"
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        final["frozen_param_names"]
    )
    assert final["pattern"]["active_coordinate_count"] == 16
    for route in config["material_discrete_joint"][
        "planned_proposal_budget"
    ].values():
        assert route["total"] == 1498
    assert config["material_discrete_joint"]["post_rescan_axis_response_scan"][
        "enabled"
    ] is False
    race = config["material_discrete_joint"]["post_rescan_branch_race"]
    assert race["enabled"] is False
    assert config["stage1_optimizer_contract"]["target_params_visible_to_optimizer"] is False
    assert asset.target_material_path.name not in json.dumps(config)


def test_optimizer_score_resolution_preserves_asset_aspect_ratio() -> None:
    assert _optimizer_score_resolution(
        {"width": 900, "height": 700}, requested_width=720, requested_height=0
    ) == (720, 560)
    assert _optimizer_score_resolution(
        {"width": 800, "height": 484}, requested_width=400, requested_height=0
    ) == (400, 242)
    assert _optimizer_score_resolution(
        {"width": 800, "height": 484}, requested_width=450, requested_height=0
    ) == (450, 272)


def test_controlled_search_subset_is_not_overwritten_by_material_scope(
    tmp_path: Path,
) -> None:
    asset = resolve_material_stage1_asset(REPO_ROOT, "fish")
    profile = _write_profile(asset, tmp_path / "inputs/asset_profile.json")
    start_patch = material_patch_from_lmat(asset.start_material_path)
    config = _build_fit_config(
        asset=asset,
        profile_path=profile,
        run_dir=tmp_path / "run",
        start_material_path=asset.start_material_path,
        target_dir=tmp_path / "target_render",
        optimizer_start_patch=start_patch,
        target_score=0.99999,
        optimizer="material_coordinate_pattern",
        warmup_iterations=1000,
        block_iterations=400,
        block_population_size=16,
        refine_iterations=800,
        node_modules=None,
        views=[asset.profile["capture_defaults"]["views"][0]],
        jacobian_search_scope="material",
        material_only=True,
        search_param_names_override=["u_EmissionPow"],
    )

    assert config["search_param_names"] == ["u_EmissionPow"]
    assert config["search_param_space"] == "controlled_known_perturbation_subset_v1"
    assert config["stage1_optimizer_contract"]["known_perturbation_search_subset"] is True


def test_optimizer_profile_is_marked_as_proposal_only(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({"width": 900, "height": 700, "capture_defaults": {"views": []}}),
        encoding="utf-8",
    )
    output = _write_optimizer_profile(
        source,
        tmp_path / "optimizer.json",
        width=720,
        height=560,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert (payload["width"], payload["height"]) == (720, 560)
    assert payload["online_score_surrogate"]["role"] == "proposal_ranking_only"
    assert payload["online_score_surrogate"]["final_artifacts_use_source_profile"] is True


def test_finite_score_and_artifact_resolution_reject_invalid_inputs(
    tmp_path: Path,
) -> None:
    assert _finite_score(None) is None
    assert _finite_score({"score": float("nan")}) is None
    assert _finite_score({"score": 0.75}) == 0.75

    views = [{"file_name": "a.png"}, {"file_name": "b.png"}]
    Image.new("RGBA", (800, 484), (255, 255, 255, 255)).save(tmp_path / "a.png")
    Image.new("RGBA", (800, 484), (255, 255, 255, 255)).save(tmp_path / "b.png")
    assert _artifact_resolution(tmp_path, views) == [800, 484]

    Image.new("RGBA", (900, 700), (255, 255, 255, 255)).save(tmp_path / "b.png")
    with pytest.raises(RuntimeError, match="inconsistent Stage 1 artifact sizes"):
        _artifact_resolution(tmp_path, views)
