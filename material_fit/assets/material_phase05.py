"""Asset adapters for the shared Phase 0.5 material-recovery experiment."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from material_fit.assets.fish_scene import resolve_fish_scene_assets
from material_fit.assets.laya_scene_bounds import (
    perspective_camera_distance,
    target_bounds_from_lh,
)


EIGHT_VIEWS = [
    {
        "view_id": f"v{index:03d}_yaw{yaw}_pitch0",
        "yaw": float(yaw),
        "pitch": 0.0,
        "file_name": f"laya_v{index:03d}_yaw{yaw}_pitch0.png",
    }
    for index, yaw in enumerate(range(0, 360, 45))
]
CANONICAL_YAW_OFFSET = 0.0
CANONICAL_PITCH_OFFSET = 0.0


TURTLE_ROOT = Path("examples/turtle_laya_project")
TURTLE_PROFILE = Path("material_fit/assets/profiles/turtle_1506.json")
TURTLE_MATERIAL = Path(
    "assets/resources/model/1506/mat/1506_test.lmat"
)
TURTLE_SHADER = Path(
    "assets/resources/shader/Custom_low.shader"
)
CROCODILE_ROOT = Path("examples/crocodile_laya_project")
CROCODILE_PROFILE = Path("material_fit/assets/profiles/crocodile_1503.json")
CROCODILE_MATERIAL = Path(
    "assets/1503/mat/1503_test.lmat"
)
CROCODILE_SHADER = Path(
    "assets/resources/shader/Custom_low.shader"
)


@dataclass(frozen=True)
class MaterialAssetSpec:
    asset_id: str
    project_root: Path
    scene_path: Path
    shader_path: Path
    target_material_path: Path
    profile: dict[str, Any]

    def manifest(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = copy.deepcopy(self.profile)
        for key in ("project_root", "scene_path", "shader_path", "target_material_path"):
            payload[key] = str(payload[key])
        return payload

    def write_profile(self, path: Path) -> Path:
        payload = copy.deepcopy(self.profile)
        payload["project_root"] = str(self.project_root)
        payload["scene"] = str(self.scene_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def resolve_material_asset(
    repo_root: Path,
    asset_id: str,
    *,
    profile_path: str | Path | None = None,
    target_material_path: str | Path | None = None,
    shader_path: str | Path | None = None,
) -> MaterialAssetSpec:
    """Resolve one renderer-only asset description without optimizer policy."""

    normalized = str(asset_id).strip().lower()
    if normalized in {"fish", "fish_1504", "1504"}:
        spec = _resolve_fish(repo_root)
    elif normalized in {"turtle", "turtle_1506", "1506"}:
        spec = _resolve_turtle(repo_root)
    elif normalized in {"crocodile", "crocodile_1503", "1503"}:
        spec = _resolve_crocodile(repo_root)
    else:
        raise ValueError(f"unsupported material asset: {asset_id}")
    return _with_overrides(
        spec,
        profile_path=profile_path,
        target_material_path=target_material_path,
        shader_path=shader_path,
    )


def _resolve_fish(repo_root: Path) -> MaterialAssetSpec:
    assets = resolve_fish_scene_assets(repo_root)
    profile = {
        "schema_version": 1,
        "asset_id": "fish_1504",
        "reference_contract_id": assets.reference_contract_id,
        "project_root": str(assets.source_laya_project_dir),
        "scene": str(assets.source_scene_path),
        "width": 900,
        "height": 700,
        "runtime": {
            "target_name": "model",
            "startup_settle_frames": 1,
        },
        "capture_defaults": {
            "target_name": "model",
            "camera_name": "Capture Camera",
            "capture_mode": "rotate_target",
            "use_orthographic": True,
            "orthographic_vertical_size": 8.0,
            "distance_scale": 2.2,
            "min_distance": 1.0,
            "yaw_offset": 0.0,
            "pitch_offset": 0.0,
            "target_yaw_sign": -1.0,
            "target_pitch_sign": -1.0,
            "animation_mode": "disabled",
            "freeze_animators": True,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "transparent_background": True,
            "preserve_artifact_alpha": False,
            "visual_background_color": [255, 255, 255, 255],
            "views": copy.deepcopy(EIGHT_VIEWS),
        },
        "validation_variants": [],
    }
    return MaterialAssetSpec(
        asset_id="fish_1504",
        project_root=assets.source_laya_project_dir,
        scene_path=assets.source_scene_path,
        shader_path=assets.shader_path,
        target_material_path=assets.baseline_material_path,
        profile=profile,
    )


def _resolve_turtle(repo_root: Path) -> MaterialAssetSpec:
    root = (repo_root / TURTLE_ROOT).resolve()
    profile_path = (repo_root / TURTLE_PROFILE).resolve()
    if not profile_path.is_file():
        raise FileNotFoundError(
            "missing maintained turtle renderer payload: "
            f"{profile_path}. Restore the validated 1506 asset bundle or pass --asset-profile."
        )
    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    project_root = root
    scene_path = _scene_path(profile.get("scene"), project_root, profile_path.parent)
    return MaterialAssetSpec(
        asset_id="turtle_1506",
        project_root=project_root,
        scene_path=scene_path,
        shader_path=(root / TURTLE_SHADER).resolve(),
        target_material_path=(root / TURTLE_MATERIAL).resolve(),
        profile=profile,
    )


def canonicalize_axis_aligned_eight_view_profile(profile: dict[str, Any]) -> None:
    """Apply the shared optimizer-facing, axis-aligned eight-view contract."""

    capture_defaults = profile.setdefault("capture_defaults", {})
    capture_defaults["yaw_offset"] = CANONICAL_YAW_OFFSET
    capture_defaults["pitch_offset"] = CANONICAL_PITCH_OFFSET
    capture_defaults["camera_height_factor"] = 0.0
    capture_defaults["views"] = copy.deepcopy(EIGHT_VIEWS)
    capture_defaults["freeze_animators"] = True
    capture_defaults["settle_frames"] = 0
    capture_defaults["animation_freeze_settle_frames"] = 0
    capture_defaults["animation_mode"] = "disabled"
    for key in (
        "fixed_animation_state",
        "fixed_animation_layer",
        "fixed_animation_time",
        "restore_animators_after_capture",
    ):
        capture_defaults.pop(key, None)

    runtime = profile.get("runtime")
    if isinstance(runtime, dict):
        camera = runtime.get("camera")
        if isinstance(camera, dict):
            camera["yaw"] = CANONICAL_YAW_OFFSET
            camera["pitch"] = CANONICAL_PITCH_OFFSET
            camera["height_offset"] = 0.0


def _resolve_crocodile(repo_root: Path) -> MaterialAssetSpec:
    root = (repo_root / CROCODILE_ROOT).resolve()
    profile_path = (repo_root / CROCODILE_PROFILE).resolve()
    if not profile_path.is_file():
        raise FileNotFoundError(
            "missing maintained 1503 crocodile renderer payload: "
            f"{profile_path}. Restore the local 1503 validation bundle."
        )
    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    project_root = root
    scene_path = _scene_path(profile.get("scene"), project_root, profile_path.parent)
    return MaterialAssetSpec(
        asset_id="crocodile_1503",
        project_root=project_root,
        scene_path=scene_path,
        shader_path=(root / CROCODILE_SHADER).resolve(),
        target_material_path=(root / CROCODILE_MATERIAL).resolve(),
        profile=profile,
    )


def _with_overrides(
    spec: MaterialAssetSpec,
    *,
    profile_path: str | Path | None,
    target_material_path: str | Path | None,
    shader_path: str | Path | None,
) -> MaterialAssetSpec:
    profile = copy.deepcopy(spec.profile)
    project_root = spec.project_root
    scene_path = spec.scene_path
    if profile_path:
        source = Path(profile_path).expanduser().resolve()
        profile = json.loads(source.read_text(encoding="utf-8-sig"))
        project_root = _profile_path(profile.get("project_root"), source.parent)
        scene_path = _scene_path(profile.get("scene"), project_root, source.parent)
    canonicalize_axis_aligned_eight_view_profile(profile)
    _apply_geometry_framing(profile, scene_path)
    result = MaterialAssetSpec(
        asset_id=spec.asset_id,
        project_root=project_root,
        scene_path=scene_path,
        shader_path=(Path(shader_path).expanduser().resolve() if shader_path else spec.shader_path),
        target_material_path=(
            Path(target_material_path).expanduser().resolve()
            if target_material_path
            else spec.target_material_path
        ),
        profile=profile,
    )
    missing = [
        str(path)
        for path in (
            result.project_root,
            result.scene_path,
            result.shader_path,
            result.target_material_path,
        )
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("material asset is incomplete:\n" + "\n".join(missing))
    return result


def _apply_geometry_framing(profile: dict[str, Any], scene_path: Path) -> None:
    capture_defaults = profile["capture_defaults"]
    if capture_defaults.get("capture_mode") != "orbit_camera":
        return
    target_name = str(capture_defaults.get("target_name") or "model")
    bounds = target_bounds_from_lh(scene_path, target_name)
    runtime = profile.setdefault("runtime", {})
    camera = runtime.setdefault("camera", {})
    distance = perspective_camera_distance(
        bounds,
        width=int(profile.get("width") or 800),
        height=int(profile.get("height") or 600),
        vertical_field_of_view=float(camera.get("field_of_view") or 60.0),
    )
    center = [float(value) for value in bounds.center]
    capture_defaults["camera_center"] = center
    capture_defaults["camera_distance"] = distance
    camera["center"] = center
    camera["distance"] = distance


def _profile_path(value: Any, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _scene_path(value: Any, project_root: Path, profile_dir: Path) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidate = (project_root / path).resolve()
    return candidate if candidate.exists() else (profile_dir / path).resolve()


__all__ = [
    "MaterialAssetSpec",
    "canonicalize_axis_aligned_eight_view_profile",
    "resolve_material_asset",
]
