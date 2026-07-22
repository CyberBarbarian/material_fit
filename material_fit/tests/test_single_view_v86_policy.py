from material_fit.experiments.single_view_v86_policy import (
    adapt_v86_policy_for_material_only,
)
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V30,
    JOINT_PROFILE_V42,
    JOINT_PROFILE_V85,
    _extend_v86_child_policy_to_1500,
    joint_profile_policy,
)
from material_fit.experiments.stage1_fit_config import (
    STAGE1_OPTIMIZATION_SCORE_METRIC,
)
from material_fit.optimizer.material_discrete_joint_strategy import (
    MaterialDiscreteJointStrategy,
)
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    build_legal_discrete_candidates,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.optimizer.adjustment_algorithm import AdjustmentState
from material_fit.optimizer.strategy_core import StrategyContext
from material_fit.shared.models import ShaderParam
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_V3_METRIC,
    DISTS_METRIC,
)


def test_single_view_policy_routes_high_score_child_to_unified_policy() -> None:
    source, _extension = _extend_v86_child_policy_to_1500(
        selected_profile=JOINT_PROFILE_V30,
        selected_policy=joint_profile_policy(JOINT_PROFILE_V30),
        max_scored_candidates=1500,
    )
    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=True,
    )

    assert adapted["profile"].endswith("single_view_unified_v51")
    assert adapted["round_widths"] == [1]
    assert adapted["round_budgets"] == [1]
    assert adapted["round_sigmas"] == [0.18]
    assert adapted["rescan_at"] == [366, 1200]
    assert adapted["max_rescans"] == 2
    assert adapted["round_seed_mode"] == "branch_best"
    assert adapted["conditional_activation_probes"] == [
        {
            "name": "rim_and_normal_hard_state_response",
            "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
            "normalized_values": [0.3],
            "only_if_all_at_lower_bound": True,
            "feedback_source": "online_target_png_score_only",
            "target_params_visible": False,
        }
    ]
    assert adapted["activation_selects_initial_winner"] is True
    assert adapted["activation_commits_initial_seed"] is True
    assert adapted["skip_initial_discrete_probes_when_activation_selects"] is True
    assert adapted["discrete_observation_equivalence"] is False
    assert report["target_information_used"] is False
    assert report["selected_child_policy_preserved"] is False
    assert report["continuation_route"] == (
        "inverse_search_then_acceptance_polish"
    )
    assert report["scene_coordinates_searchable"] is True
    assert report["scene_coordinates_searchable_stage"] == (
        "pre_rescan_dedicated_scene_and_post_rescan_joint_then_frozen_material"
    )
    assert report["scene_coordinates_frozen_before_material_refine"] is True

def test_single_view_policy_routes_low_score_child_to_unified_policy() -> None:
    source = joint_profile_policy(JOINT_PROFILE_V85)
    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=True,
    )

    assert adapted["rescan_at"] == [366, 1200]
    assert adapted["max_rescans"] == 2
    assert report["optimization_score_metric"] == DISTS_ALIGNED_RGB_V3_METRIC
    assert report["acceptance_score_metric"] == STAGE1_OPTIMIZATION_SCORE_METRIC
    assert report["objective_changes_during_search"] is True
    assert report["runtime_score_override"]["after_continuous_proposals"] == 1200
    assert report["continuation_route"] == (
        "inverse_search_then_acceptance_polish"
    )

def test_single_view_policy_selects_hard_state_before_full_continuation() -> None:
    source, _extension = _extend_v86_child_policy_to_1500(
        selected_profile=JOINT_PROFILE_V42,
        selected_policy=joint_profile_policy(JOINT_PROFILE_V42),
        max_scored_candidates=1500,
    )
    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=True,
    )

    assert adapted["rescan_at"] == [366, 1200]
    assert adapted["rescan_candidate_modes"] == ["all", "all"]
    assert adapted["initial_continuous_warmup"] == {}
    assert adapted["post_rescan_branch_race"]["enabled"] is False
    assert adapted["restart_continuous_after_rescan"] is True
    assert adapted["restart_continuous_after_first_rescan"] is True
    assert adapted["minimum_final_refine_proposals"] == 250
    assert adapted["continuous"]["frozen_param_names"] == []
    continuous_stages = adapted["continuous"]["cascade"]["stages"]
    assert continuous_stages[1]["name"] == "dedicated_scene_calibration"
    assert continuous_stages[1].get("optimizer", "jacobian") == "jacobian"
    final = adapted["continuous_after_final_rescan"]
    assert final["strategy"] == "material_jacobian_cascade"
    stages = final["cascade"]["stages"]
    assert [stage["name"] for stage in stages] == [
        "post_rescan_joint_dense_descriptor_refine",
        "final_scene_frozen_material_refine",
    ]
    assert [stage["max_proposals"] for stage in stages] == [200, 50]
    assert stages[0]["frozen_param_names"] == []
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        stages[1]["frozen_param_names"]
    )
    assert stages[1].get("optimizer", "jacobian") == "jacobian"
    assert adapted["max_scored_candidates"] == 1500
    assert adapted["planned_proposal_budget"]["total"] == 1499
    between = adapted["post_rescan_branch_race"]["final_continuous"]
    assert [
        stage["max_proposals"]
        for stage in between["cascade"]["stages"]
    ] == [734, 100]
    assert report["hard_state_frozen_before_final_continuous_refine"] is True
    assert report["post_rescan_branch_race_enabled"] is False
    assert report["final_refiner"] == "material_jacobian_cascade"

def test_single_view_material_only_policy_omits_scene_calibration() -> None:
    source, _extension = _extend_v86_child_policy_to_1500(
        selected_profile=JOINT_PROFILE_V42,
        selected_policy=joint_profile_policy(JOINT_PROFILE_V42),
        max_scored_candidates=1500,
    )

    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=False,
    )

    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        adapted["initial_continuous_warmup"]["frozen_param_names"]
    )
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        adapted["continuous"]["frozen_param_names"]
    )
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        adapted["continuous_after_final_rescan"]["frozen_param_names"]
    )
    assert report["scene_coordinates_searchable"] is False
    assert report["scene_coordinates_searchable_stage"] is None
    assert report["scene_coordinates_frozen_before_material_refine"] is True

def test_low_score_material_only_route_moves_budget_to_pattern_tail() -> None:
    source, _extension = _extend_v86_child_policy_to_1500(
        selected_profile=JOINT_PROFILE_V42,
        selected_policy=joint_profile_policy(JOINT_PROFILE_V42),
        max_scored_candidates=1500,
    )

    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=False,
        initial_score=0.62,
    )

    assert adapted["initial_continuous_warmup"]["max_proposals"] == 110
    assert adapted["continuous_after_final_rescan"]["pattern"][
        "active_coordinate_count"
    ] == 16
    assert report["continuation_route"] == "fixed_target_blind_unified"

def test_low_score_joint_route_keeps_scene_stage_and_prioritizes_pattern() -> None:
    source, _extension = _extend_v86_child_policy_to_1500(
        selected_profile=JOINT_PROFILE_V42,
        selected_policy=joint_profile_policy(JOINT_PROFILE_V42),
        max_scored_candidates=1500,
    )

    adapted, report = adapt_v86_policy_for_material_only(
        source,
        scene_searchable=True,
        initial_score=0.75,
    )

    assert adapted["initial_continuous_warmup"] == {}
    assert adapted["continuous"]["frozen_param_names"] == []
    continuous_stages = adapted["continuous"]["cascade"]["stages"]
    assert continuous_stages[1]["name"] == "dedicated_scene_calibration"
    stages = adapted["continuous_after_final_rescan"]["cascade"]["stages"]
    assert stages[0]["frozen_param_names"] == []
    assert set(STRUCTURED_SCENE_PARAM_NAMES).issubset(
        stages[1]["frozen_param_names"]
    )
    assert report["continuation_route"] == (
        "inverse_search_then_acceptance_polish"
    )

def test_target_distance_stop_waits_for_all_planned_rescans() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )[:2]
    initial = attach_discrete_candidate({"u_GammaPower": 0.5}, candidates[0])
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "max_rescans": 2,
            "minimum_final_refine_proposals": 64,
        },
    )

    assert strategy.allows_target_distance_stop() is False
    strategy._rescan_count = 2
    strategy._final_rescan_continuous_proposal_start = 100
    strategy._continuous_proposals = 163
    assert strategy.allows_target_distance_stop() is False
    strategy._continuous_proposals = 164
    assert strategy.allows_target_distance_stop() is True


def test_rescan_candidate_modes_freeze_then_reopen_hard_states() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )[:3]
    initial = attach_discrete_candidate({"u_GammaPower": 0.5}, candidates[0])
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "initial_candidate_ids": [
                candidates[0]["candidate_id"],
                candidates[1]["candidate_id"],
            ],
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "rescan_candidate_modes": ["initial_representatives", "all"],
            "rescan_browser_score_overrides": [
                {},
                {"metric": DISTS_METRIC},
            ],
        },
    )
    winner_id = str(candidates[0]["candidate_id"])
    strategy._winner_id = winner_id
    strategy._best_params = initial
    context = StrategyContext(
        iteration=1,
        current_params=initial,
        analysis={},
        diff_score=0.1,
        fit_score=0.9,
        state=AdjustmentState(),
    )

    strategy._start_rescan(context)
    assert strategy._rescan_candidate_ids == [
        str(candidates[0]["candidate_id"]),
        str(candidates[1]["candidate_id"]),
    ]
    _first_params, first_decision = strategy._propose_rescan_candidate()
    assert first_decision["reset_global_score_domain"] is False
    strategy._pending_branch_id = None
    strategy._rescan_count = 1
    strategy._start_rescan(context)
    assert strategy._rescan_candidate_ids == [
        str(candidate["candidate_id"]) for candidate in candidates
    ]
    second_params, second_decision = strategy._propose_rescan_candidate()
    assert second_params["__material_fit_browser_score_override__"] == {
        "metric": DISTS_METRIC
    }
    assert second_decision["reset_global_score_domain"] is True
    assert context.state.best_fit_score == float("-inf")


def test_winner_axis_rescan_varies_only_the_requested_hard_state_axis() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )
    winner = next(
        candidate
        for candidate in candidates
        if candidate["axes"]
        == {"normal_mode": "normal", "rim_smooth": True, "blend_src": 0}
    )
    initial = attach_discrete_candidate({"u_GammaPower": 0.5}, winner)
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={
            "candidates": candidates,
            "start_candidate": winner,
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "rescan_candidate_modes": ["winner_axis:normal_mode"],
        },
    )
    strategy._winner_id = str(winner["candidate_id"])
    strategy._best_params = initial
    context = StrategyContext(
        iteration=1,
        current_params=initial,
        analysis={},
        diff_score=0.1,
        fit_score=0.9,
        state=AdjustmentState(),
    )

    strategy._start_rescan(context)

    selected = [strategy._branches[candidate_id].candidate for candidate_id in strategy._rescan_candidate_ids]
    assert len(selected) == 4
    assert {candidate["axes"]["normal_mode"] for candidate in selected} == {
        "flat",
        "legacy_y_invert_only",
        "normal",
        "normal_y_invert",
    }
    assert {candidate["axes"]["rim_smooth"] for candidate in selected} == {True}
    assert {candidate["axes"]["blend_src"] for candidate in selected} == {0}
    assert strategy._rescan_group_axes == ("normal_mode",)


def test_branch_best_round_seed_preserves_each_hard_state_basin() -> None:
    candidates = build_legal_discrete_candidates(
        {
            "defines": {},
            "render_states": {"blend": 0, "blend_src": 1},
        }
    )[:2]
    initial = attach_discrete_candidate({"u_GammaPower": 0.5}, candidates[0])
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "round_widths": [2],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "round_seed_mode": "branch_best",
            "branch_strategy": "material_jacobian_trust_region",
        },
    )
    first_id = str(candidates[0]["candidate_id"])
    second_id = str(candidates[1]["candidate_id"])
    strategy._branches[first_id].best_params = {"u_GammaPower": 0.25}
    strategy._branches[first_id].best_score = 0.8
    strategy._branches[second_id].best_params = {"u_GammaPower": 1.75}
    strategy._branches[second_id].best_score = 0.7

    strategy._start_round(0, [first_id, second_id])

    assert strategy._branches[first_id].round_seed_params == {"u_GammaPower": 0.25}
    assert strategy._branches[second_id].round_seed_params == {"u_GammaPower": 1.75}
    assert strategy._branches[first_id].optimizer._best_params == {
        "u_GammaPower": 0.25
    }
    assert strategy._branches[second_id].optimizer._best_params == {
        "u_GammaPower": 1.75
    }


def test_conditional_activation_score_does_not_replace_continuous_seed() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )[:2]
    initial_continuous = {
        "u_GammaPower": 0.5,
        "u_RimIntensity": 0.0,
        "u_RimWidth": 0.0,
    }
    initial = attach_discrete_candidate(initial_continuous, candidates[0])
    shader_params = [
        ShaderParam(name, "Float", default=value, range_min=0.0, range_max=10.0)
        for name, value in initial_continuous.items()
    ]
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=list(initial_continuous),
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "conditional_activation_probes": [
                {
                    "name": "rim",
                    "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
                    "normalized_values": [0.5],
                    "only_if_all_at_lower_bound": True,
                }
            ],
        },
    )
    candidate_id = str(candidates[0]["candidate_id"])
    probe = {
        "probe_name": "rim",
        "normalized_value": 0.5,
        "candidate_id": candidate_id,
    }
    probe_params = attach_discrete_candidate(
        {**initial_continuous, "u_RimIntensity": 5.0, "u_RimWidth": 5.0},
        candidates[0],
    )
    strategy._phase = "conditional_activation_probe"
    strategy._conditional_activation_pending = probe
    strategy._pending_branch_id = candidate_id
    strategy._branches[candidate_id].selection_score = 0.95

    strategy._observe(
        StrategyContext(
            iteration=1,
            current_params=probe_params,
            analysis={},
            diff_score=0.1,
            fit_score=0.9,
            state=AdjustmentState(),
        )
    )

    branch = strategy._branches[candidate_id]
    assert branch.selection_score == 0.9
    assert branch.best_params == initial_continuous


def test_conditional_activation_can_commit_target_blind_seed() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )[:2]
    initial_continuous = {
        "u_GammaPower": 0.5,
        "u_RimIntensity": 0.0,
        "u_RimWidth": 0.0,
    }
    initial = attach_discrete_candidate(initial_continuous, candidates[0])
    shader_params = [
        ShaderParam(name, "Float", default=value, range_min=0.0, range_max=10.0)
        for name, value in initial_continuous.items()
    ]
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=shader_params,
        search_param_names=list(initial_continuous),
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "round_widths": [1],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "activation_commits_initial_seed": True,
            "conditional_activation_probes": [
                {
                    "name": "rim",
                    "coordinate_ids": ["u_RimIntensity", "u_RimWidth"],
                    "normalized_values": [0.5],
                    "only_if_all_at_lower_bound": True,
                }
            ],
        },
    )
    candidate_id = str(candidates[0]["candidate_id"])
    probe = {
        "probe_name": "rim",
        "normalized_value": 0.5,
        "candidate_id": candidate_id,
    }
    probe_continuous = {
        **initial_continuous,
        "u_RimIntensity": 5.0,
        "u_RimWidth": 5.0,
    }
    strategy._phase = "conditional_activation_probe"
    strategy._conditional_activation_pending = probe
    strategy._pending_branch_id = candidate_id
    strategy._observe(
        StrategyContext(
            iteration=1,
            current_params=attach_discrete_candidate(
                probe_continuous,
                candidates[0],
            ),
            analysis={"source": "online PNG"},
            diff_score=0.1,
            fit_score=0.9,
            state=AdjustmentState(),
        )
    )

    branch = strategy._branches[candidate_id]
    assert branch.best_params == probe_continuous
    assert branch.best_score == 0.9
    assert strategy.research_summary()["conditional_activation"][
        "commits_initial_seed"
    ] is True


def test_activation_ranking_keeps_diverse_normal_modes_for_basin_race() -> None:
    candidates = build_legal_discrete_candidates(
        {"defines": {}, "render_states": {"blend": 0, "blend_src": 1}}
    )
    initial = attach_discrete_candidate({"u_GammaPower": 0.5}, candidates[0])
    strategy = MaterialDiscreteJointStrategy(
        initial_params=initial,
        shader_params=[
            ShaderParam(
                "u_GammaPower",
                "Range",
                default=1.0,
                range_min=0.0,
                range_max=3.0,
            )
        ],
        search_param_names=["u_GammaPower"],
        config={
            "candidates": candidates,
            "start_candidate": candidates[0],
            "round_widths": [4],
            "round_budgets": [1],
            "round_sigmas": [0.1],
            "diversity_rounds": 1,
        },
    )
    for index, branch in enumerate(strategy._branches.values()):
        branch.best_score = float(index)
        branch.selection_score = float(len(strategy._branches) - index)
    strategy._conditional_activation_results.append({"fit_score": 0.5})

    strategy._start_round(0, list(strategy._branches))

    selected = [strategy._branches[candidate_id] for candidate_id in strategy._active_ids]
    assert len(selected) == 4
    assert len({branch.candidate["axes"]["normal_mode"] for branch in selected}) == 4
