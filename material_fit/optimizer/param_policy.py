from __future__ import annotations

import re
from typing import Any

from ..shared.models import ShaderParam


TEXTURE_PARAM_TYPES = frozenset({
    "texture2d",
    "texture",
    "texturecube",
    "sampler2d",
    "sampler",
    "samplercube",
    "rendertexture",
})


def is_texture_param_type(param_type: str) -> bool:
    return str(param_type).strip().lower() in TEXTURE_PARAM_TYPES


def is_texture_param(param: ShaderParam) -> bool:
    return is_texture_param_type(param.param_type)


def fixed_optimizer_param_reason(name: str, param: ShaderParam | None = None) -> str | None:
    """Return why ``name`` must not be part of numeric appearance search."""

    lower = str(name).strip().lower()
    compact = lower.replace("_", "")
    if not lower:
        return "empty parameter name"
    if param is not None and is_texture_param(param):
        return "texture binding"
    if param is not None and str(param.hidden or "").strip().lower() in {"true", "1", "yes"}:
        return "hidden shader parameter"
    if param is not None and str(param.param_type).strip().lower() in {"bool", "boolean"}:
        return "boolean/toggle parameter"
    if lower.startswith("s_"):
        return "engine render-state parameter"
    if _is_uv_transform_name(lower, compact):
        return "texture UV scale/offset"
    if _is_alpha_or_cutoff_name(compact):
        return "alpha/cutoff material-validity parameter"
    if _is_scene_lighting_name(compact):
        return "scene lighting/environment orientation parameter"
    return None


def is_optimizer_fixed_param(name: str, param: ShaderParam | None = None) -> bool:
    return fixed_optimizer_param_reason(name, param) is not None


def is_optimizer_searchable_param(name: str, param: ShaderParam | None = None) -> bool:
    return not is_optimizer_fixed_param(name, param)


def is_numeric_search_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    return False


def zero_search_value(name: str, value: Any, param: ShaderParam | None = None) -> Any:
    """Zero a trainable coordinate while preserving non-trainable alpha."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return 0.0
    if isinstance(value, list) and is_numeric_search_value(value):
        if looks_like_color_param(name, param, len(value)) and len(value) >= 4:
            return [0.0, 0.0, 0.0, *value[3:]]
        return [0.0 for _ in value]
    return value


def looks_like_color_param(name: str, param: ShaderParam | None, length: int) -> bool:
    if param is not None and str(param.param_type).strip().lower() == "color":
        return True
    if length == 4 and re.search(r"color|tint|albedo|emission", name, re.IGNORECASE):
        return True
    return False


def ordered_param_names(params: dict[str, Any], shader_params: list[ShaderParam] | tuple[ShaderParam, ...]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for param in shader_params:
        if param.name in params and param.name not in seen:
            names.append(param.name)
            seen.add(param.name)
    for name in sorted((name for name in params if name not in seen), key=str):
        names.append(name)
        seen.add(name)
    return names


def _is_uv_transform_name(lower: str, compact: str) -> bool:
    if lower.endswith("_st"):
        return True
    if not compact.endswith("st"):
        return False
    return any(token in compact for token in ("tex", "map", "mask", "lmap", "normal", "bump", "maer", "ibl"))


def _is_alpha_or_cutoff_name(compact: str) -> bool:
    if compact in {"alpha", "ualpha", "cutoff", "ucutoff", "alphacutoff"}:
        return True
    return "alphatest" in compact


def _is_scene_lighting_name(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "skyrotate",
            "lightrotate",
            "lightdirection",
            "selflightdir",
        )
    )
