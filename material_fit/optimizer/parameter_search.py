from __future__ import annotations

from typing import Any

from ..shared.models import FitStage, ShaderParam
from .param_policy import (
    fixed_optimizer_param_reason,
    is_numeric_search_value,
    is_texture_param,
    ordered_param_names,
    zero_search_value,
)


DEFAULT_STAGES: list[FitStage] = [
    FitStage("base_color", ["u_BaseColor", "u_Gamma_Power", "u_AdjustHue", "u_AdjustSaturation", "u_AdjustLightness", "u_ContrastScale"], "基础色、亮度、饱和度"),
    FitStage("diffuse", ["u_DiffuseThreshold", "u_DiffuseSmoothness", "u_ShadowColor"], "明暗层次"),
    FitStage("specular", ["u_SpecularColor", "u_SpecularIntensity", "u_SpecularThreshold", "u_SpecularSmooth", "u_GGXSpecular", "u_Smoothness"], "主高光"),
    FitStage("reflection", ["u_IBLMapIntensity", "u_IBLMapPower", "u_IBLMapColor", "u_EnvironmentReflections", "u_Metallic"], "环境反射"),
    FitStage("matcap", ["u_MatcapStrength", "u_MatcapPow", "u_MatcapAngle", "u_MatcapColor", "u_MatcapAddStrength", "u_MatcapAddPow", "u_MatcapAddAngle", "u_MatcapAddColor"], "材质球捕捉贴图"),
    FitStage("fresnel_emission", ["u_FresnelColor", "u_FresnelThreshold", "u_FresnelSmooth", "u_FresnelIntensity", "u_FresnelPow", "u_EmissionColor", "u_EmissionScale"], "菲涅尔和自发光"),
]


# Shader uniform types that are texture *bindings*. These never live as
# top-level scalar props in a .lmat — they live inside ``props.textures[]``
# as ``{path, name, ...}``. Treating their string defaults (``"white"``,
# ``"bump"``, ``"black"``) as scalar uniforms would silently corrupt the
# .lmat by introducing ``props.u_BaseMap = "white"`` etc., which Laya then
# fails to parse.
def _is_numeric_default(value: Any) -> bool:
    if isinstance(value, bool):
        return True  # bool is fine, Laya stores bool as bool
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return all(isinstance(x, (int, float, bool)) for x in value)
    return False


def build_initial_params(laya_material_params: dict[str, Any], shader_params: list[ShaderParam]) -> dict[str, Any]:
    """Build the set of scalar/vector uniforms safe to write into props.

    Rules:

    * If the .lmat already has a value for the param, use that (this is the
      authoritative source and we don't want shader defaults to clobber it).
    * Otherwise, only fall back to the shader default when the param is a
      *numeric* uniform (scalar, vec2/3/4, bool). Texture-binding params and
      string defaults are deliberately skipped — those go through the
      ``props.textures[]`` array instead.
    """

    result: dict[str, Any] = {}
    for param in shader_params:
        if param.name in laya_material_params:
            result[param.name] = laya_material_params[param.name]
            continue
        if is_texture_param(param):
            continue
        if param.default is None:
            continue
        if not _is_numeric_default(param.default):
            continue
        result[param.name] = param.default
    return result


def build_zero_searchable_initial_params(
    baseline_params: dict[str, Any],
    shader_params: list[ShaderParam],
    *,
    search_param_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return a zero-start dict that keeps material-validity params intact."""

    param_by_name = {param.name: param for param in shader_params}
    search_names = set(search_param_names) if search_param_names is not None else None
    result = {name: _clone_param_value(value) for name, value in baseline_params.items()}
    for name in ordered_param_names(baseline_params, shader_params):
        param = param_by_name.get(name)
        if search_names is not None and name not in search_names:
            continue
        if fixed_optimizer_param_reason(name, param) is not None:
            continue
        value = baseline_params.get(name)
        if not is_numeric_search_value(value):
            continue
        result[name] = zero_search_value(name, value, param)
    return result


def build_param_policy_audit(
    params: dict[str, Any],
    shader_params: list[ShaderParam],
    *,
    search_param_names: set[str] | list[str] | tuple[str, ...] | None = None,
    allow_scene_lighting_search: bool = False,
) -> dict[str, Any]:
    """Describe which params are searchable and which are locked for a run."""

    param_by_name = {param.name: param for param in shader_params}
    search_names = set(search_param_names) if search_param_names is not None else None
    searchable: list[dict[str, Any]] = []
    locked: list[dict[str, Any]] = []
    for name in ordered_param_names(params, shader_params):
        param = param_by_name.get(name)
        value = params.get(name)
        reason = fixed_optimizer_param_reason(
            name,
            param,
            allow_scene_lighting=allow_scene_lighting_search,
        )
        if reason is None and search_names is not None and name not in search_names:
            reason = "not active in semantic search graph"
        if reason is None and not is_numeric_search_value(value):
            reason = "non-numeric parameter value"
        if reason is None:
            searchable.append(_policy_row(name, value, param, "searchable"))
        else:
            row = _policy_row(name, value, param, "locked")
            row["reason"] = reason
            locked.append(row)
    return {
        "searchable_param_count": len(searchable),
        "locked_param_count": len(locked),
        "allow_scene_lighting_search": bool(allow_scene_lighting_search),
        "searchable_params": searchable,
        "locked_params": locked,
    }


def _policy_row(name: str, value: Any, param: ShaderParam | None, status: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "param_type": str(param.param_type) if param is not None else "",
        "value_shape": _value_shape(value),
    }


def _value_shape(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


def _clone_param_value(value: Any) -> Any:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def build_stage_plan(shader_params: list[ShaderParam]) -> list[FitStage]:
    available = {param.name for param in shader_params}
    stages: list[FitStage] = []
    for stage in DEFAULT_STAGES:
        params = [name for name in stage.params if name in available]
        if params:
            stages.append(FitStage(stage.name, params, stage.description))
    return stages


def generate_probe_candidates(base_params: dict[str, Any], stage: FitStage, shader_params: list[ShaderParam]) -> list[dict[str, Any]]:
    """Generate a tiny deterministic candidate set for pipeline smoke tests.

    Real coordinate descent / local refinement will replace this in a later phase.
    """

    param_by_name = {param.name: param for param in shader_params}
    candidates = [dict(base_params)]
    for name in stage.params:
        param = param_by_name.get(name)
        value = base_params.get(name)
        if not isinstance(value, (int, float)) or param is None:
            continue
        low = param.range_min if param.range_min is not None else max(0.0, float(value) * 0.5)
        high = param.range_max if param.range_max is not None else float(value) * 1.5 + 0.1
        for probe in (low, high):
            candidate = dict(base_params)
            candidate[name] = probe
            candidates.append(candidate)
    return candidates
