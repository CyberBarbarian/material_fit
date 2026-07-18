"""Tracked Unity reference sets used by the cross-engine Stage 2 gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


EXPECTED_YAWS = (0, 45, 90, 135, 180, 225, 270, 315)
ASSET_IDS = {
    "1503": "1503",
    "crocodile": "1503",
    "crocodile_1503": "1503",
    "1504": "1504",
    "fish": "1504",
    "fish_1504": "1504",
    "1506": "1506",
    "turtle": "1506",
    "turtle_1506": "1506",
}


@dataclass(frozen=True)
class Stage2UnityReferenceSet:
    asset_id: str
    root: Path
    metadata_path: Path
    metadata: dict[str, Any]
    views: tuple[dict[str, Any], ...]


def resolve_stage2_unity_references(repo_root: Path, asset_id: str) -> Stage2UnityReferenceSet:
    normalized = ASSET_IDS.get(str(asset_id).strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported Stage 2 Unity reference asset: {asset_id}")
    root = (repo_root / "examples" / "stage2_unity_refs" / normalized).resolve()
    metadata_path = root / "unity_ref_multiview_metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing Stage 2 Unity metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    raw_views = metadata.get("views")
    if not isinstance(raw_views, list):
        raise ValueError(f"Unity metadata has no views: {metadata_path}")
    views: list[dict[str, Any]] = []
    for raw in sorted(raw_views, key=lambda item: int(item.get("index", -1))):
        index = int(raw.get("index", -1))
        yaw = int(round(float(raw.get("yaw", 0))))
        pitch = int(round(float(raw.get("pitch", 0))))
        views.append(
            {
                "index": index,
                "view_id": f"v{index:03d}_yaw{yaw}_pitch{pitch}",
                "yaw": float(yaw),
                "pitch": float(pitch),
                "reference_file_name": str(raw.get("fileName") or ""),
                "candidate_file_name": f"laya_v{index:03d}_yaw{yaw}_pitch{pitch}.png",
                "capture_yaw": float(raw.get("captureYaw", yaw)),
            }
        )
    return Stage2UnityReferenceSet(
        asset_id=normalized,
        root=root,
        metadata_path=metadata_path,
        metadata=metadata,
        views=tuple(views),
    )


def audit_stage2_unity_references(reference_set: Stage2UnityReferenceSet) -> dict[str, Any]:
    metadata = reference_set.metadata
    expected_size = (int(metadata.get("imageWidth", 0)), int(metadata.get("imageHeight", 0)))
    view_reports: list[dict[str, Any]] = []
    structural_errors: list[str] = []
    clipped_view_ids: list[str] = []
    for expected_index, view in enumerate(reference_set.views):
        if view["index"] != expected_index:
            structural_errors.append(f"view index {view['index']} != {expected_index}")
        if view["yaw"] != float(EXPECTED_YAWS[expected_index]) or view["pitch"] != 0.0:
            structural_errors.append(f"unexpected angle for {view['view_id']}")
        path = reference_set.root / view["reference_file_name"]
        if not path.is_file():
            structural_errors.append(f"missing image: {path.name}")
            continue
        with Image.open(path) as source:
            rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8)
            size = source.size
            alpha = rgba[:, :, 3]
        ys, xs = np.nonzero(alpha > 5)
        bbox = None
        touches_canvas = False
        if len(xs) == 0:
            structural_errors.append(f"empty alpha foreground: {path.name}")
        else:
            bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
            touches_canvas = bbox[0] == 0 or bbox[1] == 0 or bbox[2] == size[0] or bbox[3] == size[1]
            if touches_canvas:
                clipped_view_ids.append(view["view_id"])
        if size != expected_size:
            structural_errors.append(f"size mismatch for {path.name}: {size} != {expected_size}")
        partial_alpha_pixels = int(((alpha > 0) & (alpha < 255)).sum())
        view_reports.append(
            {
                **view,
                "path": str(path),
                "sha256": _sha256(path),
                "size": list(size),
                "alpha_bbox": bbox,
                "foreground_pixels": int((alpha > 5).sum()),
                "partial_alpha_pixels": partial_alpha_pixels,
                "touches_canvas": touches_canvas,
            }
        )
    geometry = metadata.get("modelGeometry") if isinstance(metadata.get("modelGeometry"), dict) else {}
    pivot_offset = geometry.get("pivotToBoundsCenter") if isinstance(geometry, dict) else None
    return {
        "contract": "material_fit_stage2_unity_reference_intake_v1",
        "asset_id": reference_set.asset_id,
        "passed": len(structural_errors) == 0 and len(view_reports) == 8,
        "geometry_ready": len(structural_errors) == 0 and len(view_reports) == 8 and not clipped_view_ids,
        "reference_root": str(reference_set.root),
        "metadata_path": str(reference_set.metadata_path),
        "metadata_sha256": _sha256(reference_set.metadata_path),
        "exporter_version": metadata.get("exporterVersion"),
        "unity_version": metadata.get("unityVersion"),
        "target_asset_path": metadata.get("targetAssetPath"),
        "image_size": list(expected_size),
        "capture_mode": metadata.get("captureMode"),
        "use_orthographic": metadata.get("useOrthographic"),
        "orthographic_size": metadata.get("orthographicSize"),
        "transparent_background": metadata.get("transparentBackground"),
        "silhouette_mask_alpha": metadata.get("useSilhouetteMaskAlpha"),
        "pivot_to_bounds_center": pivot_offset,
        "clipped_view_ids": clipped_view_ids,
        "structural_errors": structural_errors,
        "views": view_reports,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "EXPECTED_YAWS",
    "Stage2UnityReferenceSet",
    "audit_stage2_unity_references",
    "resolve_stage2_unity_references",
]
