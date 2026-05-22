from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..shared.models import FitStage, ShaderParam
from .parameter_search import build_stage_plan


@dataclass(frozen=True)
class AdjustmentStagePolicy:
    """Shader-aware policy for one fitting stage.

    The stage order intentionally starts from broad, high-impact controls and
    then moves toward increasingly local lighting effects. This avoids random
    wandering in the large Laya parameter space.
    """

    name: str
    description: str
    channels: list[str]
    params: list[str]
    max_iterations: int = 2
    target_score: float = 0.04


@dataclass
class AdjustmentState:
    iteration: int = 0
    stage_index: int = 0
    # Per-stage tracking — the missing piece that caused the "12 iterations
    # all stuck in base_color" bug. Without these, choose_stage had no way
    # to know how long it had been grinding on a single stage and so it
    # never advanced when the stage's MAE refused to drop below target_score.
    stage_iteration: int = 0
    stage_best_score: float = math.inf
    stage_no_improve: int = 0
    cycle: int = 0
    best_score: float = math.inf
    best_params: dict[str, Any] = field(default_factory=dict)
    best_fit_score: float = -math.inf
    best_fit_params: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    # Number of consecutive *global* iterations with no improvement to
    # ``best_score``. Used to abort the whole run when no stage helps.
    global_no_improve: int = 0


def build_adjustment_policies(shader_params: list[ShaderParam]) -> list[AdjustmentStagePolicy]:
    """Build the concrete tuning order for FishStandard-like Laya shaders."""

    available = {param.name for param in shader_params}
    raw: list[AdjustmentStagePolicy] = [
        AdjustmentStagePolicy(
            name="base_color",
            description="先锁定主体基础色、整体亮度和主色偏；只动 u_BaseColor/u_Gamma_Power，避免高光与边缘光干扰基础判断。",
            channels=["base_color_main_texture"],
            params=["u_BaseColor", "u_Gamma_Power"],
            max_iterations=3,
            target_score=0.055,
        ),
        AdjustmentStagePolicy(
            name="shadow_diffuse",
            description="基础色接近后调整明暗层次、暗部压暗/提亮和 Toon diffuse 过渡。",
            channels=["shadow_occlusion", "base_color_main_texture"],
            params=["u_OcclusionStrength", "u_GIIntensity", "u_DiffuseThreshold", "u_DiffuseSmoothness", "u_ShadowColor"],
            max_iterations=2,
            target_score=0.06,
        ),
        AdjustmentStagePolicy(
            name="specular_smoothness",
            description="再调主高光亮度、范围、金属度和光滑度，解决高亮区域偏暗/偏亮。",
            channels=["metallic_smoothness_specular"],
            params=["u_SpecularIntensity", "u_SpecularColor", "u_SpecularThreshold", "u_SpecularSmooth", "u_GGXSpecular", "u_Metallic", "u_Smoothness"],
            max_iterations=2,
            target_score=0.055,
        ),
        AdjustmentStagePolicy(
            name="reflection_matcap",
            description="随后调整环境反射、IBL 和 Matcap，让大面积反射/材质球层次接近 Unity。",
            channels=["environment_reflection_matcap"],
            params=["u_IBLMapIntensity", "u_IBLMapPower", "u_IBLMapColor", "u_EnvironmentReflections", "u_MatcapStrength", "u_MatcapPow", "u_MatcapColor", "u_MatcapAddStrength"],
            max_iterations=2,
            target_score=0.055,
        ),
        AdjustmentStagePolicy(
            name="fresnel_emission",
            description="最后处理局部边缘光、Fresnel 和自发光，避免过早把局部效果当成基础色来修。",
            channels=["fresnel_rim", "emission", "center_vs_edge_balance"],
            params=["u_FresnelColor", "u_FresnelIntensity", "u_FresnelThreshold", "u_FresnelSmooth", "u_FresnelPow", "u_EmissionColor", "u_EmissionScale"],
            max_iterations=2,
            target_score=0.05,
        ),
        AdjustmentStagePolicy(
            name="global_color_grade",
            description="当材质主要结构接近后，只用 HSV/对比度做小幅全局收尾。",
            channels=["color_grading_hsv_contrast"],
            params=["u_AdjustHue", "u_AdjustSaturation", "u_AdjustLightness", "u_ContrastScale"],
            max_iterations=2,
            target_score=0.04,
        ),
    ]
    return [
        AdjustmentStagePolicy(
            name=item.name,
            description=item.description,
            channels=item.channels,
            params=[param for param in item.params if param in available],
            max_iterations=item.max_iterations,
            target_score=item.target_score,
        )
        for item in raw
        if any(param in available for param in item.params)
    ]


def policies_to_fit_stages(policies: list[AdjustmentStagePolicy]) -> list[FitStage]:
    if policies:
        return [FitStage(policy.name, policy.params, policy.description) for policy in policies]
    return []


STUCK_NO_IMPROVE_LIMIT = 2
GLOBAL_NO_IMPROVE_LIMIT = 4


def choose_stage(
    policies: list[AdjustmentStagePolicy],
    analysis: dict[str, Any],
    state: AdjustmentState,
) -> tuple[AdjustmentStagePolicy | None, dict[str, Any]]:
    """Return the next stage to optimize, advancing past converged/stuck/exhausted stages.

    Each call may transition through several stages in one go (e.g. if a
    stage's channel score is already below target the moment we reach it,
    we just move on to the next instead of wasting an iteration on it).

    Returns a tuple ``(policy, info)`` where ``info`` records the reason
    for any transitions and the current stage iteration counter, so the
    caller can log it into ``decision.json``.
    """

    if not policies:
        return None, {"transitions": [], "selected": None}

    channels = analysis.get("material_channels", {}) if isinstance(analysis, dict) else {}
    transitions: list[dict[str, Any]] = []

    # Hard ceiling on stage advances per call so a buggy policy table can't
    # turn this into an infinite loop. Each stage can be visited at most
    # twice per call (once to check, once after a cycle restart).
    safety = (len(policies) + 1) * 2

    while safety > 0:
        safety -= 1
        idx = state.stage_index

        if idx >= len(policies):
            # Finished a full pass; loop back for refinement so late changes
            # to (e.g.) matcap/IBL/fresnel can re-influence the base color.
            transitions.append({"event": "cycle_restart", "cycle": state.cycle + 1})
            state.cycle += 1
            state.stage_index = 0
            state.stage_iteration = 0
            state.stage_best_score = math.inf
            state.stage_no_improve = 0
            continue

        policy = policies[idx]
        score = _policy_channel_score(policy, channels)
        score_finite = math.isfinite(score)

        # Already converged on this stage? Skip it.
        if score_finite and score <= policy.target_score and state.stage_iteration == 0:
            transitions.append({
                "event": "skip",
                "from_stage": policy.name,
                "reason": "channel_already_below_target",
                "channel_score": score,
                "target": policy.target_score,
            })
            state.stage_index += 1
            state.stage_iteration = 0
            state.stage_best_score = math.inf
            state.stage_no_improve = 0
            continue

        # Already converged after some work on this stage? Advance.
        if score_finite and score <= policy.target_score and state.stage_iteration > 0:
            transitions.append({
                "event": "advance",
                "from_stage": policy.name,
                "reason": "target_reached",
                "channel_score": score,
                "target": policy.target_score,
                "iterations_spent": state.stage_iteration,
            })
            state.stage_index += 1
            state.stage_iteration = 0
            state.stage_best_score = math.inf
            state.stage_no_improve = 0
            continue

        # Spent the iteration budget without converging? Advance — beating a
        # dead horse on one stage is exactly what produced the user-visible
        # "12 iters all in base_color" bug.
        if state.stage_iteration >= policy.max_iterations:
            transitions.append({
                "event": "advance",
                "from_stage": policy.name,
                "reason": "max_iterations_exhausted",
                "channel_score": score if score_finite else None,
                "best_on_stage": state.stage_best_score if math.isfinite(state.stage_best_score) else None,
                "iterations_spent": state.stage_iteration,
                "max_iterations": policy.max_iterations,
            })
            state.stage_index += 1
            state.stage_iteration = 0
            state.stage_best_score = math.inf
            state.stage_no_improve = 0
            continue

        # Stuck — channel score didn't improve for two iterations in a row.
        # The current stage's params have low leverage on this material.
        if (
            state.stage_iteration >= 2
            and state.stage_no_improve >= STUCK_NO_IMPROVE_LIMIT
        ):
            transitions.append({
                "event": "advance",
                "from_stage": policy.name,
                "reason": "no_improvement_on_stage",
                "channel_score": score if score_finite else None,
                "best_on_stage": state.stage_best_score if math.isfinite(state.stage_best_score) else None,
                "iterations_spent": state.stage_iteration,
                "consecutive_no_improve": state.stage_no_improve,
            })
            state.stage_index += 1
            state.stage_iteration = 0
            state.stage_best_score = math.inf
            state.stage_no_improve = 0
            continue

        # We're going to work this stage on this iteration.
        return policy, {
            "transitions": transitions,
            "selected": policy.name,
            "stage_iteration": state.stage_iteration,
            "stage_best_score": state.stage_best_score if math.isfinite(state.stage_best_score) else None,
            "stage_no_improve": state.stage_no_improve,
            "cycle": state.cycle,
            "channel_score": score if score_finite else None,
        }

    # Safety bail-out — all stages have been cycled-and-exhausted in a single
    # call. Pick the last stage as a fallback so the run can still emit a
    # decision, but flag it.
    transitions.append({"event": "cycle_safety_bailout"})
    state.stage_index = len(policies) - 1
    state.stage_iteration = 0
    return policies[-1], {
        "transitions": transitions,
        "selected": policies[-1].name,
        "stage_iteration": 0,
        "cycle": state.cycle,
        "warning": "cycle_safety_bailout",
    }


def update_stage_progress(
    state: AdjustmentState,
    policy: AdjustmentStagePolicy,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Advance per-stage iteration counters after a propose-and-render cycle.

    Should be called once per iteration *after* the new candidate has been
    rendered and re-analysed (so ``analysis`` is the post-change diff). The
    returned dict is suitable for embedding into ``decision.json`` to
    debug stage progression.
    """
    channels = analysis.get("material_channels", {}) if isinstance(analysis, dict) else {}
    score = _policy_channel_score(policy, channels)
    score_finite = math.isfinite(score)
    improved = score_finite and score < state.stage_best_score - 1e-6
    if improved:
        state.stage_best_score = score
        state.stage_no_improve = 0
    else:
        state.stage_no_improve += 1
    state.stage_iteration += 1
    return {
        "stage": policy.name,
        "stage_iteration": state.stage_iteration,
        "stage_best_score": state.stage_best_score if math.isfinite(state.stage_best_score) else None,
        "stage_no_improve": state.stage_no_improve,
        "channel_score_after": score if score_finite else None,
        "improved": improved,
    }


def should_abort_global(state: AdjustmentState) -> bool:
    """Return True when the run has stagnated globally and should bail out."""
    return state.global_no_improve >= GLOBAL_NO_IMPROVE_LIMIT


def propose_next_params(
    current_params: dict[str, Any],
    shader_params: list[ShaderParam],
    analysis: dict[str, Any],
    policy: AdjustmentStagePolicy,
    *,
    iteration: int = 0,
    unity_material_params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create the next Laya parameter set from material-oriented diff metrics."""

    param_info = {param.name: param for param in shader_params}
    channels = analysis.get("material_channels", {}) if isinstance(analysis, dict) else {}
    next_params = dict(current_params)
    changes: list[dict[str, Any]] = []
    unity_material_params = unity_material_params or {}
    gain = max(0.35, 0.72 * (0.86 ** max(iteration, 0)))

    def set_param(name: str, value: Any, reason: str) -> None:
        if name not in policy.params or name not in param_info:
            return
        old = next_params.get(name)
        new = _coerce_to_param(value, old, param_info[name])
        if _almost_equal(old, new):
            return
        next_params[name] = new
        changes.append({"param": name, "old": old, "new": new, "reason": reason})

    if policy.name == "base_color":
        channel = _channel(channels, "base_color_main_texture")
        rgb_bias = _rgb_bias(channel)
        luma_bias = _luma_bias(channel)
        current_color = _color(next_params.get("u_BaseColor", [1, 1, 1, 1]))
        # Positive bias means Laya is brighter/more colored than Unity, so reduce
        # that channel. Negative bias means the opposite.
        adjusted = [max(0.0, current_color[i] * (1.0 - rgb_bias[i] * gain)) for i in range(3)] + [current_color[3]]
        set_param("u_BaseColor", adjusted, "按中间调 RGB signed bias 反向修正主体基础色")
        gamma = _number(next_params.get("u_Gamma_Power"), 1.0)
        set_param("u_Gamma_Power", gamma + luma_bias * 0.9 * gain, "中间调偏亮则增大 gamma，偏暗则减小 gamma")

    elif policy.name == "shadow_diffuse":
        shadow = _channel(channels, "shadow_occlusion")
        base = _channel(channels, "base_color_main_texture")
        shadow_luma = _luma_bias(shadow)
        base_contrast = _contrast_bias(base)
        occ = _number(next_params.get("u_OcclusionStrength"), 1.0)
        gi = _number(next_params.get("u_GIIntensity"), 1.0)
        set_param("u_OcclusionStrength", occ + shadow_luma * 1.2 * gain, "暗部偏亮时增强遮蔽，偏暗时减弱遮蔽")
        set_param("u_GIIntensity", gi - shadow_luma * 0.75 * gain, "暗部整体亮度反向修正 GI 强度")
        threshold = _number(next_params.get("u_DiffuseThreshold"), 0.5)
        smooth = _number(next_params.get("u_DiffuseSmoothness"), 0.1)
        set_param("u_DiffuseThreshold", threshold + shadow_luma * 0.45 * gain, "依据暗部亮度移动 diffuse ramp 阈值")
        set_param("u_DiffuseSmoothness", smooth + abs(base_contrast) * 0.35 * gain, "层次/对比差异较大时略放宽 diffuse 过渡")

    elif policy.name == "specular_smoothness":
        channel = _channel(channels, "metallic_smoothness_specular")
        luma = _luma_bias(channel)
        sat = _sat_bias(channel)
        rgb = _rgb_bias(channel)
        set_param("u_SpecularIntensity", _number(next_params.get("u_SpecularIntensity"), 1.0) - luma * 1.35 * gain, "高亮偏暗则增强主高光，偏亮则降低")
        set_param("u_Smoothness", _number(next_params.get("u_Smoothness"), 0.8) - luma * 0.55 * gain, "高亮不足时提高光滑度以集中反射")
        set_param("u_SpecularThreshold", _number(next_params.get("u_SpecularThreshold"), 0.5) + luma * 0.35 * gain, "微调高光阈值控制高光面积")
        set_param("u_SpecularSmooth", _number(next_params.get("u_SpecularSmooth"), 0.5) + abs(luma) * 0.25 * gain, "高亮差异大时让高光边缘更可搜索")
        current_color = _color(next_params.get("u_SpecularColor", [1, 1, 1, 1]))
        set_param("u_SpecularColor", [max(0.0, current_color[i] * (1.0 - rgb[i] * 0.55 * gain)) for i in range(3)] + [current_color[3]], "反向修正高光色偏")
        if abs(sat) > 0.03:
            set_param("u_GGXSpecular", _number(next_params.get("u_GGXSpecular"), 1.0) - sat * 0.25 * gain, "高光饱和度偏差时调整 GGX/风格化混合")

    elif policy.name == "reflection_matcap":
        channel = _channel(channels, "environment_reflection_matcap")
        luma = _luma_bias(channel)
        rgb = _rgb_bias(channel)
        set_param("u_IBLMapIntensity", _number(next_params.get("u_IBLMapIntensity"), 0.3) - luma * 1.15 * gain, "反射区域偏暗则增强 IBL，偏亮则降低")
        set_param("u_MatcapStrength", _number(next_params.get("u_MatcapStrength"), 0.0) - luma * 0.85 * gain, "用 Matcap 补偿视角相关反射亮度")
        ibl_color = _color(next_params.get("u_IBLMapColor", [1, 1, 1, 1]))
        set_param("u_IBLMapColor", [max(0.0, ibl_color[i] * (1.0 - rgb[i] * 0.45 * gain)) for i in range(3)] + [ibl_color[3]], "反向修正环境反射色偏")
        matcap_color = _color(next_params.get("u_MatcapColor", [1, 1, 1, 1]))
        set_param("u_MatcapColor", [max(0.0, matcap_color[i] * (1.0 - rgb[i] * 0.35 * gain)) for i in range(3)] + [matcap_color[3]], "反向修正 Matcap 色偏")

    elif policy.name == "fresnel_emission":
        fresnel = _channel(channels, "fresnel_rim")
        emission = _channel(channels, "emission")
        balance = _channel(channels, "center_vs_edge_balance")
        edge_luma = _luma_bias(fresnel)
        emission_luma = _luma_bias(emission)
        edge_minus_center = _number(balance.get("edge_minus_center_luma_bias"), 0.0)
        set_param("u_FresnelIntensity", _number(next_params.get("u_FresnelIntensity"), 1.0) - (edge_luma + edge_minus_center) * 1.05 * gain, "边缘相对 Unity 偏暗则增强 Fresnel，偏亮则降低")
        set_param("u_FresnelPow", _number(next_params.get("u_FresnelPow"), 1.0) + edge_minus_center * 0.65 * gain, "按中心/边缘亮度差调节 Fresnel 衰减")
        fresnel_rgb = _rgb_bias(fresnel)
        fresnel_color = _color(next_params.get("u_FresnelColor", [1, 1, 1, 1]))
        set_param("u_FresnelColor", [max(0.0, fresnel_color[i] * (1.0 - fresnel_rgb[i] * 0.55 * gain)) for i in range(3)] + [fresnel_color[3]], "反向修正边缘光色偏")
        set_param("u_EmissionScale", _number(next_params.get("u_EmissionScale"), 1.0) - emission_luma * 0.95 * gain, "极亮区偏暗则增强自发光，偏亮则降低")
        emission_rgb = _rgb_bias(emission)
        emission_color = _color(next_params.get("u_EmissionColor", [0, 0, 0, 1]))
        set_param("u_EmissionColor", [max(0.0, emission_color[i] * (1.0 - emission_rgb[i] * 0.55 * gain)) for i in range(3)] + [emission_color[3]], "反向修正自发光色偏")

    elif policy.name == "global_color_grade":
        channel = _channel(channels, "color_grading_hsv_contrast")
        luma = _luma_bias(channel)
        sat = _sat_bias(channel)
        contrast = _contrast_bias(channel)
        rgb = _rgb_bias(channel)
        hue_bias = (rgb[1] - rgb[0]) * 0.35 + (rgb[2] - rgb[1]) * 0.18
        set_param("u_AdjustLightness", _number(next_params.get("u_AdjustLightness"), 0.0) - luma * 0.7 * gain, "全局亮度收尾")
        set_param("u_AdjustSaturation", _number(next_params.get("u_AdjustSaturation"), 0.0) - sat * 0.8 * gain, "全局饱和度收尾")
        set_param("u_AdjustHue", _number(next_params.get("u_AdjustHue"), 0.0) - hue_bias * gain, "按 RGB 色偏做小幅 hue 收尾")
        set_param("u_ContrastScale", _number(next_params.get("u_ContrastScale"), 0.0) - contrast * 0.65 * gain, "全局对比度收尾")

    # If Unity material JSON contains same-named numeric/color values, softly pull
    # newly changed values toward the known Unity prototype as an anchor.
    for change in list(changes):
        name = change["param"]
        if name not in unity_material_params:
            continue
        anchored = _blend_value(next_params[name], unity_material_params[name], 0.12)
        anchored = _coerce_to_param(anchored, next_params[name], param_info[name])
        if not _almost_equal(next_params[name], anchored):
            change["new_before_unity_anchor"] = next_params[name]
            change["new"] = anchored
            change["reason"] += "；并向 Unity 导出同名参数轻微靠拢"
            next_params[name] = anchored

    decision = {
        "stage": asdict(policy),
        "iteration_gain": gain,
        "score": analysis.get("score"),
        "changes": changes,
        "stop_reason": "no_effective_change" if not changes else "continue",
    }
    return next_params, decision


def load_adjustment_state(path: str | Path) -> AdjustmentState:
    state_path = Path(path)
    if not state_path.exists():
        return AdjustmentState()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return AdjustmentState(
        iteration=int(data.get("iteration", 0)),
        stage_index=int(data.get("stage_index", 0)),
        stage_iteration=int(data.get("stage_iteration", 0)),
        stage_best_score=float(data.get("stage_best_score", math.inf)),
        stage_no_improve=int(data.get("stage_no_improve", 0)),
        cycle=int(data.get("cycle", 0)),
        best_score=float(data.get("best_score", math.inf)),
        best_params=data.get("best_params", {}) if isinstance(data.get("best_params"), dict) else {},
        best_fit_score=float(data.get("best_fit_score", -math.inf)),
        best_fit_params=data.get("best_fit_params", {}) if isinstance(data.get("best_fit_params"), dict) else {},
        history=data.get("history", []) if isinstance(data.get("history"), list) else [],
        global_no_improve=int(data.get("global_no_improve", 0)),
    )


def save_adjustment_state(path: str | Path, state: AdjustmentState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")


def fallback_policies(shader_params: list[ShaderParam]) -> list[AdjustmentStagePolicy]:
    """Fallback for non-FishStandard shaders using the old stage builder."""

    return [
        AdjustmentStagePolicy(stage.name, stage.description, [], stage.params)
        for stage in build_stage_plan(shader_params)
    ]


def _policy_channel_score(policy: AdjustmentStagePolicy, channels: dict[str, Any]) -> float:
    scores = []
    for name in policy.channels:
        channel = channels.get(name, {})
        if isinstance(channel, dict):
            value = channel.get("rgb_mae", channel.get("avg_rgb_mae"))
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                scores.append(float(value))
    return max(scores) if scores else math.inf


def _channel(channels: dict[str, Any], name: str) -> dict[str, Any]:
    value = channels.get(name, {})
    return value if isinstance(value, dict) else {}


def _rgb_bias(channel: dict[str, Any]) -> list[float]:
    value = channel.get("rgb_bias_candidate_minus_reference", [0.0, 0.0, 0.0])
    if not isinstance(value, list) or len(value) < 3:
        return [0.0, 0.0, 0.0]
    return [_number(value[i], 0.0) for i in range(3)]


def _luma_bias(channel: dict[str, Any]) -> float:
    return _number(channel.get("luma_bias_candidate_minus_reference"), 0.0)


def _sat_bias(channel: dict[str, Any]) -> float:
    return _number(channel.get("saturation_bias_candidate_minus_reference"), 0.0)


def _contrast_bias(channel: dict[str, Any]) -> float:
    return _number(channel.get("contrast_bias_candidate_minus_reference"), 0.0)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _color(value: Any) -> list[float]:
    if isinstance(value, list):
        rgba = [_number(item, 1.0) for item in value[:4]]
        while len(rgba) < 4:
            rgba.append(1.0)
        return rgba
    return [1.0, 1.0, 1.0, 1.0]


def _coerce_to_param(value: Any, old: Any, param: ShaderParam) -> Any:
    if isinstance(old, list) or str(param.param_type).lower() in {"color", "vector4"}:
        old_list = old if isinstance(old, list) else param.default if isinstance(param.default, list) else [1, 1, 1, 1]
        value_list = value if isinstance(value, list) else old_list
        limit = len(old_list) if isinstance(old_list, list) else len(value_list)
        return [_clamp_number(_number(value_list[i], _number(old_list[i], 0.0)), param) for i in range(min(len(value_list), limit))]
    if isinstance(value, (int, float)) or isinstance(old, (int, float)):
        return _clamp_number(_number(value, _number(old, 0.0)), param)
    return value


def _clamp_number(value: float, param: ShaderParam) -> float:
    low = param.range_min
    high = param.range_max
    if low is None:
        if any(token in param.name.lower() for token in ("intensity", "strength", "scale", "power", "pow")):
            low = 0.0
        elif any(token in param.name.lower() for token in ("threshold", "smooth", "metallic")):
            low = 0.0
    if high is None:
        if any(token in param.name.lower() for token in ("intensity", "strength", "scale")):
            high = 8.0
        elif any(token in param.name.lower() for token in ("threshold", "smooth", "metallic")):
            high = 1.0
        elif "pow" in param.name.lower() or "power" in param.name.lower():
            high = 10.0
    if low is not None:
        value = max(float(low), value)
    if high is not None:
        value = min(float(high), value)
    return value


def _blend_value(a: Any, b: Any, weight_b: float) -> Any:
    if isinstance(a, list) and isinstance(b, list):
        return [_number(a[i], 0.0) * (1.0 - weight_b) + _number(b[i], _number(a[i], 0.0)) * weight_b for i in range(min(len(a), len(b)))]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) * (1.0 - weight_b) + float(b) * weight_b
    return a


def _almost_equal(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return all(abs(_number(x) - _number(y)) < 1e-6 for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b