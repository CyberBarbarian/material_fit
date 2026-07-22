"""Frozen asset-side sampling profiles for Unity-to-Laya Stage 2."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from material_fit.assets.material_stage1 import (
    MaterialStage1AssetSpec,
    resolve_material_stage1_asset,
)
from material_fit.assets.stage2_unity_references import (
    Stage2UnityReferenceSet,
    audit_stage2_unity_references,
    resolve_stage2_unity_references,
)


@dataclass(frozen=True)
class Stage2SamplingSpec:
    asset: MaterialStage1AssetSpec
    references: Stage2UnityReferenceSet
    calibration_path: Path
    calibration: dict[str, Any]
    material_path: Path
    material_variant: str
    lighting_variant: str
    additional_material_defines: tuple[str, ...]
    profile: dict[str, Any]

    def manifest(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset.asset_id,
            "reference_asset_id": self.references.asset_id,
            "reference_root": str(self.references.root),
            "reference_metadata_path": str(self.references.metadata_path),
            "calibration_path": str(self.calibration_path),
            "calibration": copy.deepcopy(self.calibration),
            "material_path": str(self.material_path),
            "material_variant": self.material_variant,
            "lighting_variant": self.lighting_variant,
            "additional_material_defines": list(self.additional_material_defines),
            "profile": copy.deepcopy(self.profile),
        }


def resolve_stage2_sampling(
    repo_root: Path,
    asset_id: str,
    *,
    material_variant: str = "start",
    lighting_variant: str = "baseline",
) -> Stage2SamplingSpec:
    """Resolve one frozen geometry profile without exposing target material params."""

    root = repo_root.resolve()
    asset = resolve_material_stage1_asset(root, asset_id)
    references = resolve_stage2_unity_references(root, asset_id)
    reference_audit = audit_stage2_unity_references(references)
    if not reference_audit["geometry_ready"]:
        raise ValueError(
            f"Stage 2 references for {references.asset_id} are not geometry-ready: "
            f"clipped views={reference_audit['clipped_view_ids']}"
        )

    calibration_path = (
        root / "material_fit" / "assets" / "stage2_sampling" / f"{references.asset_id}.json"
    ).resolve()
    if not calibration_path.is_file():
        raise FileNotFoundError(
            f"no frozen Stage 2 sampling calibration for {references.asset_id}: {calibration_path}"
        )
    calibration = json.loads(calibration_path.read_text(encoding="utf-8-sig"))
    _validate_calibration(calibration, asset, references)

    variant = str(material_variant).strip().lower()
    if variant == "start":
        material_path = asset.start_material_path
    elif variant in {"human", "human-adjusted", "human_adjusted"}:
        variant = "human-adjusted"
        material_path = asset.target_material_path
    else:
        raise ValueError(f"unsupported Stage 2 material variant: {material_variant}")

    profile = _build_capture_profile(asset, references, calibration)
    resolved_lighting, additional_defines = _apply_lighting_variant(
        profile,
        calibration,
        lighting_variant,
    )
    return Stage2SamplingSpec(
        asset=asset,
        references=references,
        calibration_path=calibration_path,
        calibration=calibration,
        material_path=material_path,
        material_variant=variant,
        lighting_variant=resolved_lighting,
        additional_material_defines=additional_defines,
        profile=profile,
    )


def _apply_lighting_variant(
    profile: dict[str, Any],
    calibration: dict[str, Any],
    lighting_variant: str,
) -> tuple[str, tuple[str, ...]]:
    variant = str(lighting_variant).strip().lower()
    if variant == "baseline":
        return variant, ()

    presets = calibration.get("lighting_presets")
    preset = presets.get(variant) if isinstance(presets, dict) else None
    if not isinstance(preset, dict):
        available = sorted(str(name) for name in presets) if isinstance(presets, dict) else []
        raise ValueError(
            f"unsupported Stage 2 lighting variant {lighting_variant!r}; "
            f"available: {['baseline', *available]}"
        )
    if preset.get("frozen_during_material_search") is not True:
        raise ValueError(f"Stage 2 lighting preset {variant!r} must be frozen during material search")
    runtime_patch = preset.get("runtime")
    if not isinstance(runtime_patch, dict):
        raise ValueError(f"Stage 2 lighting preset {variant!r} requires a runtime object")
    profile.setdefault("runtime", {}).update(copy.deepcopy(runtime_patch))
    raw_defines = preset.get("material_defines", [])
    if not isinstance(raw_defines, list) or not all(isinstance(name, str) for name in raw_defines):
        raise ValueError(f"Stage 2 lighting preset {variant!r} has invalid material_defines")
    return variant, tuple(raw_defines)


def _build_capture_profile(
    asset: MaterialStage1AssetSpec,
    references: Stage2UnityReferenceSet,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    profile = copy.deepcopy(asset.profile)
    profile["project_root"] = str(asset.project_root)
    profile["scene"] = str(asset.scene_path)
    profile["width"] = int(references.metadata["imageWidth"])
    profile["height"] = int(references.metadata["imageHeight"])

    center = [float(value) for value in calibration["camera_center"]]
    runtime = profile.setdefault("runtime", {})
    runtime["background_color"] = [255, 255, 255, 255]
    camera = runtime.setdefault("camera", {})
    camera.update(
        {
            "orthographic": False,
            "field_of_view": float(calibration["field_of_view"]),
            "distance": float(calibration["camera_distance"]),
            "center": center,
            "yaw": float(calibration["yaw_offset"]),
            "pitch": float(calibration["pitch_offset"]),
            "height_offset": 0.0,
        }
    )

    capture = profile.setdefault("capture_defaults", {})
    capture.update(
        {
            "capture_mode": str(calibration["capture_mode"]),
            "preserve_target_transform": True,
            "camera_center": center,
            "camera_distance": float(calibration["camera_distance"]),
            "fov": float(calibration["field_of_view"]),
            "yaw_offset": float(calibration["yaw_offset"]),
            "pitch_offset": float(calibration["pitch_offset"]),
            "camera_height_factor": float(calibration["camera_height_factor"]),
            "animation_mode": "disabled",
            "freeze_animators": True,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "visual_background_color": [255, 255, 255, 255],
            "views": [
                {
                    "view_id": view["view_id"],
                    "yaw": view["yaw"],
                    "pitch": view["pitch"],
                    "file_name": view["candidate_file_name"],
                }
                for view in references.views
            ],
        }
    )
    capture.pop("orthographic_vertical_size", None)
    return profile


def _validate_calibration(
    calibration: dict[str, Any],
    asset: MaterialStage1AssetSpec,
    references: Stage2UnityReferenceSet,
) -> None:
    if calibration.get("contract") != "material_fit_stage2_frozen_sampling_v2":
        raise ValueError("unsupported Stage 2 sampling calibration contract")
    if str(calibration.get("reference_asset_id")) != references.asset_id:
        raise ValueError("Stage 2 sampling calibration references the wrong asset")
    if str(calibration.get("asset_id")) != asset.asset_id:
        raise ValueError("Stage 2 sampling calibration references the wrong Laya asset")
    if calibration.get("capture_mode") != "orbit_camera":
        raise ValueError("Stage 2 sampling calibration must use orbit_camera")
    if calibration.get("projection") != "perspective":
        raise ValueError("Stage 2 sampling calibration must preserve perspective projection")
    expected_hash = str(calibration.get("reference_metadata_sha256") or "").lower()
    actual_hash = _sha256(references.metadata_path)
    if expected_hash != actual_hash:
        raise ValueError(
            "Stage 2 Unity metadata changed after sampling calibration: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    center = calibration.get("camera_center")
    if not isinstance(center, list) or len(center) != 3:
        raise ValueError("Stage 2 sampling calibration requires a three-value camera_center")
    if float(calibration.get("field_of_view", 0.0)) <= 0.0:
        raise ValueError("Stage 2 sampling calibration requires a positive field of view")
    if float(calibration.get("camera_distance", 0.0)) <= 0.0:
        raise ValueError("Stage 2 sampling calibration requires a positive camera distance")
    registration = calibration.get("registration")
    if not isinstance(registration, dict) or registration.get("mode") != "frozen_per_view_similarity":
        raise ValueError("Stage 2 sampling calibration requires frozen per-view registration")
    transforms = registration.get("transforms")
    if not isinstance(transforms, list) or len(transforms) != len(references.views):
        raise ValueError("Stage 2 sampling calibration must cover all reference views")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["Stage2SamplingSpec", "resolve_stage2_sampling"]
