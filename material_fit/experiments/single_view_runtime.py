"""Small persistent-renderer surface shared by the three single-view stages."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from material_fit.laya.render_driver import RenderDriver
from material_fit.vision.dists_score import (
    DEFAULT_DISTS_IMAGE_SIZE,
    DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE,
    DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES,
    DEFAULT_DISTS_TORCH_THREADS,
    DISTS_ALIGNED_RGB_METRIC,
)


DEFAULT_SINGLE_VIEW_ID = "v000_yaw0_pitch0"
DEFAULT_SINGLE_VIEW_SCORE_WIDTH = 450
DEFAULT_SINGLE_VIEW_SCORE_HEIGHT = 350
DEFAULT_SINGLE_VIEW = {
    "view_id": DEFAULT_SINGLE_VIEW_ID,
    "yaw": 0.0,
    "pitch": 0.0,
    "file_name": "laya_v000_yaw0_pitch0.png",
}


def write_single_view_profile(
    profile: Mapping[str, Any],
    path: Path,
    *,
    project_root: Path,
    scene_path: Path,
    width: int,
    height: int,
    view: Mapping[str, Any] | None = None,
) -> Path:
    payload = single_view_profile_payload(
        profile,
        project_root=project_root,
        scene_path=scene_path,
        width=width,
        height=height,
        view=view,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def single_view_profile_payload(
    profile: Mapping[str, Any],
    *,
    project_root: Path,
    scene_path: Path,
    width: int,
    height: int,
    view: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(profile))
    payload["project_root"] = str(project_root.resolve())
    payload["scene"] = str(scene_path.resolve())
    payload["width"] = int(width)
    payload["height"] = int(height)
    defaults = payload.setdefault("capture_defaults", {})
    defaults.update(
        {
            "yaw_offset": 0.0,
            "pitch_offset": 0.0,
            "camera_height_factor": 0.0,
            "animation_mode": "disabled",
            "freeze_animators": True,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "restore_animators_after_capture": False,
            "transparent_background": True,
            "preserve_artifact_alpha": False,
            "visual_background_color": [255, 255, 255, 255],
            "views": [copy.deepcopy(dict(view or DEFAULT_SINGLE_VIEW))],
        }
    )
    for key in ("fixed_animation_state", "fixed_animation_layer", "fixed_animation_time"):
        defaults.pop(key, None)
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        runtime["background_color"] = [255, 255, 255, 255]
        camera = runtime.get("camera")
        if isinstance(camera, dict):
            camera["yaw"] = 0.0
            camera["pitch"] = 0.0
            camera["height_offset"] = 0.0
    return payload


def build_single_view_driver(
    *,
    profile_path: Path,
    output_root: Path,
    material_patch: Mapping[str, Any],
    node_modules: Path,
    reference_path: Path | None,
    return_images: bool,
    emit_residual_features: bool = True,
    perceptual_device: str = "auto",
    perceptual_image_size: int = DEFAULT_DISTS_IMAGE_SIZE,
    perceptual_metric: str = DISTS_ALIGNED_RGB_METRIC,
    browser_score_overrides: Mapping[str, Any] | None = None,
) -> RenderDriver:
    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    defaults = profile.get("capture_defaults")
    views = defaults.get("views") if isinstance(defaults, dict) else None
    if not isinstance(views, list) or len(views) != 1 or not isinstance(views[0], dict):
        raise ValueError("single-view profile must contain exactly one capture view")
    view = views[0]
    browser_score: dict[str, Any] = {"enabled": False}
    if reference_path is not None:
        browser_score = {
            "enabled": True,
            "metric": str(perceptual_metric),
            "emit_artifacts": "always" if return_images else "never",
            "perceptual_image_size": int(perceptual_image_size),
            "perceptual_device": str(perceptual_device),
            "perceptual_torch_threads": DEFAULT_DISTS_TORCH_THREADS,
            "perceptual_emit_residual_features": bool(emit_residual_features),
            "perceptual_residual_sketch_size": DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE,
            "perceptual_residual_sketch_tables": DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES,
            "reference_images": [
                {
                    "view_id": str(view.get("view_id") or DEFAULT_SINGLE_VIEW_ID),
                    "path": str(reference_path.resolve()),
                }
            ],
        }
        if browser_score_overrides:
            browser_score.update(copy.deepcopy(dict(browser_score_overrides)))
    patch = copy.deepcopy(dict(material_patch))
    patch["target_name"] = str(patch.get("target_name") or defaults.get("target_name") or "model")
    return RenderDriver(
        output_dir=output_root,
        dry_run=False,
        capture_config={
            "runtime_bridge": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 0,
                "asset_profile": str(profile_path.resolve()),
                "state_dir": str((output_root / "runtime_renderer").resolve()),
                "timeout_s": 90,
                "startup_timeout_s": 90,
                "output_subdir": "render",
                "auto_start_renderer": True,
                "node_modules": str(node_modules.resolve()),
            },
            "browser_score": browser_score,
            "material_patch": patch,
            "return_images": bool(return_images),
            "persist_browser_score": False,
            "preserve_artifact_alpha": False,
            "settle_frames": 0,
            "animation_freeze_settle_frames": 0,
            "restore_animators_after_capture": False,
            "visual_quality_guard": {"enabled": False},
        },
    )


def render_score(
    driver: RenderDriver,
    *,
    evaluation_index: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    result = driver.render_candidate(int(evaluation_index), params)
    if result.get("status") != "ok":
        raise RuntimeError(f"single-view renderer failed: {result}")
    score = result.get("browser_score")
    if not isinstance(score, dict):
        persistent = result.get("persistent_result")
        score = persistent.get("browser_score") if isinstance(persistent, dict) else None
    if not isinstance(score, dict):
        raise RuntimeError(f"single-view renderer returned no browser score: {result}")
    view_score = _single_view_score(score)
    distance = _score_distance(score)
    if not isinstance(distance, (int, float)) and view_score is not None:
        distance = _score_distance(view_score)
    fit_score = score.get("fit_score", score.get("score"))
    if not isinstance(distance, (int, float)):
        diff_score = score.get("diff_score")
        if not isinstance(diff_score, (int, float)) and view_score is not None:
            diff_score = view_score.get("diff_score")
        if isinstance(diff_score, (int, float)):
            distance = float(diff_score)
        elif isinstance(fit_score, (int, float)):
            distance = 1.0 - float(fit_score)
    if not isinstance(distance, (int, float)) or not isinstance(fit_score, (int, float)):
        raise RuntimeError(f"single-view perceptual payload is incomplete: {score}")
    structured = score.get("structured_residual_features")
    residual_features = (
        list(structured.get("features", []))
        if isinstance(structured, dict)
        else []
    )
    if not residual_features:
        residual_features = _view_residual_features(score)
    return {
        "distance": float(distance),
        "fit_score": float(fit_score),
        "residual_features": residual_features,
        "browser_score": score,
    }


def capture_png(
    driver: RenderDriver,
    *,
    evaluation_index: int,
    params: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    result = driver.render_candidate(int(evaluation_index), params)
    if result.get("status") != "ok":
        raise RuntimeError(f"single-view artifact capture failed: {result}")
    screenshots = [Path(str(value)) for value in result.get("screenshots", [])]
    if len(screenshots) != 1 or not screenshots[0].is_file():
        raise RuntimeError(f"single-view artifact capture returned {len(screenshots)} PNG files")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(screenshots[0], output_path)
    return result


def _view_residual_features(score: Mapping[str, Any]) -> list[float]:
    view = _single_view_score(score)
    if view is None:
        return []
    values = view.get("residual_features")
    if not isinstance(values, list):
        return []
    return [float(value) for value in values]


def _score_distance(score: Mapping[str, Any]) -> float | None:
    for key in ("distance", "perceptual_distance", "dists_distance"):
        value = score.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _single_view_score(score: Mapping[str, Any]) -> Mapping[str, Any] | None:
    views = score.get("views")
    if not isinstance(views, list) or len(views) != 1 or not isinstance(views[0], Mapping):
        return None
    return views[0]


__all__ = [
    "DEFAULT_SINGLE_VIEW",
    "DEFAULT_SINGLE_VIEW_ID",
    "DEFAULT_SINGLE_VIEW_SCORE_HEIGHT",
    "DEFAULT_SINGLE_VIEW_SCORE_WIDTH",
    "build_single_view_driver",
    "capture_png",
    "render_score",
    "single_view_profile_payload",
    "write_single_view_profile",
]
