"""Structured search coordinates for the maintained 1504 fish material.

The legacy Pattern16 space remains available as a baseline.  This module
defines the broader, target-independent space used by the Laya oracle gates:

* scene alignment coordinates are searched as a separate global stage;
* material scalars, RGB color channels, and shader offsets are continuous;
* alpha, textures, UV transforms, defines, and render state stay fixed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

from ..shared.models import ShaderParam


SCENE_ALIGNMENT_GROUP = "scene_alignment"
MATERIAL_SCALAR_GROUP = "material_scalar"
MATERIAL_COLOR_GROUP = "material_color"
MATERIAL_OFFSET_GROUP = "material_offset"
MATERIAL_GROUPS = (
    MATERIAL_SCALAR_GROUP,
    MATERIAL_COLOR_GROUP,
    MATERIAL_OFFSET_GROUP,
)
STRUCTURED_GROUP_ORDER = (SCENE_ALIGNMENT_GROUP, *MATERIAL_GROUPS)


@dataclass(frozen=True)
class FishSearchCoordinate:
    """One scalar coordinate inside a scalar or vector shader parameter."""

    param_name: str
    component: int | None
    group: str
    low: float
    high: float
    initial_step: float

    @property
    def coordinate_id(self) -> str:
        if self.component is None:
            return self.param_name
        return f"{self.param_name}[{self.component}]"

    @property
    def min_step(self) -> float:
        return self.initial_step / 16.0

    def read(self, params: dict[str, Any]) -> float:
        value = params[self.param_name]
        if self.component is None:
            return float(value)
        return float(value[self.component])

    def write(self, params: dict[str, Any], value: float) -> dict[str, Any]:
        result = copy.deepcopy(params)
        clamped = min(max(float(value), self.low), self.high)
        if self.component is None:
            result[self.param_name] = clamped
            return result
        vector = list(result[self.param_name])
        vector[self.component] = clamped
        result[self.param_name] = vector
        return result


def _scalar(name: str, group: str, low: float, high: float, step: float) -> FishSearchCoordinate:
    return FishSearchCoordinate(name, None, group, low, high, step)


def _vector_rgb(name: str, *, step: float = 0.15) -> tuple[FishSearchCoordinate, ...]:
    return tuple(
        FishSearchCoordinate(name, component, MATERIAL_COLOR_GROUP, 0.0, 2.0, step)
        for component in range(3)
    )


def _vector4(
    name: str,
    *,
    low: float = -2.0,
    high: float = 2.0,
    step: float = 0.32,
) -> tuple[FishSearchCoordinate, ...]:
    return tuple(
        FishSearchCoordinate(name, component, MATERIAL_OFFSET_GROUP, low, high, step)
        for component in range(4)
    )


_SCENE_COORDINATES: tuple[FishSearchCoordinate, ...] = tuple(
    _scalar(name, SCENE_ALIGNMENT_GROUP, -180.0, 180.0, 22.5)
    for name in (
        "u_SkyRotateX",
        "u_SkyRotateY",
        "u_SkyRotateZ",
        "u_LightRotateX",
        "u_LightRotateY",
        "u_LightRotateZ",
    )
)

_MATERIAL_SCALAR_COORDINATES: tuple[FishSearchCoordinate, ...] = (
    _scalar("u_GammaPower", MATERIAL_SCALAR_GROUP, 0.0001, 3.0, 0.30),
    _scalar("u_Saturation", MATERIAL_SCALAR_GROUP, 0.0, 2.0, 0.15),
    _scalar("u_Contrast", MATERIAL_SCALAR_GROUP, 0.0, 2.0, 0.15),
    _scalar("u_HueShift", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.08),
    _scalar("u_TexPower", MATERIAL_SCALAR_GROUP, 0.1, 3.0, 0.30),
    _scalar("u_AoPower", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.15),
    # The shader declares this as an unbounded positive Float. Real maintained
    # assets use values above 3 (1503 uses about 25.8), so a fish-era cap of 3
    # made those targets unreachable and turned a tiny perturbation into a
    # destructive clamp. Keep a shared conservative search cap instead.
    _scalar("u_EmissionPow", MATERIAL_SCALAR_GROUP, 0.0, 64.0, 4.0),
    _scalar("u_IndirectStrength", MATERIAL_SCALAR_GROUP, 0.0, 3.0, 0.20),
    _scalar("u_NormalScale", MATERIAL_SCALAR_GROUP, 0.0, 1.2, 0.15),
    _scalar("u_ShadowSmoothness", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.10),
    _scalar("u_ShadowThreshold1", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.08),
    _scalar("u_SpecularIntensity", MATERIAL_SCALAR_GROUP, 0.0, 10.0, 0.40),
    _scalar("u_SpecularPower", MATERIAL_SCALAR_GROUP, 1.0, 200.0, 8.0),
    _scalar("u_SpecularThreshold", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.08),
    _scalar("u_SpecularSmoothness", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.10),
    _scalar("u_RimIntensity", MATERIAL_SCALAR_GROUP, 0.0, 10.0, 0.40),
    _scalar("u_RimWidth", MATERIAL_SCALAR_GROUP, 0.0, 10.0, 0.50),
)

# These coordinates are part of the shipped shader, but are dormant unless
# the material enables USE_SECOND_LEVELS.  Keep them out of the immutable
# canonical 40-coordinate policy and expose them only when a caller explicitly
# requests the extended executable parameter space.
_OPTIONAL_SECOND_LEVEL_COORDINATES: tuple[FishSearchCoordinate, ...] = (
    _scalar("u_ShadowThreshold2", MATERIAL_SCALAR_GROUP, 0.0, 1.0, 0.08),
    *_vector_rgb("u_ShadowColor2"),
)

_MATERIAL_COLOR_COORDINATES: tuple[FishSearchCoordinate, ...] = tuple(
    coordinate
    for name in (
        "u_Color",
        "u_ReflectColor",
        "u_ShadowColor1",
        "u_SpecularColor",
        "u_RimColor",
    )
    for coordinate in _vector_rgb(name)
)

_MATERIAL_OFFSET_COORDINATES: tuple[FishSearchCoordinate, ...] = (
    *_vector4("u_SpeOffet"),
    *_vector4("u_RimOffet"),
)

STRUCTURED_FISH_COORDINATES: tuple[FishSearchCoordinate, ...] = (
    *_SCENE_COORDINATES,
    *_MATERIAL_SCALAR_COORDINATES,
    *_MATERIAL_COLOR_COORDINATES,
    *_MATERIAL_OFFSET_COORDINATES,
)

STRUCTURED_FISH_MATERIAL_COORDINATES: tuple[FishSearchCoordinate, ...] = tuple(
    coordinate
    for coordinate in STRUCTURED_FISH_COORDINATES
    if coordinate.group in MATERIAL_GROUPS
)

STRUCTURED_FISH_SCENE_PARAM_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(coordinate.param_name for coordinate in _SCENE_COORDINATES)
)
STRUCTURED_FISH_MATERIAL_PARAM_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(coordinate.param_name for coordinate in STRUCTURED_FISH_MATERIAL_COORDINATES)
)
STRUCTURED_FISH_OPTIONAL_SECOND_LEVEL_PARAM_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        coordinate.param_name for coordinate in _OPTIONAL_SECOND_LEVEL_COORDINATES
    )
)
STRUCTURED_FISH_EXTENDED_MATERIAL_PARAM_NAMES: tuple[str, ...] = (
    *STRUCTURED_FISH_MATERIAL_PARAM_NAMES,
    *STRUCTURED_FISH_OPTIONAL_SECOND_LEVEL_PARAM_NAMES,
)
STRUCTURED_FISH_PARAM_NAMES: tuple[str, ...] = (
    *STRUCTURED_FISH_SCENE_PARAM_NAMES,
    *STRUCTURED_FISH_MATERIAL_PARAM_NAMES,
)


def structured_fish_search_param_names(
    params: dict[str, Any],
    shader_params: Sequence[ShaderParam] = (),
) -> list[str]:
    """Return active top-level params in deterministic stage order."""

    active_coordinates = structured_fish_coordinates(params, shader_params=shader_params)
    return list(dict.fromkeys(coordinate.param_name for coordinate in active_coordinates))


def structured_fish_coordinates(
    params: dict[str, Any],
    *,
    shader_params: Sequence[ShaderParam] = (),
    search_param_names: Sequence[str] | None = None,
    material_only: bool = False,
) -> list[FishSearchCoordinate]:
    """Return valid scalar coordinates for the current material state."""

    shader_by_name = {param.name: param for param in shader_params}
    shader_names = set(shader_by_name)
    requested = set(search_param_names) if search_param_names is not None else None
    base_source: Iterable[FishSearchCoordinate] = (
        STRUCTURED_FISH_MATERIAL_COORDINATES if material_only else STRUCTURED_FISH_COORDINATES
    )
    source = list(base_source)
    if requested is not None:
        source.extend(
            coordinate
            for coordinate in _OPTIONAL_SECOND_LEVEL_COORDINATES
            if coordinate.param_name in requested
        )
    result: list[FishSearchCoordinate] = []
    for coordinate in source:
        name = coordinate.param_name
        if requested is not None and name not in requested:
            continue
        if shader_names and name not in shader_names:
            continue
        value = params.get(name)
        if coordinate.component is None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
        else:
            if not isinstance(value, list) or coordinate.component >= len(value):
                continue
            component_value = value[coordinate.component]
            if isinstance(component_value, bool) or not isinstance(component_value, (int, float)):
                continue
        numeric_value = (
            float(value)
            if coordinate.component is None
            else float(value[coordinate.component])
        )
        low = coordinate.low
        high = coordinate.high
        shader_param = shader_by_name.get(name)
        if coordinate.component is None and shader_param is not None:
            if shader_param.range_min is not None:
                low = min(low, float(shader_param.range_min))
            if shader_param.range_max is not None:
                high = max(high, float(shader_param.range_max))
        low = min(low, numeric_value)
        high = max(high, numeric_value)
        result.append(
            coordinate
            if low == coordinate.low and high == coordinate.high
            else replace(coordinate, low=low, high=high)
        )
    return result


def structured_fish_space_manifest(
    params: dict[str, Any],
    *,
    shader_params: Sequence[ShaderParam] = (),
    search_param_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    coordinates = structured_fish_coordinates(
        params,
        shader_params=shader_params,
        search_param_names=search_param_names,
    )
    groups: dict[str, list[str]] = {name: [] for name in STRUCTURED_GROUP_ORDER}
    for coordinate in coordinates:
        groups.setdefault(coordinate.group, []).append(coordinate.coordinate_id)
    return {
        "profile": "structured_fish_v1",
        "coordinate_count": len(coordinates),
        "param_count": len(dict.fromkeys(coordinate.param_name for coordinate in coordinates)),
        "group_order": list(STRUCTURED_GROUP_ORDER),
        "groups": groups,
        "coordinates": [
            {
                "id": coordinate.coordinate_id,
                "param": coordinate.param_name,
                "component": coordinate.component,
                "group": coordinate.group,
                "bounds": [coordinate.low, coordinate.high],
                "initial_step": coordinate.initial_step,
                "min_step": coordinate.min_step,
            }
            for coordinate in coordinates
        ],
        "locked_contract": {
            "color_alpha": "preserved",
            "textures": "preserved",
            "texture_uv_st": "preserved",
            "alpha_cutoff": "preserved",
            "shader_defines": "preserved",
            "engine_render_state": "audited_not_continuously_optimized",
        },
    }


__all__ = [
    "FishSearchCoordinate",
    "MATERIAL_GROUPS",
    "SCENE_ALIGNMENT_GROUP",
    "STRUCTURED_FISH_COORDINATES",
    "STRUCTURED_FISH_MATERIAL_COORDINATES",
    "STRUCTURED_FISH_EXTENDED_MATERIAL_PARAM_NAMES",
    "STRUCTURED_FISH_MATERIAL_PARAM_NAMES",
    "STRUCTURED_FISH_OPTIONAL_SECOND_LEVEL_PARAM_NAMES",
    "STRUCTURED_FISH_PARAM_NAMES",
    "STRUCTURED_FISH_SCENE_PARAM_NAMES",
    "STRUCTURED_GROUP_ORDER",
    "structured_fish_coordinates",
    "structured_fish_search_param_names",
    "structured_fish_space_manifest",
]
