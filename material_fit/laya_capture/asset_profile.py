"""Validated asset profiles for the persistent Laya runtime renderer."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_CAPTURE_SETTINGS: dict[str, Any] = {
    "animation_mode": "disabled",
    "freeze_animators": True,
    "settle_frames": 0,
    "animation_freeze_settle_frames": 0,
}

MATERIAL_RENDER_STATE_KEYS = (
    "renderQueue",
    "s_Cull",
    "s_Blend",
    "s_BlendSrc",
    "s_BlendDst",
    "s_BlendSrcRGB",
    "s_BlendDstRGB",
    "s_BlendSrcAlpha",
    "s_BlendDstAlpha",
    "s_BlendEquation",
    "s_BlendEquationRGB",
    "s_BlendEquationAlpha",
    "s_DepthTest",
    "s_DepthWrite",
)


def load_asset_profile(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path).expanduser().resolve()
    raw = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError(f"asset profile must be a JSON object: {profile_path}")
    if int(raw.get("schema_version", 1)) != 1:
        raise ValueError(f"unsupported asset profile schema_version: {raw.get('schema_version')}")

    profile = copy.deepcopy(raw)
    project_root = _resolve_path(profile.get("project_root"), base=profile_path.parent)
    if project_root is None or not project_root.is_dir():
        raise FileNotFoundError(f"asset profile project_root is unavailable: {project_root}")
    scene_path = _resolve_scene(profile.get("scene"), project_root=project_root, profile_dir=profile_path.parent)
    if scene_path is None or not scene_path.is_file():
        raise FileNotFoundError(f"asset profile scene is unavailable: {scene_path}")

    capture_defaults = dict(DEFAULT_CAPTURE_SETTINGS)
    raw_defaults = profile.get("capture_defaults")
    if isinstance(raw_defaults, dict):
        capture_defaults.update(copy.deepcopy(raw_defaults))
    animation_mode = str(capture_defaults.get("animation_mode") or "disabled")
    if animation_mode not in {"disabled", "fixed_pose", "legacy"}:
        raise ValueError(f"unsupported animation_mode: {animation_mode}")
    capture_defaults["animation_mode"] = animation_mode

    views = capture_defaults.get("views")
    if not isinstance(views, list) or not views:
        raise ValueError("asset profile capture_defaults.views must be a non-empty list")
    seen: set[str] = set()
    for index, raw_view in enumerate(views):
        if not isinstance(raw_view, dict):
            raise ValueError(f"capture view {index} must be an object")
        view_id = str(raw_view.get("view_id") or raw_view.get("id") or "")
        if not view_id or view_id in seen:
            raise ValueError(f"capture view {index} has an empty or duplicate view_id: {view_id!r}")
        seen.add(view_id)

    profile["_profile_path"] = str(profile_path)
    profile["_project_root"] = str(project_root)
    profile["_scene_path"] = str(scene_path)
    profile["capture_defaults"] = capture_defaults
    return profile


def capture_command_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    defaults = profile.get("capture_defaults")
    if not isinstance(defaults, dict):
        raise ValueError("loaded asset profile is missing capture_defaults")
    return copy.deepcopy(defaults)


def material_patch_from_lmat(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8-sig"))
    props = payload.get("props") if isinstance(payload, dict) else None
    if not isinstance(props, dict):
        raise ValueError(f"invalid .lmat props: {path}")
    values = {
        name: copy.deepcopy(value)
        for name, value in props.items()
        if not name.startswith("s_")
        and name not in {"textures", "type", "renderQueue", "materialRenderMode", "defines"}
        and (isinstance(value, (int, float, bool)) or _is_numeric_vector(value))
    }
    enabled_defines = [str(value) for value in props.get("defines", []) if str(value)]
    managed_defines = ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"]
    render_states = {
        name: copy.deepcopy(props[name])
        for name in MATERIAL_RENDER_STATE_KEYS
        if name in props and isinstance(props[name], (int, float, bool))
    }
    return {
        "values": values,
        "defines": {
            "managed": managed_defines,
            "enabled": [value for value in enabled_defines if value in managed_defines],
        },
        "render_states": render_states,
    }


def _resolve_path(value: Any, *, base: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _resolve_scene(value: Any, *, project_root: Path, profile_dir: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    project_candidate = (project_root / path).resolve()
    if project_candidate.exists():
        return project_candidate
    return (profile_dir / path).resolve()


def _is_numeric_vector(value: Any) -> bool:
    return isinstance(value, list) and 2 <= len(value) <= 4 and all(isinstance(item, (int, float)) for item in value)
