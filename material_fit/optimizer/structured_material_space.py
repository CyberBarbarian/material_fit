"""Asset-neutral public names for the shared structured material space.

The implementation remains in ``structured_fish_space`` so historical run
configs and imports stay reproducible. New multi-asset code should import this
module instead.
"""

from __future__ import annotations

from .structured_fish_space import (
    FishSearchCoordinate as MaterialSearchCoordinate,
    MATERIAL_GROUPS,
    SCENE_ALIGNMENT_GROUP,
    STRUCTURED_FISH_COORDINATES as STRUCTURED_MATERIAL_COORDINATES,
    STRUCTURED_FISH_MATERIAL_COORDINATES as STRUCTURED_MATERIAL_ONLY_COORDINATES,
    STRUCTURED_FISH_EXTENDED_MATERIAL_PARAM_NAMES as STRUCTURED_EXTENDED_MATERIAL_PARAM_NAMES,
    STRUCTURED_FISH_MATERIAL_PARAM_NAMES as STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_FISH_OPTIONAL_SECOND_LEVEL_PARAM_NAMES as STRUCTURED_OPTIONAL_SECOND_LEVEL_PARAM_NAMES,
    STRUCTURED_FISH_PARAM_NAMES as STRUCTURED_MATERIAL_ALL_PARAM_NAMES,
    STRUCTURED_FISH_SCENE_PARAM_NAMES as STRUCTURED_SCENE_PARAM_NAMES,
    STRUCTURED_GROUP_ORDER,
    structured_fish_coordinates as structured_material_coordinates,
    structured_fish_search_param_names as structured_material_search_param_names,
    structured_fish_space_manifest as structured_material_space_manifest,
)


__all__ = [
    "MATERIAL_GROUPS",
    "MaterialSearchCoordinate",
    "SCENE_ALIGNMENT_GROUP",
    "STRUCTURED_GROUP_ORDER",
    "STRUCTURED_MATERIAL_ALL_PARAM_NAMES",
    "STRUCTURED_MATERIAL_COORDINATES",
    "STRUCTURED_EXTENDED_MATERIAL_PARAM_NAMES",
    "STRUCTURED_MATERIAL_ONLY_COORDINATES",
    "STRUCTURED_MATERIAL_PARAM_NAMES",
    "STRUCTURED_OPTIONAL_SECOND_LEVEL_PARAM_NAMES",
    "STRUCTURED_SCENE_PARAM_NAMES",
    "structured_material_coordinates",
    "structured_material_search_param_names",
    "structured_material_space_manifest",
]
