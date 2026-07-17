from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def foreground_mask(image: Any, *, white_threshold: float = 8.0) -> tuple[np.ndarray, str]:
    rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[:, :, 3]
    if int(alpha.max()) > int(alpha.min()):
        return alpha > 5, "alpha"
    rgb = rgba[:, :, :3].astype(np.int16)
    return np.abs(rgb - 255).max(axis=2) > white_threshold, "distance_from_white"


def score_alignment_pair(reference: Any, candidate: Any) -> dict[str, Any]:
    reference_mask, reference_mask_source = foreground_mask(reference)
    candidate_mask, candidate_mask_source = foreground_mask(candidate)
    if reference_mask.shape != candidate_mask.shape:
        return {
            "status": "invalid",
            "reason": f"shape mismatch: reference={reference_mask.shape} candidate={candidate_mask.shape}",
        }

    reference_bbox = _mask_features(reference_mask)
    candidate_bbox = _mask_features(candidate_mask)
    if reference_bbox is None or candidate_bbox is None:
        return {
            "status": "invalid",
            "reason": "empty foreground",
            "reference_mask_source": reference_mask_source,
            "candidate_mask_source": candidate_mask_source,
            "reference_bbox": reference_bbox,
            "candidate_bbox": candidate_bbox,
        }

    intersection = reference_mask & candidate_mask
    union = reference_mask | candidate_mask
    intersection_pixels = int(intersection.sum())
    union_pixels = int(union.sum())
    reference_pixels = int(reference_mask.sum())
    candidate_pixels = int(candidate_mask.sum())
    trusted_core = _binary_erode(intersection, iterations=2)

    height, width = reference_mask.shape
    centroid_dx = float(candidate_bbox["centroid_x"] - reference_bbox["centroid_x"])
    centroid_dy = float(candidate_bbox["centroid_y"] - reference_bbox["centroid_y"])
    bbox_center_dx = float(candidate_bbox["bbox_center_x"] - reference_bbox["bbox_center_x"])
    bbox_center_dy = float(candidate_bbox["bbox_center_y"] - reference_bbox["bbox_center_y"])
    center_error_px = math.hypot(bbox_center_dx, bbox_center_dy)
    center_error_norm = center_error_px / max(width, height)
    centroid_error_px = math.hypot(centroid_dx, centroid_dy)
    centroid_error_norm = centroid_error_px / max(width, height)
    width_ratio = candidate_bbox["width"] / max(reference_bbox["width"], 1)
    height_ratio = candidate_bbox["height"] / max(reference_bbox["height"], 1)
    bbox_scale_error = 0.5 * (abs(width_ratio - 1.0) + abs(height_ratio - 1.0))

    return {
        "status": "ok",
        "reference_mask_source": reference_mask_source,
        "candidate_mask_source": candidate_mask_source,
        "foreground_iou": intersection_pixels / max(union_pixels, 1),
        "foreground_dice": 2.0 * intersection_pixels / max(reference_pixels + candidate_pixels, 1),
        "foreground_overlap_coefficient": intersection_pixels / max(min(reference_pixels, candidate_pixels), 1),
        "reference_foreground_pixels": reference_pixels,
        "candidate_foreground_pixels": candidate_pixels,
        "intersection_pixels": intersection_pixels,
        "union_pixels": union_pixels,
        "trusted_core_pixels": int(trusted_core.sum()),
        "trusted_core_reference_coverage": int(trusted_core.sum()) / max(reference_pixels, 1),
        "trusted_core_candidate_coverage": int(trusted_core.sum()) / max(candidate_pixels, 1),
        "dynamic_or_unaligned_pixels": union_pixels - intersection_pixels,
        "dynamic_or_unaligned_ratio": (union_pixels - intersection_pixels) / max(union_pixels, 1),
        "centroid_dx": centroid_dx,
        "centroid_dy": centroid_dy,
        "bbox_center_dx": bbox_center_dx,
        "bbox_center_dy": bbox_center_dy,
        "bbox_center_error_px": center_error_px,
        "bbox_center_error_norm": center_error_norm,
        "centroid_error_px": centroid_error_px,
        "centroid_error_norm": centroid_error_norm,
        "bbox_width_ratio": width_ratio,
        "bbox_height_ratio": height_ratio,
        "bbox_scale_error": bbox_scale_error,
        "symmetric_edge_distance_px": _symmetric_edge_distance(reference_mask, candidate_mask),
        "reference_bbox": reference_bbox,
        "candidate_bbox": candidate_bbox,
    }


def score_eight_view_alignment(
    *,
    reference_dir: Path,
    candidate_dir: Path,
    views: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    from PIL import Image

    per_view: list[dict[str, Any]] = []
    for view in views:
        reference_path = reference_dir / str(view["file_name"])
        candidate_path = candidate_dir / str(view["file_name"])
        if not reference_path.exists() or not candidate_path.exists():
            return None
        with Image.open(reference_path) as reference, Image.open(candidate_path) as candidate:
            scored = score_alignment_pair(reference, candidate)
        per_view.append(
            {
                "view_id": str(view["view_id"]),
                "file_name": str(view["file_name"]),
                **scored,
            }
        )

    valid = [item for item in per_view if item.get("status") == "ok"]
    if not valid:
        return {
            "version": "cross_engine_alignment_v2",
            "status": "invalid",
            "candidate_dir": str(candidate_dir),
            "view_count": len(per_view),
            "views": per_view,
        }

    def values(name: str) -> list[float]:
        return [float(item[name]) for item in valid if isinstance(item.get(name), (int, float))]

    ious = values("foreground_iou")
    overlaps = values("foreground_overlap_coefficient")
    center_errors = values("bbox_center_error_norm")
    centroid_errors = values("centroid_error_norm")
    centroid_dx = [abs(value) for value in values("centroid_dx")]
    centroid_dy = [abs(value) for value in values("centroid_dy")]
    scale_errors = values("bbox_scale_error")
    trusted_core = values("trusted_core_pixels")
    edge_distances = values("symmetric_edge_distance_px")
    thresholds = {
        "view_count": 8,
        "min_foreground_overlap_coefficient": 0.80,
        "max_centroid_error_norm": 0.02,
        "max_bbox_scale_error": 0.15,
        "min_trusted_core_pixels": 1000,
    }
    checks = {
        "view_count": len(valid) == thresholds["view_count"],
        "foreground_overlap": min(overlaps) >= thresholds["min_foreground_overlap_coefficient"],
        "centroid": max(centroid_errors) <= thresholds["max_centroid_error_norm"],
        "bbox_scale": max(scale_errors) <= thresholds["max_bbox_scale_error"],
        "trusted_core": min(trusted_core) >= thresholds["min_trusted_core_pixels"],
    }
    return {
        "version": "cross_engine_alignment_v2",
        "status": "ok",
        "passed": all(checks.values()),
        "candidate_dir": str(candidate_dir),
        "view_count": len(per_view),
        "valid_view_count": len(valid),
        "mean_foreground_iou": float(np.mean(ious)),
        "min_foreground_iou": min(ious),
        "mean_foreground_overlap_coefficient": float(np.mean(overlaps)),
        "min_foreground_overlap_coefficient": min(overlaps),
        "max_bbox_center_error_norm": max(center_errors),
        "max_centroid_error_norm": max(centroid_errors),
        "max_abs_centroid_dx": max(centroid_dx),
        "max_abs_centroid_dy": max(centroid_dy),
        "max_bbox_scale_error": max(scale_errors),
        "min_trusted_core_pixels": int(min(trusted_core)),
        "mean_symmetric_edge_distance_px": float(np.mean(edge_distances)),
        "max_symmetric_edge_distance_px": max(edge_distances),
        "thresholds": thresholds,
        "checks": checks,
        "notes": [
            "Full silhouette metrics remain diagnostic and include animation-dependent fins and tail.",
            "Material scoring may use only the unregistered eroded intersection core; no translation, scale, flip, or warp is applied.",
        ],
        "views": per_view,
    }


def trusted_intersection_core(reference: Any, candidate: Any, *, erosion_iterations: int = 2) -> np.ndarray:
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    if reference_mask.shape != candidate_mask.shape:
        raise ValueError(f"shape mismatch: reference={reference_mask.shape} candidate={candidate_mask.shape}")
    return _binary_erode(reference_mask & candidate_mask, iterations=erosion_iterations)


def _mask_features(mask: np.ndarray) -> dict[str, Any] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "width": x1 - x0,
        "height": y1 - y0,
        "bbox_center_x": 0.5 * (x0 + x1),
        "bbox_center_y": 0.5 * (y0 + y1),
        "centroid_x": float(xs.mean()),
        "centroid_y": float(ys.mean()),
        "area": int(mask.sum()),
    }


def _binary_erode(mask: np.ndarray, *, iterations: int) -> np.ndarray:
    try:
        from scipy.ndimage import binary_erosion

        return binary_erosion(mask, iterations=max(0, iterations)) if iterations > 0 else mask.copy()
    except ImportError:
        result = mask.copy()
        for _ in range(max(0, iterations)):
            padded = np.pad(result, 1, mode="constant", constant_values=False)
            neighborhoods = [
                padded[dy : dy + result.shape[0], dx : dx + result.shape[1]]
                for dy in range(3)
                for dx in range(3)
            ]
            result = np.logical_and.reduce(neighborhoods)
        return result


def _symmetric_edge_distance(reference_mask: np.ndarray, candidate_mask: np.ndarray) -> float:
    reference_edge = reference_mask & ~_binary_erode(reference_mask, iterations=1)
    candidate_edge = candidate_mask & ~_binary_erode(candidate_mask, iterations=1)
    if not reference_edge.any() or not candidate_edge.any():
        return math.inf
    try:
        from scipy.ndimage import distance_transform_edt

        reference_distance = distance_transform_edt(~reference_edge)
        candidate_distance = distance_transform_edt(~candidate_edge)
        return 0.5 * (
            float(candidate_distance[reference_edge].mean())
            + float(reference_distance[candidate_edge].mean())
        )
    except ImportError:
        return math.nan
