from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.optimizer.cma_es_optimizer import ParameterEncoder  # noqa: E402
from tools.material_fit.optimizer.group_probe import (  # noqa: E402
    evaluate_group_probe,
    generate_group_probe_candidates,
)
from tools.material_fit.optimizer.llm_semantics import (  # noqa: E402
    build_llm_semantics_context,
    validate_llm_semantics_output,
)
from tools.material_fit.optimizer.semantic_graph import (  # noqa: E402
    build_shader_effect_graph,
)
from tools.material_fit.optimizer.strategy import (  # noqa: E402
    SemanticCandidateGenerator,
    SemanticGroupStrategy,
    StrategyContext,
)
from tools.material_fit.optimizer.acceptance_policy import AcceptancePolicy  # noqa: E402
from tools.material_fit.optimizer.branch_guard import BranchDriftGuard  # noqa: E402
from tools.material_fit.optimizer.breakthrough_candidates import BreakthroughCandidateQueue  # noqa: E402
from tools.material_fit.optimizer.search_evidence import (  # noqa: E402
    InfluenceTracker,
    TopKArchive,
    metric_vector_from_analysis,
)
from tools.material_fit.optimizer.trust_region import TrustRegionBranch  # noqa: E402
from tools.material_fit.fit_material import _resolve_auto_adjust_status  # noqa: E402
from tools.material_fit_ui.backend.project_store import _apply_effective_laya_control_schema  # noqa: E402
from tools.material_fit_ui.backend.preanalysis import build_effective_laya_control_schema  # noqa: E402
from tools.material_fit.optimizer.adjustment_algorithm import AdjustmentState  # noqa: E402
from tools.material_fit.shared.models import ShaderDefine, ShaderParam  # noqa: E402


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_FresnelIntensity", "Float", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_FresnelColor", "Color", default=[1, 0, 0, 1]),
        ShaderParam("u_FresnelSmooth", "Range", default=0.5, range_min=0.0, range_max=1.0),
        ShaderParam("u_EmissionColor", "Color", default=[0, 0, 0, 1]),
        ShaderParam("u_EmissionScale", "Float", default=0.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_AdjustHue", "Float", default=0.0, range_min=0.0, range_max=360.0),
        ShaderParam("u_BaseMap", "Texture2D", default="white"),
    ]


def _params() -> dict[str, object]:
    return {
        "u_BaseColor": [0.3, 0.2, 0.1, 1.0],
        "u_Gamma_Power": 2.2,
        "u_FresnelIntensity": 0.0,
        "u_FresnelColor": [1.0, 0.0, 0.0, 1.0],
        "u_FresnelSmooth": 0.5,
        "u_EmissionColor": [0.0, 0.0, 0.0, 1.0],
        "u_EmissionScale": 1.0,
        "u_AdjustHue": 15.0,
        "u_BaseMap": "white",
    }


def test_semantic_graph_marks_groups_gates_and_transforms():
    graph = build_shader_effect_graph(
        _shader_params(),
        shader_defines=[ShaderDefine("EMISSION"), ShaderDefine("ADJUST_HSV")],
        material_params=_params(),
        material_defines=["EMISSION"],
    )

    assert graph.params["u_Gamma_Power"].transform == "log"
    assert graph.params["u_AdjustHue"].transform == "circular"
    assert graph.params["u_BaseMap"].searchable is False
    assert graph.params["u_FresnelColor"].gates[0].name == "u_FresnelIntensity"
    assert graph.groups["fresnel"].active is False
    assert graph.groups["emission"].active is True
    assert graph.groups["color_grade"].active is False


def test_semantic_graph_classifies_generic_u_color_as_base_color():
    graph = build_shader_effect_graph(
        [
            ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
            ShaderParam("u_TexPower", "Float", default=1.0),
            ShaderParam("u_AoPower", "Float", default=1.0),
        ],
        material_params={"u_Color": [0.4, 0.4, 0.4, 1], "u_TexPower": 1.0, "u_AoPower": 1.0},
    )

    assert graph.params["u_Color"].group == "base_color"
    assert graph.params["u_Color"].transform == "color_rgb"
    assert graph.params["u_TexPower"].group == "base_color"
    assert graph.params["u_AoPower"].group == "shadow_diffuse"
    assert "u_Color" in graph.groups["base_color"].search_params


def test_semantic_graph_classifies_custom_low_misc_params_into_specific_groups():
    graph = build_shader_effect_graph(
        [
            ShaderParam("u_MainTex", "Texture2D", default="white"),
            ShaderParam("u_MainTex_ST", "Vector", default=[1, 1, 0, 0]),
            ShaderParam("u_NormalTex", "Texture2D", default="bump"),
            ShaderParam("u_NormalScale", "Float", default=1.0),
            ShaderParam("u_SpeTex", "Texture2D", default="white"),
            ShaderParam("u_SpeOffet", "Float", default=0.0),
            ShaderParam("u_LMap", "Texture2D", default="white"),
            ShaderParam("u_GammaPower", "Float", default=1.0),
            ShaderParam("u_LightRotateY", "Float", default=0.0),
            ShaderParam("u_AlphaTestValue", "Float", default=0.5),
            ShaderParam("u_IndirectStrength", "Float", default=1.0),
        ],
        shader_defines=[ShaderDefine("NORMALMAP"), ShaderDefine("ALPHATEST")],
        material_params={
            "u_NormalScale": 1.0,
            "u_SpeOffet": 0.0,
            "u_GammaPower": 1.0,
            "u_LightRotateY": 0.0,
            "u_AlphaTestValue": 0.5,
            "u_IndirectStrength": 1.0,
        },
    )

    assert graph.params["u_MainTex"].group == "base_color"
    assert graph.params["u_MainTex"].searchable is False
    assert graph.params["u_NormalScale"].group == "normal_detail"
    assert graph.params["u_SpeTex"].group == "specular_smoothness"
    assert graph.params["u_LMap"].group == "shared_mask_lmap"
    assert graph.params["u_GammaPower"].group == "shared_mask_lmap"
    assert graph.params["u_LightRotateY"].group == "light_direction"
    assert graph.params["u_AlphaTestValue"].group == "alpha_cutout"
    assert graph.params["u_AlphaTestValue"].searchable is False
    assert graph.params["u_IndirectStrength"].group == "reflection_matcap"


def test_parameter_encoder_uses_semantic_log_transform_when_graph_is_provided():
    graph = build_shader_effect_graph(_shader_params(), material_params=_params())
    encoder = ParameterEncoder(_params(), _shader_params(), semantics=graph)

    gamma_axis = next(axis for axis in encoder.axes if axis.param_name == "u_Gamma_Power")
    assert gamma_axis.transform == "log"
    fresnel_axis = next(axis for axis in encoder.axes if axis.param_name == "u_FresnelIntensity")
    assert fresnel_axis.transform == "log"
    assert math.expm1(fresnel_axis.high) == pytest.approx(20.0)
    encoded = encoder.encode(_params())
    decoded = encoder.decode(encoded)
    assert decoded["u_Gamma_Power"] == pytest.approx(2.2)


def test_group_probe_candidates_activate_inactive_gated_groups_and_report_results():
    graph = build_shader_effect_graph(
        _shader_params(),
        shader_defines=[ShaderDefine("EMISSION")],
        material_params=_params(),
        material_defines=["EMISSION"],
    )
    candidates = generate_group_probe_candidates(_params(), graph)
    groups = {candidate.group for candidate in candidates}

    assert "emission" in groups
    fresnel_probe = next(candidate for candidate in candidates if candidate.group == "fresnel")
    assert fresnel_probe.changed_params == ["u_FresnelIntensity"]
    result = evaluate_group_probe(group="emission", mean_diff=1.2, threshold=0.5)
    assert result.active is True


def test_runtime_gating_reactivates_params_after_gate_value_changes():
    graph = build_shader_effect_graph(
        _shader_params(),
        material_params={**_params(), "u_FresnelIntensity": 0.0},
    )
    off_params = {**_params(), "u_FresnelIntensity": 0.0}

    assert graph.runtime_group_status("fresnel", off_params)["active"] is False
    assert "u_FresnelColor" not in graph.active_search_params_for(off_params)
    assert any(item["param"] == "u_FresnelColor" for item in graph.gated_search_params_for(off_params))
    assert any(item["param"] == "u_FresnelIntensity" for item in graph.activation_params_for(off_params))

    on_params = {**_params(), "u_FresnelIntensity": 1.0}
    assert graph.runtime_group_status("fresnel", on_params)["active"] is True
    assert "u_FresnelColor" in graph.active_search_params_for(on_params)
    assert not graph.gated_search_params_for(on_params)


def test_runtime_gating_does_not_invent_missing_fresnel_gate():
    shader_params = [
        ShaderParam("u_RimColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_RimIntensity", "Float", default=1.0, range_min=0.0, range_max=4.0),
        ShaderParam("u_RimWidth", "Float", default=1.0, range_min=0.0, range_max=8.0),
    ]
    params = {"u_RimColor": [1, 1, 1, 1], "u_RimIntensity": 0.0, "u_RimWidth": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)

    assert graph.groups["fresnel"].gate_params == []
    assert graph.runtime_group_status("fresnel", params)["active"] is True
    assert "u_RimColor" in graph.active_search_params_for(params)


def test_llm_semantics_validator_only_allows_known_params_and_defines():
    context = build_llm_semantics_context(
        laya_shader={"params": [{"name": "u_FresnelColor"}], "defines": [{"name": "FRESNEL"}]},
        laya_material_params={"u_FresnelColor": [1, 0, 0, 1]},
        laya_material_defines=[],
    )
    assert context["task"]["allowed_output"] == "strict_json_semantic_prior"

    validated = validate_llm_semantics_output(
        {
            "param_semantics": [
                {
                    "name": "u_FresnelColor",
                    "group": "fresnel",
                    "role": "color",
                    "transform": "color_rgb",
                    "confidence": 0.91,
                    "evidence": ["used in rim color term"],
                    "risk": "view dependent",
                    "gates": [{"kind": "define", "name": "FRESNEL"}],
                },
                {"name": "u_NotReal", "group": "misc"},
            ],
            "unity_feature_summary": [
                {
                    "feature": "rim_or_fresnel",
                    "enabled": True,
                    "confidence": 0.88,
                    "evidence": ["_RIMLIGHT_ON keyword"],
                    "unity_params": ["_RimColor"],
                    "controls": ["color", "intensity"],
                    "laya_candidate_groups": ["fresnel"],
                }
            ],
            "laya_module_candidates": [
                {
                    "feature": "rim_or_fresnel",
                    "group": "fresnel",
                    "confidence": 0.8,
                    "params": ["u_FresnelColor", "u_NotReal"],
                    "define_gates": ["FRESNEL", "NOT_A_DEFINE"],
                    "param_gates": ["u_FresnelColor", "u_NotReal"],
                }
            ],
            "unity_phenomena": [
                {
                    "name": "rim_or_fresnel",
                    "confidence": 0.9,
                    "unity_evidence": ["Unity shader contains fresnel-like term"],
                    "laya_candidate_groups": ["fresnel", "not_a_group"],
                }
            ],
            "initial_laya_param_suggestions": [
                {
                    "laya_param": "u_FresnelColor",
                    "suggested_value": [1, 0.2, 0.2, 1],
                    "confidence": 0.6,
                    "source_unity_params": ["_RimColor"],
                },
                {"laya_param": "u_NotReal", "suggested_value": 1.0},
            ],
        },
        allowed_params={"u_FresnelColor"},
        allowed_defines={"FRESNEL"},
    )

    assert len(validated["param_semantics"]) == 1
    assert validated["param_semantics"][0]["confidence"] == pytest.approx(0.91)
    assert validated["param_semantics"][0]["evidence"] == ["used in rim color term"]
    assert validated["param_semantics"][0]["risk"] == "view dependent"
    assert validated["unity_feature_summary"][0]["feature"] == "rim_or_fresnel"
    assert validated["laya_module_candidates"][0]["params"] == ["u_FresnelColor"]
    assert validated["laya_module_candidates"][0]["define_gates"] == ["FRESNEL"]
    assert validated["laya_module_candidates"][0]["param_gates"] == ["u_FresnelColor"]
    assert len(validated["unity_phenomena"]) == 1
    assert validated["unity_phenomena"][0]["laya_candidate_groups"] == ["fresnel", "misc"]
    assert len(validated["initial_laya_param_suggestions"]) == 1
    assert validated["warnings"] == [
        "ignored unknown param 'u_NotReal'",
        "ignored initial suggestion for unknown param 'u_NotReal'",
    ]


def test_llm_semantics_cannot_promote_fixed_texture_to_searchable():
    graph = build_shader_effect_graph(
        [ShaderParam("u_MainTex", "Texture2D", default="white")],
        llm_semantics={
            "param_semantics": [
                {
                    "name": "u_MainTex",
                    "group": "base_color",
                    "role": "texture",
                    "searchable": True,
                    "confidence": 0.95,
                }
            ]
        },
    )

    assert graph.params["u_MainTex"].group == "base_color"
    assert graph.params["u_MainTex"].source == "llm"
    assert graph.params["u_MainTex"].searchable is False


def test_effective_laya_control_schema_updates_fit_config_effect_graph_group():
    graph = build_shader_effect_graph(
        [
            ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
            ShaderParam("u_EmissionPow", "Float", default=1.0),
        ],
        material_params={"u_Color": [0.3, 0.3, 0.3, 1], "u_EmissionPow": 1.0},
    ).to_dict()
    effective_schema = {
        "groups": [
            {
                "id": "base_color",
                "enabled": True,
                "order": 0,
                "controls": [
                    {
                        "name": "u_Color",
                        "group": "base_color",
                        "role": "color",
                        "transform": "color_rgb",
                        "searchable": True,
                        "source": "manual",
                        "confidence": 1.0,
                        "evidence": ["human confirmed"],
                        "conflict_status": "manual_override",
                    }
                ],
            }
        ]
    }

    patched = _apply_effective_laya_control_schema(graph, effective_schema, {})

    assert patched["params"]["u_Color"]["group"] == "base_color"
    assert patched["params"]["u_Color"]["source"] == "manual"
    assert patched["params"]["u_Color"]["confidence"] == pytest.approx(1.0)
    assert patched["groups"]["base_color"]["search_params"] == ["u_Color"]


def test_semantic_graph_marks_unity_suggested_inactive_group_for_probe():
    graph = build_shader_effect_graph(
        _shader_params(),
        material_params=_params(),
        llm_semantics={
            "unity_feature_summary": [
                {
                    "feature": "rim_or_fresnel",
                    "confidence": 0.9,
                    "evidence": ["Unity rim keyword is enabled"],
                    "laya_candidate_groups": ["fresnel"],
                }
            ],
            "laya_module_candidates": [
                {
                    "feature": "rim_or_fresnel",
                    "group": "fresnel",
                    "confidence": 0.9,
                    "params": ["u_FresnelIntensity", "u_FresnelColor"],
                }
            ],
        },
    )

    group = graph.groups["fresnel"]
    assert group.current_active is False
    assert group.suggested_by_unity is True
    assert group.probe_required is True
    assert group.search_priority == pytest.approx(0.9)
    assert "u_FresnelIntensity" in graph.active_search_params()


def test_semantic_group_strategy_walks_ui_panel_order():
    """The optimizer should follow the human-curated UI panel order.

    When the run console assigns ``order=10`` to ``fresnel`` and a
    larger order to ``base_color``, ``SemanticGroupStrategy`` must
    pick ``fresnel`` first regardless of which channel currently has
    the worst residual.
    """

    params = dict(_params())
    params["u_FresnelIntensity"] = 1.0
    graph = build_shader_effect_graph(_shader_params(), material_params=params)
    # Simulate the run console preset assigning fresnel as the first
    # panel and demoting base_color to the back.
    fresnel = graph.groups["fresnel"]
    base = graph.groups["base_color"]
    object.__setattr__(fresnel, "order", 10)
    object.__setattr__(base, "order", 100)

    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=_shader_params(),
        graph=graph,
    )
    ctx = StrategyContext(
        iteration=0,
        current_params=params,
        analysis={
            "material_channels": {
                "fresnel_rim": {"rgb_mae": 0.9},
                "base_color_main_texture": {"rgb_mae": 0.1},
            }
        },
        diff_score=0.5,
        fit_score=0.5,
        state=AdjustmentState(best_params=params),
    )

    next_params, decision = strategy.propose(ctx)

    assert decision["optimizer"] == "semantic_group"
    assert decision["semantic_group"]["name"] == "fresnel"
    assert next_params != params
    assert decision["changes"]


def test_semantic_group_fresh_fit_skips_force_isolation_before_base_color():
    params = dict(_params())
    params["u_EmissionScale"] = 1.0
    graph = build_shader_effect_graph(_shader_params(), material_params=params)

    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=_shader_params(),
        graph=graph,
        auto_adjust_mode="fresh_fit",
    )
    next_params, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={},
            diff_score=0.5,
            fit_score=0.5,
            state=AdjustmentState(best_params=params),
        )
    )

    assert decision["semantic_action"] != "isolate_base_color"
    assert next_params["u_EmissionScale"] != 0.0


def test_semantic_group_refine_current_skips_isolation():
    params = dict(_params())
    params["u_EmissionScale"] = 1.0
    graph = build_shader_effect_graph(_shader_params(), material_params=params)

    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=_shader_params(),
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    next_params, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={},
            diff_score=0.5,
            fit_score=0.5,
            state=AdjustmentState(best_params=params),
        )
    )

    assert decision.get("semantic_action") != "isolate_base_color"
    assert next_params["u_EmissionScale"] != 0.0


def test_semantic_group_visit_budget_prevents_single_param_starvation():
    shader_params = [
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    object.__setattr__(graph.groups["emission"], "order", 10)
    object.__setattr__(graph.groups["normal_detail"], "order", 20)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    current = dict(params)
    stages: list[str] = []
    for iteration in range(8):
        current, decision = strategy.propose(
            StrategyContext(
                iteration=iteration,
                current_params=current,
                analysis={},
                diff_score=0.5,
                fit_score=0.5 + iteration * 0.01,
                state=AdjustmentState(best_params=current),
            )
        )
        stages.append(decision["semantic_group"]["name"])

    assert stages[0] == "emission"
    assert "normal_detail" in stages[1:]


def test_semantic_group_decision_reports_scheduler_state():
    shader_params = [
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    _, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={},
            diff_score=0.5,
            fit_score=0.5,
            state=AdjustmentState(best_params=params),
        )
    )

    scheduler = decision["scheduler"]
    assert scheduler["phase"] == "exploration"
    assert scheduler["selected_group"] == decision["semantic_group"]["name"]
    assert "emission" in scheduler["group_status"]
    assert scheduler["group_status"]["emission"]["visit_limit"] >= 6
    assert scheduler["search_param_count"] == 2
    assert len(scheduler["param_ranking"]) == 2
    assert len(scheduler["param_candidate_pool"]) == 2


def test_semantic_group_rolls_branch_back_only_after_hard_drift():
    shader_params = [
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    global_best = {"u_EmissionPow": 2.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    state = AdjustmentState(
        best_params=dict(global_best),
        best_fit_score=0.9,
        best_fit_params=dict(global_best),
    )

    candidate, _ = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={},
            diff_score=0.5,
            fit_score=0.5,
            state=state,
        )
    )
    _, decision = strategy.propose(
        StrategyContext(
            iteration=1,
            current_params=candidate,
            analysis={},
            diff_score=0.4,
            fit_score=0.6,
            state=state,
        )
    )

    previous = decision["previous_candidate"]
    assert previous["accepted"] is True
    assert previous["outcome"] == "accepted_but_drift_rollback_to_checkpoint"
    assert previous["next_base_params"] == global_best


def test_semantic_group_uses_joint_candidate_for_multi_param_group():
    shader_params = [
        ShaderParam("u_HueShift", "Float", default=0.0, range_min=-1.0, range_max=1.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_Contrast", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_HueShift": 0.0, "u_Saturation": 1.0, "u_Contrast": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    next_params, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={},
            diff_score=0.5,
            fit_score=0.5,
            state=AdjustmentState(best_params=params),
        )
    )

    assert decision["axis"]["joint"] is True
    assert len(decision["axis"]["changed_params"]) >= 2
    assert next_params != params


def test_semantic_candidate_generator_cross_group_candidate_changes_two_groups():
    from tools.material_fit.optimizer.cma_es_optimizer import ParameterEncoder

    shader_params = [
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    generator = SemanticCandidateGenerator(
        graph=graph,
        shader_params=shader_params,
        encoder_cls=ParameterEncoder,
        step_schedule=[0.25, 0.14],
    )

    result = generator.cross_group_candidate(
        base_params=params,
        groups=[graph.groups["emission"], graph.groups["normal_detail"]],
        group_cycle=1,
        analysis={},
        base_fit_score=0.5,
        iteration=10,
    )

    assert result is not None
    next_params, payload = result
    assert next_params["u_EmissionPow"] != params["u_EmissionPow"]
    assert next_params["u_NormalScale"] != params["u_NormalScale"]
    assert payload["cross_groups"] == ["emission", "normal_detail"]
    assert sorted(payload["changed_params"]) == ["u_EmissionPow", "u_NormalScale"]


def test_semantic_group_refinement_uses_diagnostic_scores():
    shader_params = [
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    object.__setattr__(graph.groups["emission"], "order", 10)
    object.__setattr__(graph.groups["normal_detail"], "order", 20)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._state_for_group("emission")["status"] = "exhausted"
    strategy._state_for_group("normal_detail")["status"] = "exhausted"

    restarted = strategy._restart_exhausted_groups(
        {
            "material_channels": {
                "emission": {"valid": True, "rgb_mae": 0.01},
                "detail_texture": {"valid": True, "avg_rgb_mae": 0.40},
            }
        }
    )

    assert restarted is True
    assert strategy._group_order[0] == "normal_detail"
    scheduler = strategy._scheduler_state(
        "normal_detail",
        {"material_channels": {"detail_texture": {"valid": True, "avg_rgb_mae": 0.40}}},
    )
    assert scheduler["group_status"]["normal_detail"]["diagnostic_score"] == pytest.approx(0.40)


def test_metric_vector_extracts_research_components_and_worst_view():
    metrics = metric_vector_from_analysis(
        {
            "research_metrics": {
                "components": {
                    "color_mean": 0.12,
                    "detail_texture": 0.30,
                    "ignored": 99.0,
                }
            },
            "multiview": {"summary": {"worst_fit_score": 0.62, "worst_view_id": "yaw90_pitch0"}},
        },
        0.81,
    )

    assert metrics.fit_score == 0.81
    assert metrics.components == {"color_mean": 0.12, "detail_texture": 0.30}
    assert metrics.worst_fit_score == 0.62
    assert metrics.worst_view_id == "yaw90_pitch0"


def test_influence_tracker_prioritizes_matching_metric_bottleneck():
    tracker = InfluenceTracker(alpha=1.0)
    before = metric_vector_from_analysis(
        {"research_metrics": {"components": {"color_mean": 0.30, "detail_texture": 0.10}}},
        0.70,
    )
    after = metric_vector_from_analysis(
        {"research_metrics": {"components": {"color_mean": 0.10, "detail_texture": 0.12}}},
        0.78,
    )

    tracker.observe(
        group="base_color",
        kind="pattern",
        before=before,
        after=after,
        fit_delta=0.08,
        accepted=True,
        changed_params=["u_BaseColor"],
    )

    assert tracker.utility_for("base_color", {"color_mean": 0.50}) > tracker.utility_for(
        "base_color",
        {"detail_texture": 0.50},
    )


def test_semantic_group_breakthrough_restart_reports_active_phase():
    shader_params = [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_BaseColor": [1, 1, 1, 1], "u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    for name in strategy._group_order:
        strategy._state_for_group(name)["status"] = "exhausted"
    strategy._group_cycle = strategy._breakthrough_cycle - 1

    restarted = strategy._restart_exhausted_groups(
        {
            "research_metrics": {
                "components": {"color_mean": 0.45, "detail_texture": 0.08},
            },
            "material_channels": {"base_color": {"valid": True, "rgb_mae": 0.45}},
        }
    )

    assert restarted is True
    assert strategy._scheduler_state(
        "base_color",
        {
            "research_metrics": {
                "components": {"color_mean": 0.45, "detail_texture": 0.08},
            },
        },
    )["phase"] == "refinement"


def test_topk_archive_selects_restart_matching_bottleneck():
    archive = TopKArchive(capacity=4)
    archive.add(
        params={"u_BaseColor": [0.2, 0.2, 0.2, 1.0]},
        fit_score=0.80,
        metrics=metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.05, "detail_texture": 0.40}}},
            0.80,
        ),
        group="base_color",
        iteration=4,
    )
    archive.add(
        params={"u_BaseColor": [0.8, 0.8, 0.8, 1.0]},
        fit_score=0.81,
        metrics=metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.35, "detail_texture": 0.05}}},
            0.81,
        ),
        group="normal_detail",
        iteration=5,
    )

    restart = archive.select_restart(
        bottleneck={"color_mean": 0.45},
        current_params={"u_BaseColor": [1.0, 1.0, 1.0, 1.0]},
    )

    assert restart is not None
    assert restart["group"] == "base_color"


def test_acceptance_policy_provisionally_accepts_component_gain_in_breakthrough():
    policy = AcceptancePolicy(component_gain_threshold=0.03)
    base = metric_vector_from_analysis(
        {
            "research_metrics": {"components": {"color_mean": 0.30}},
            "multiview": {"summary": {"worst_fit_score": 0.72}},
        },
        0.80,
    )
    candidate = metric_vector_from_analysis(
        {
            "research_metrics": {"components": {"color_mean": 0.22}},
            "multiview": {"summary": {"worst_fit_score": 0.71}},
        },
        0.797,
    )

    decision = policy.evaluate(
        base=base,
        candidate=candidate,
        fit_delta=-0.003,
        min_improvement=0.001,
        phase="breakthrough",
    )

    assert decision.accepted is True
    assert decision.provisional is True
    assert decision.reason == "component_bottleneck_improved"


def test_breakthrough_candidate_queue_builds_local_population():
    shader_params = [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_EmissionPow", "Float", default=1.0, range_min=0.0, range_max=8.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_BaseColor": [1, 1, 1, 1], "u_EmissionPow": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    generator = SemanticCandidateGenerator(
        graph=graph,
        shader_params=shader_params,
        encoder_cls=ParameterEncoder,
        step_schedule=[0.25, 0.14],
    )
    queue = BreakthroughCandidateQueue(max_size=4)

    queue.ensure(
        base_params=params,
        base_fit_score=0.80,
        analysis={"research_metrics": {"components": {"color_mean": 0.30}}},
        iteration=12,
        group_cycle=3,
        groups_by_name=graph.groups,
        group_order=list(graph.groups),
        group_scores={name: 1.0 for name in graph.groups},
        active_groups=set(graph.groups),
        bottleneck={"color_mean": 0.30},
        archive=TopKArchive(),
        generator=generator,
    )

    candidate = queue.pop()
    assert candidate is not None
    assert candidate[0] != params
    assert queue.summary()["generated_count"] > 0


def test_auto_adjust_status_reports_breakthrough_exhausted():
    status = _resolve_auto_adjust_status(
        best_fit_score=0.81,
        target_score=0.90,
        terminal_reason="all_semantic_groups_exhausted",
        completed_iterations=230,
        requested_iterations=300,
        optimizer_research_summary={"phase": "breakthrough"},
    )

    assert status == "breakthrough_exhausted"


def test_semantic_group_plateau_waits_until_search_space_is_sampled():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_Color": [1, 1, 1, 1], "u_Saturation": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    state = AdjustmentState(best_params=params, best_fit_score=0.70, best_fit_params=params)

    for iteration in range(40):
        strategy._update_plateau_state(
            StrategyContext(
                iteration=iteration,
                current_params=params,
                analysis={"research_metrics": {"components": {"color_mean": 0.45}}},
                diff_score=0.3,
                fit_score=0.70,
                state=state,
            )
        )

    assert strategy._scheduler_phase() == "exploration"

    sampled = 0
    for name in strategy._group_order:
        strategy._state_for_group(name)["status"] = "exhausted"
        sampled += 1
        if sampled / max(len(strategy._group_order), 1) >= strategy._plateau_min_exhausted_ratio:
            break
    strategy._update_plateau_state(
        StrategyContext(
            iteration=40,
            current_params=params,
            analysis={"research_metrics": {"components": {"color_mean": 0.45}}},
            diff_score=0.3,
            fit_score=0.70,
            state=state,
        )
    )

    assert strategy._scheduler_phase() == "breakthrough"
    assert strategy._scheduler_state("base_color", {})["force_breakthrough"] is True


def test_color_bottleneck_active_subspace_keeps_color_related_groups():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
        ShaderParam("u_GammaPower", "Float", default=1.0, range_min=0.05, range_max=3.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {
        "u_Color": [1, 1, 1, 1],
        "u_TexPower": 1.0,
        "u_GammaPower": 1.0,
        "u_Saturation": 1.0,
        "u_NormalScale": 1.0,
    }
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    active = strategy._active_subspace_groups(
        {"research_metrics": {"components": {"color_mean": 0.50, "color_p95": 0.45}}}
    )

    assert "base_color" in active
    assert "color_grade" in active
    assert "shared_mask_lmap" in active


def test_param_agenda_prioritizes_bottleneck_relevant_under_sampled_params():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_GammaPower", "Float", default=1.0, range_min=0.05, range_max=3.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_Color": [1, 1, 1, 1], "u_GammaPower": 1.0, "u_Saturation": 1.0, "u_NormalScale": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    agenda = strategy._param_agenda(
        params,
        {"research_metrics": {"components": {"color_mean": 0.50, "color_p95": 0.45}}},
    )
    ranked = [item["param"] for item in agenda[:3]]

    assert "u_Saturation" in ranked
    assert "u_GammaPower" in ranked


def test_param_ranking_reports_all_searchable_params_and_candidate_pool_is_limited():
    shader_params = [
        ShaderParam(f"u_Color{i}", "Float", default=1.0, range_min=0.0, range_max=2.0)
        for i in range(14)
    ]
    params = {param.name: 1.0 for param in shader_params}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    scheduler = strategy._scheduler_state(
        "base_color",
        {"research_metrics": {"components": {"color_mean": 0.50}}},
    )

    assert scheduler["search_param_count"] == 14
    assert scheduler["all_searchable_param_count"] == 14
    assert len(scheduler["param_ranking"]) == 14
    assert len(scheduler["param_candidate_pool"]) == 10
    assert scheduler["param_candidate_pool_size"] == 10


def test_scheduler_reports_runtime_gated_params_separately():
    params = {**_params(), "u_FresnelIntensity": 0.0}
    graph = build_shader_effect_graph(_shader_params(), material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=_shader_params(),
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    scheduler = strategy._scheduler_state(
        "fresnel",
        {"research_metrics": {"components": {"highlight": 0.40}}},
        base_params=params,
    )

    assert scheduler["all_searchable_param_count"] > scheduler["search_param_count"]
    assert scheduler["gated_param_count"] >= 1
    assert any(item["param"] == "u_FresnelColor" for item in scheduler["gated_params"])
    assert any(item["param"] == "u_FresnelIntensity" for item in scheduler["activation_candidates"])


def test_semantic_group_uses_param_priority_before_group_axis_order():
    shader_params = [
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_NormalScale": 1.0, "u_Saturation": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )

    _, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={"research_metrics": {"components": {"color_mean": 0.50}}},
            diff_score=0.4,
            fit_score=0.6,
            state=AdjustmentState(best_params=params, best_fit_score=0.6, best_fit_params=params),
        )
    )

    assert decision["semantic_action"] == "param_priority_search"
    assert decision["param_priority_choice"]["param"] == "u_Saturation"


def test_fresh_fit_does_not_force_accept_isolation_candidate():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_RimIntensity", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_Color": [1, 1, 1, 1], "u_RimIntensity": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="fresh_fit",
    )

    _, decision = strategy.propose(
        StrategyContext(
            iteration=0,
            current_params=params,
            analysis={"research_metrics": {"components": {"color_mean": 0.40}}},
            diff_score=0.3,
            fit_score=0.65,
            state=AdjustmentState(best_params=params, best_fit_score=0.65, best_fit_params=params),
        )
    )

    assert decision.get("semantic_action") != "isolate_base_color"
    assert decision.get("stage", {}).get("name") != "isolate_base"


def test_breakthrough_waits_for_required_bottleneck_groups_to_be_sampled():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
        ShaderParam("u_GammaPower", "Float", default=1.0, range_min=0.05, range_max=3.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_ShadowSmoothness", "Float", default=0.5, range_min=0.0, range_max=1.0),
        ShaderParam("u_SpecularIntensity", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_ReflectColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_NormalScale", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {
        "u_Color": [1, 1, 1, 1],
        "u_TexPower": 1.0,
        "u_GammaPower": 1.0,
        "u_Saturation": 1.0,
        "u_ShadowSmoothness": 0.5,
        "u_SpecularIntensity": 1.0,
        "u_ReflectColor": [1, 1, 1, 1],
        "u_NormalScale": 1.0,
    }
    graph = build_shader_effect_graph(shader_params, material_params=params)
    strategy = SemanticGroupStrategy(
        initial_params=params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._force_breakthrough = True
    analysis = {"research_metrics": {"components": {"color_mean": 0.50, "highlight": 0.30}}}

    assert strategy._scheduler_state("base_color", analysis)["phase"] == "refinement"

    for group_name in strategy._required_groups_before_breakthrough(analysis):
        state = strategy._state_for_group(group_name)
        state["visit_attempts"] = strategy._minimum_group_coverage(group_name)
        state["no_improve"] = 2

    assert strategy._scheduler_state("base_color", analysis)["phase"] == "breakthrough"


def test_breakthrough_queue_uses_subspace_batch_instead_of_color_joint_population():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_Contrast", "Float", default=1.0, range_min=0.0, range_max=2.0),
    ]
    params = {"u_Color": [0.5, 0.5, 0.5, 1], "u_TexPower": 1.0, "u_Saturation": 1.0, "u_Contrast": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    generator = SemanticCandidateGenerator(
        graph=graph,
        shader_params=shader_params,
        encoder_cls=ParameterEncoder,
        step_schedule=[0.25, 0.14],
    )
    archive = TopKArchive(capacity=4)
    archive.add(
        params={"u_Color": [0.55, 0.55, 0.55, 1], "u_TexPower": 1.2, "u_Saturation": 0.9, "u_Contrast": 1.1},
        fit_score=0.82,
        metrics=metric_vector_from_analysis({"research_metrics": {"components": {"color_mean": 0.20}}}, 0.82),
    )
    queue = BreakthroughCandidateQueue(max_size=8)

    queue.ensure(
        base_params=params,
        base_fit_score=0.80,
        analysis={"research_metrics": {"components": {"color_mean": 0.30, "color_p95": 0.25}}},
        iteration=12,
        group_cycle=3,
        groups_by_name=graph.groups,
        group_order=list(graph.groups),
        group_scores={name: 1.0 for name in graph.groups},
        active_groups=set(graph.groups),
        bottleneck={"color_mean": 0.30, "color_p95": 0.25},
        archive=archive,
        generator=generator,
        param_agenda=[
            {"param": "u_Color", "priority": 1.0, "group": "base_color"},
            {"param": "u_TexPower", "priority": 0.9, "group": "base_color"},
            {"param": "u_Saturation", "priority": 0.8, "group": "color_grade"},
            {"param": "u_Contrast", "priority": 0.7, "group": "color_grade"},
        ],
    )

    popped = [queue.pop() for _ in range(8)]
    payloads = [item[1] for item in popped if item is not None]
    assert not any(payload.get("candidate_kind") == "color_joint_population" for payload in payloads)
    assert any(payload.get("candidate_kind") == "subspace_batch" for payload in payloads)

    queue.ensure(
        base_params=params,
        base_fit_score=0.80,
        analysis={"research_metrics": {"components": {"color_mean": 0.30, "color_p95": 0.25}}},
        iteration=13,
        group_cycle=3,
        groups_by_name=graph.groups,
        group_order=list(graph.groups),
        group_scores={name: 1.0 for name in graph.groups},
        active_groups=set(graph.groups),
        bottleneck={"color_mean": 0.30, "color_p95": 0.25},
        archive=archive,
        generator=generator,
        param_agenda=[
            {"param": "u_Color", "priority": 1.0, "group": "base_color"},
            {"param": "u_TexPower", "priority": 0.9, "group": "base_color"},
            {"param": "u_Saturation", "priority": 0.8, "group": "color_grade"},
            {"param": "u_Contrast", "priority": 0.7, "group": "color_grade"},
        ],
    )
    regenerated = [queue.pop() for _ in range(8)]
    regenerated_payloads = [item[1] for item in regenerated if item is not None]
    assert not any(payload.get("candidate_kind") == "color_joint_population" for payload in regenerated_payloads)
    assert queue.summary()["subspace_batch_generated_count"] >= 1


def test_breakthrough_queue_uses_param_agenda_candidates():
    shader_params = [
        ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0),
        ShaderParam("u_GammaPower", "Float", default=1.0, range_min=0.05, range_max=3.0),
    ]
    params = {"u_Saturation": 1.0, "u_GammaPower": 1.0}
    graph = build_shader_effect_graph(shader_params, material_params=params)
    generator = SemanticCandidateGenerator(
        graph=graph,
        shader_params=shader_params,
        encoder_cls=ParameterEncoder,
        step_schedule=[0.25, 0.14],
    )
    queue = BreakthroughCandidateQueue(max_size=6)

    queue.ensure(
        base_params=params,
        base_fit_score=0.70,
        analysis={"research_metrics": {"components": {"color_mean": 0.30}}},
        iteration=20,
        group_cycle=3,
        groups_by_name=graph.groups,
        group_order=list(graph.groups),
        group_scores={name: 1.0 for name in graph.groups},
        active_groups=set(graph.groups),
        bottleneck={"color_mean": 0.30},
        archive=TopKArchive(),
        generator=generator,
        param_agenda=[
            {"param": "u_Saturation", "priority": 1.0, "semantic_relevance": 0.1},
            {"param": "u_GammaPower", "priority": 0.8, "semantic_relevance": 0.1},
        ],
    )

    payloads = [item[1] for item in [queue.pop() for _ in range(6)] if item is not None]
    assert any(payload.get("candidate_kind") == "param_agenda_population" for payload in payloads)


def test_acceptance_policy_rejects_primary_bottleneck_regression():
    policy = AcceptancePolicy(bottleneck_worsen_soft_limit=0.04)
    base = metric_vector_from_analysis(
        {"research_metrics": {"components": {"color_mean": 0.30, "detail_texture": 0.10}}},
        0.80,
    )
    candidate = metric_vector_from_analysis(
        {"research_metrics": {"components": {"color_mean": 0.36, "detail_texture": 0.01}}},
        0.803,
    )

    decision = policy.evaluate(
        base=base,
        candidate=candidate,
        fit_delta=0.003,
        min_improvement=0.002,
        phase="breakthrough",
    )

    assert decision.accepted is False
    assert decision.reason == "primary_bottleneck_worsened"


def test_semantic_group_breakthrough_continues_trust_region_below_global_best():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
    ]
    base_params = {"u_Color": [1, 1, 1, 1], "u_TexPower": 1.0}
    candidate_params = {"u_Color": [0.95, 1, 1, 1], "u_TexPower": 1.1}
    graph = build_shader_effect_graph(shader_params, material_params=base_params)
    strategy = SemanticGroupStrategy(
        initial_params=base_params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._force_breakthrough = True
    strategy._trust_region.ensure(center_params=base_params, fit_score=0.63)
    strategy._pending = {
        "group": "__breakthrough__",
        "kind": "local_population",
        "base_params": dict(base_params),
        "base_fit_score": 0.63,
        "base_metrics": metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.40}}},
            0.63,
        ),
        "changed_params": ["u_Color", "u_TexPower"],
    }

    result = strategy._consume_pending(
        StrategyContext(
            iteration=12,
            current_params=candidate_params,
            analysis={"research_metrics": {"components": {"color_mean": 0.36}}},
            diff_score=0.2,
            fit_score=0.64,
            state=AdjustmentState(
                best_params=base_params,
                best_fit_score=0.66,
                best_fit_params=base_params,
            ),
        )
    )

    assert result["accepted"] is True
    assert result["outcome"] == "accepted_trust_region_branch"
    assert result["next_base_params"] == candidate_params
    summary = strategy._trust_region.summary()
    assert summary["active"] is True
    assert summary["center_fit_score"] == pytest.approx(0.64)


def test_checkpoint_branch_accepts_below_global_best_without_rollback():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
    ]
    base_params = {"u_Color": [1, 1, 1, 1], "u_TexPower": 1.0}
    candidate_params = {"u_Color": [0.95, 1, 1, 1], "u_TexPower": 1.1}
    graph = build_shader_effect_graph(shader_params, material_params=base_params)
    strategy = SemanticGroupStrategy(
        initial_params=base_params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._pending = {
        "group": "base_color",
        "kind": "param_priority",
        "base_params": dict(base_params),
        "base_fit_score": 0.63,
        "base_metrics": metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.40}}},
            0.63,
        ),
        "changed_params": ["u_TexPower"],
    }

    result = strategy._consume_pending(
        StrategyContext(
            iteration=12,
            current_params=candidate_params,
            analysis={"research_metrics": {"components": {"color_mean": 0.36}}},
            diff_score=0.2,
            fit_score=0.64,
            state=AdjustmentState(
                best_params=base_params,
                best_fit_score=0.74,
                best_fit_params=base_params,
            ),
        )
    )

    assert result["accepted"] is True
    assert result["outcome"] == "accepted_checkpoint_branch"
    assert result["next_base_params"] == candidate_params


def test_rejected_candidate_keeps_branch_base_instead_of_global_best():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
    ]
    best_params = {"u_Color": [1, 1, 1, 1], "u_TexPower": 1.0}
    branch_params = {"u_Color": [0.95, 1, 1, 1], "u_TexPower": 1.1}
    candidate_params = {"u_Color": [0.9, 1, 1, 1], "u_TexPower": 1.1}
    graph = build_shader_effect_graph(shader_params, material_params=best_params)
    strategy = SemanticGroupStrategy(
        initial_params=best_params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._pending = {
        "group": "base_color",
        "kind": "param_priority",
        "base_params": dict(branch_params),
        "base_fit_score": 0.64,
        "base_metrics": metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.40}}},
            0.64,
        ),
        "changed_params": ["u_Color"],
    }

    result = strategy._consume_pending(
        StrategyContext(
            iteration=13,
            current_params=candidate_params,
            analysis={"research_metrics": {"components": {"color_mean": 0.55}}},
            diff_score=0.3,
            fit_score=0.62,
            state=AdjustmentState(
                best_params=best_params,
                best_fit_score=0.74,
                best_fit_params=best_params,
            ),
        )
    )

    assert result["accepted"] is False
    assert result["outcome"] == "rejected_keep_branch_base"
    assert result["next_base_params"] == branch_params


def test_checkpoint_branch_can_accept_exploratory_drop_within_drift_budget():
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_TexPower", "Float", default=1.0, range_min=0.1, range_max=3.0),
    ]
    best_params = {"u_Color": [1, 1, 1, 1], "u_TexPower": 1.0}
    branch_params = {"u_Color": [0.95, 1, 1, 1], "u_TexPower": 1.1}
    candidate_params = {"u_Color": [0.9, 1, 1, 1], "u_TexPower": 1.1}
    graph = build_shader_effect_graph(shader_params, material_params=best_params)
    strategy = SemanticGroupStrategy(
        initial_params=best_params,
        shader_params=shader_params,
        graph=graph,
        auto_adjust_mode="refine_current",
    )
    strategy._pending = {
        "group": "base_color",
        "kind": "param_priority",
        "base_params": dict(branch_params),
        "base_fit_score": 0.64,
        "base_metrics": metric_vector_from_analysis(
            {"research_metrics": {"components": {"color_mean": 0.40}}},
            0.64,
        ),
        "changed_params": ["u_Color"],
    }

    result = strategy._consume_pending(
        StrategyContext(
            iteration=13,
            current_params=candidate_params,
            analysis={"research_metrics": {"components": {"color_mean": 0.39}}},
            diff_score=0.3,
            fit_score=0.62,
            state=AdjustmentState(
                best_params=best_params,
                best_fit_score=0.74,
                best_fit_params=best_params,
            ),
        )
    )

    assert result["accepted"] is True
    assert result["branch_exploratory_accept"] is True
    assert result["outcome"] == "exploratory_accept_checkpoint_branch"
    assert result["next_base_params"] == candidate_params


def test_branch_drift_guard_rolls_back_only_after_wide_hard_drop():
    guard = BranchDriftGuard(recovery_window=4)
    checkpoint = {"u_Color": [1, 1, 1, 1]}
    guard.update_checkpoint(params=checkpoint, fit_score=0.75)

    soft = guard.observe(iteration=1, params={"u_Color": [0.8, 1, 1, 1]}, fit_score=0.61)
    assert soft.action == "soft_drift"
    assert soft.should_rollback is False

    hard = guard.observe(iteration=2, params={"u_Color": [0.5, 1, 1, 1]}, fit_score=0.52)
    assert hard.action == "hard_drift"
    assert hard.should_rollback is True


def test_trust_region_branch_expands_and_shrinks_radius():
    branch = TrustRegionBranch(initial_radius=1.0, min_radius=0.2, expand=1.2, shrink=0.5, failure_limit=2)
    branch.ensure(center_params={"u_Color": [1, 1, 1, 1]}, fit_score=0.60)

    branch.record_success(params={"u_Color": [0.9, 1, 1, 1]}, fit_score=0.62, min_improvement=0.001)
    branch.record_success(params={"u_Color": [0.8, 1, 1, 1]}, fit_score=0.64, min_improvement=0.001)
    assert branch.summary()["radius"] == pytest.approx(1.2)

    branch.record_failure()
    branch.record_failure()
    assert branch.summary()["radius"] == pytest.approx(0.6)
    assert branch.summary()["active"] is True


def test_effective_laya_control_schema_normalizes_searchable_search_param_conflict():
    auto_schema = {
        "groups": [
            {
                "id": "color_grade",
                "enabled": True,
                "controls": [
                    {
                        "name": "u_Saturation",
                        "searchable": True,
                        "is_search_param": False,
                        "locked_fields": ["searchable"],
                    }
                ],
            }
        ]
    }

    effective = build_effective_laya_control_schema(auto_schema, {"schema_version": 1, "controls": {}, "groups": {}})

    control = effective["groups"][0]["controls"][0]
    assert control["is_search_param"] is True
    assert effective["diagnostics"][0]["code"] == "searchable_not_search_param"


def test_fit_config_keeps_searchable_param_when_only_searchable_field_is_locked():
    graph = build_shader_effect_graph(
        [ShaderParam("u_Saturation", "Float", default=1.0, range_min=0.0, range_max=2.0)],
        material_params={"u_Saturation": 1.0},
    ).to_dict()
    effective_schema = {
        "groups": [
            {
                "id": "color_grade",
                "enabled": True,
                "controls": [
                    {
                        "name": "u_Saturation",
                        "group": "color_grade",
                        "searchable": True,
                        "is_search_param": False,
                        "locked_fields": ["searchable"],
                    }
                ],
            }
        ]
    }

    patched = _apply_effective_laya_control_schema(graph, effective_schema, {})

    assert patched["groups"]["color_grade"]["search_params"] == ["u_Saturation"]
