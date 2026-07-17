"""Legal discrete shader states for the canonical 1504 fish material."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from material_fit.laya import lmat_io


MANAGED_FISH_DEFINES = ("NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS")

FISH_DEFINE_VARIANTS: dict[str, tuple[str, ...]] = {
    "flat_hard_rim": (),
    "flat_smooth_rim": ("RIMSMOOTHNESS",),
    "normal_hard_rim": ("NORMALMAP",),
    "normal_smooth_rim": ("NORMALMAP", "RIMSMOOTHNESS"),
    "normal_y_invert_hard_rim": ("NORMALMAP", "NORMALMAP_Y_INVERT"),
    "normal_y_invert_smooth_rim": (
        "NORMALMAP",
        "NORMALMAP_Y_INVERT",
        "RIMSMOOTHNESS",
    ),
}


def define_patch_for_variant(name: str) -> dict[str, list[str]]:
    try:
        enabled = FISH_DEFINE_VARIANTS[str(name)]
    except KeyError as exc:
        raise ValueError(f"unknown fish define variant: {name!r}") from exc
    return {
        "managed": list(MANAGED_FISH_DEFINES),
        "enabled": list(enabled),
    }


def apply_variant_to_capture_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    capture = config.get("laya_capture")
    if not isinstance(capture, dict):
        raise ValueError("fit config has no laya_capture object")
    patch = capture.get("material_patch")
    if not isinstance(patch, dict):
        patch = {}
        capture["material_patch"] = patch
    patch["defines"] = define_patch_for_variant(name)
    return config


def material_with_variant(
    source_material: str | Path,
    params: Mapping[str, Any],
    variant: str,
) -> dict[str, Any]:
    material = lmat_io.load_lmat(source_material)
    material = lmat_io.apply_params(material, dict(params), allow_missing_keys=True)
    lmat_io.get_props(material)["defines"] = list(FISH_DEFINE_VARIANTS[variant])
    return material


def optimizer_input_boundary_report(config: Mapping[str, Any]) -> dict[str, Any]:
    forbidden_tokens = (
        "1504_body.lmat",
        "human_adjusted",
        "human_target",
        "teacher",
        "proposal_direction",
    )
    hits: list[dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        text = str(value).lower()
        for token in forbidden_tokens:
            if token in text:
                hits.append({"path": path, "token": token, "value": str(value)})

    walk(copy.deepcopy(dict(config)), "")
    return {
        "contract": "optimizer_sees_active_start_target_png_and_online_feedback_only",
        "passed": not hits,
        "forbidden_tokens": list(forbidden_tokens),
        "hits": hits,
    }
