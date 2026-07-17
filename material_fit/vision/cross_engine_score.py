from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np

from material_fit.vision.cross_engine_alignment import (
    foreground_mask,
    score_alignment_pair,
    trusted_intersection_core,
)


COMPONENT_WEIGHTS = {
    "foreground_rgb": 0.40,
    "color_distribution": 0.22,
    "luminance_structure": 0.16,
    "detail_texture": 0.12,
    "highlight_emission": 0.10,
}

COMPONENT_WEIGHTS_V3 = {
    "foreground_rgb": 0.30,
    "color_distribution": 0.15,
    "chroma_hue": 0.25,
    "luminance_structure": 0.12,
    "detail_texture": 0.08,
    "highlight_emission": 0.10,
}


def score_cross_engine_pair(reference: Any, candidate: Any) -> dict[str, Any]:
    reference_rgba = np.asarray(reference.convert("RGBA"), dtype=np.float32) / 255.0
    candidate_rgba = np.asarray(candidate.convert("RGBA"), dtype=np.float32) / 255.0
    if reference_rgba.shape != candidate_rgba.shape:
        return {
            "version": "cross_engine_material_score_v2",
            "status": "invalid",
            "reason": f"shape mismatch: reference={reference_rgba.shape} candidate={candidate_rgba.shape}",
        }

    alignment = score_alignment_pair(reference, candidate)
    if alignment.get("status") != "ok":
        return {
            "version": "cross_engine_material_score_v2",
            "status": "invalid",
            "alignment": alignment,
            "score": None,
        }
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    core = trusted_intersection_core(reference, candidate, erosion_iterations=2)
    minimum_foreground_pixels = min(
        int(reference_mask.sum()),
        int(candidate_mask.sum()),
    )
    minimum_core_pixels = max(
        256,
        int(0.02 * minimum_foreground_pixels),
    )
    if int(core.sum()) < minimum_core_pixels or float(alignment["foreground_overlap_coefficient"]) < 0.75:
        return {
            "version": "cross_engine_material_score_v2",
            "status": "invalid_alignment",
            "alignment": alignment,
            "score": None,
            "reason": "insufficient unregistered foreground overlap",
            "minimum_trusted_core_pixels": minimum_core_pixels,
            "minimum_foreground_pixels": minimum_foreground_pixels,
        }

    reference_rgb = reference_rgba[:, :, :3] * reference_mask[:, :, None]
    candidate_rgb = candidate_rgba[:, :, :3] * candidate_mask[:, :, None]
    reference_luma = _luminance(reference_rgb)
    candidate_luma = _luminance(candidate_rgb)

    rgb_mae = float(np.abs(candidate_rgb[core] - reference_rgb[core]).mean())
    color_distribution_error = _color_distribution_error(
        reference_rgb[reference_mask],
        candidate_rgb[candidate_mask],
    )
    luminance_structure_error = _multiscale_luminance_error(reference_luma, candidate_luma, core)
    detail_texture_error = _detail_error(reference_luma, candidate_luma, core)
    highlight_emission_error = _highlight_error(
        reference_luma[reference_mask],
        candidate_luma[candidate_mask],
    )
    errors = {
        "foreground_rgb": rgb_mae,
        "color_distribution": color_distribution_error,
        "luminance_structure": luminance_structure_error,
        "detail_texture": detail_texture_error,
        "highlight_emission": highlight_emission_error,
    }
    component_scores = {name: _clamp01(1.0 - error) for name, error in errors.items()}
    score = sum(component_scores[name] * COMPONENT_WEIGHTS[name] for name in COMPONENT_WEIGHTS)
    return {
        "version": "cross_engine_material_score_v2",
        "status": "ok",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "alignment": alignment,
        "trusted_core_pixels": int(core.sum()),
        "minimum_trusted_core_pixels": minimum_core_pixels,
        "minimum_foreground_pixels": minimum_foreground_pixels,
        "components": component_scores,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS),
        "notes": [
            "Material components use the eroded raw intersection only.",
            "No image translation, scale normalization, flip, affine transform, or non-rigid registration is applied.",
            "Full silhouette and bbox errors remain separate alignment diagnostics and do not masquerade as material color error.",
        ],
    }


def score_cross_engine_pair_v3(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score with explicit chroma/opponent-color discrimination."""

    base = score_cross_engine_pair(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v3"
        return result

    reference_rgb = np.asarray(reference.convert("RGBA"), dtype=np.float32)[:, :, :3] / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGBA"), dtype=np.float32)[:, :, :3] / 255.0
    core = trusted_intersection_core(reference, candidate, erosion_iterations=2)
    reference_features = _chroma_opponent_means(reference_rgb[core])
    candidate_features = _chroma_opponent_means(candidate_rgb[core])
    chroma_hue_error = _clamp01(
        2.0
        * (
            0.50 * abs(candidate_features[0] - reference_features[0])
            + 0.25 * abs(candidate_features[1] - reference_features[1])
            + 0.25 * abs(candidate_features[2] - reference_features[2])
        )
    )
    components = dict(base["components"])
    components["chroma_hue"] = _clamp01(1.0 - chroma_hue_error)
    score = sum(components[name] * COMPONENT_WEIGHTS_V3[name] for name in COMPONENT_WEIGHTS_V3)
    errors = dict(base["errors"])
    errors["chroma_hue"] = chroma_hue_error
    return {
        **base,
        "version": "cross_engine_material_score_v3",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V3),
        "chroma_opponent_means": {
            "reference": {
                "chroma": reference_features[0],
                "opponent_a": reference_features[1],
                "opponent_b": reference_features[2],
            },
            "candidate": {
                "chroma": candidate_features[0],
                "opponent_a": candidate_features[1],
                "opponent_b": candidate_features[2],
            },
        },
    }


def aggregate_cross_engine_scores(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v2")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS
    }
    return result


def aggregate_cross_engine_scores_v3(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v3")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V3
    }
    return result


def score_cross_engine_views(
    *,
    reference_dir: Path,
    candidate_dir: Path,
    views: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    from PIL import Image

    items: list[dict[str, Any]] = []
    for view in views:
        reference_path = reference_dir / str(view["file_name"])
        candidate_path = candidate_dir / str(view["file_name"])
        if not reference_path.exists() or not candidate_path.exists():
            return None
        with Image.open(reference_path) as reference, Image.open(candidate_path) as candidate:
            scored = score_cross_engine_pair(reference, candidate)
        items.append(
            {
                "view_id": str(view["view_id"]),
                "file_name": str(view["file_name"]),
                **scored,
            }
        )
    result = aggregate_cross_engine_scores(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v3(
    *,
    reference_dir: Path,
    candidate_dir: Path,
    views: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    from PIL import Image

    items: list[dict[str, Any]] = []
    for view in views:
        reference_path = reference_dir / str(view["file_name"])
        candidate_path = candidate_dir / str(view["file_name"])
        if not reference_path.exists() or not candidate_path.exists():
            return None
        with Image.open(reference_path) as reference, Image.open(candidate_path) as candidate:
            scored = score_cross_engine_pair_v3(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v3(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def _aggregate_scores(payloads: list[dict[str, Any]], *, version: str) -> dict[str, Any]:
    valid = [item for item in payloads if item.get("status") == "ok" and isinstance(item.get("score"), (int, float))]
    if len(valid) != len(payloads) or not valid:
        return {"version": version, "status": "invalid", "view_count": len(payloads), "valid_view_count": len(valid), "score": None}
    scores = np.asarray([float(item["score"]) for item in valid], dtype=np.float64)
    mean_score = float(scores.mean())
    p10_score = float(np.percentile(scores, 10))
    min_score = float(scores.min())
    robust_score = 0.70 * mean_score + 0.20 * p10_score + 0.10 * min_score
    return {
        "version": version,
        "status": "ok",
        "score": _clamp01(robust_score),
        "loss": _clamp01(1.0 - robust_score),
        "view_count": len(payloads),
        "valid_view_count": len(valid),
        "mean_score": mean_score,
        "p10_score": p10_score,
        "min_score": min_score,
        "aggregation": "0.70*mean + 0.20*p10 + 0.10*min",
        "views": payloads,
    }


def _chroma_opponent_means(rgb: np.ndarray) -> tuple[float, float, float]:
    if rgb.size == 0:
        return 0.0, 0.0, 0.0
    chroma = np.max(rgb, axis=1) - np.min(rgb, axis=1)
    opponent_a = (2.0 * rgb[:, 0] - rgb[:, 1] - rgb[:, 2]) / 2.0
    opponent_b = rgb[:, 1] - rgb[:, 2]
    return float(chroma.mean()), float(opponent_a.mean()), float(opponent_b.mean())


def _color_distribution_error(reference: np.ndarray, candidate: np.ndarray) -> float:
    quantiles = (0.10, 0.25, 0.50, 0.75, 0.90)
    reference_quantiles = np.quantile(reference, quantiles, axis=0)
    candidate_quantiles = np.quantile(candidate, quantiles, axis=0)
    quantile_error = float(np.abs(candidate_quantiles - reference_quantiles).mean())
    mean_error = float(np.abs(candidate.mean(axis=0) - reference.mean(axis=0)).mean())
    return _clamp01(0.70 * quantile_error + 0.30 * mean_error)


def _multiscale_luminance_error(reference: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> float:
    errors: list[float] = []
    weights: list[float] = []
    for block, weight in ((1, 0.50), (2, 0.25), (4, 0.15), (8, 0.10)):
        if block == 1:
            pooled_reference = reference
            pooled_candidate = candidate
            pooled_mask = mask
        else:
            pooled_reference = _block_mean(reference, block)
            pooled_candidate = _block_mean(candidate, block)
            pooled_mask = _block_mean(mask.astype(np.float32), block) >= 0.75
        if int(pooled_mask.sum()) <= 0:
            continue
        errors.append(float(np.abs(pooled_candidate[pooled_mask] - pooled_reference[pooled_mask]).mean()))
        weights.append(weight)
    return _clamp01(sum(error * weight for error, weight in zip(errors, weights)) / max(sum(weights), 1e-8))


def _detail_error(reference: np.ndarray, candidate: np.ndarray, mask: np.ndarray) -> float:
    interior = _erode(mask)
    if int(interior.sum()) <= 0:
        interior = mask
    reference_gy, reference_gx = np.gradient(reference)
    candidate_gy, candidate_gx = np.gradient(candidate)
    reference_gradient = np.hypot(reference_gx, reference_gy)
    candidate_gradient = np.hypot(candidate_gx, candidate_gy)
    return _clamp01(2.0 * float(np.abs(candidate_gradient[interior] - reference_gradient[interior]).mean()))


def _highlight_error(reference: np.ndarray, candidate: np.ndarray) -> float:
    reference_threshold = max(0.65, float(np.quantile(reference, 0.90)))
    candidate_threshold = max(0.65, float(np.quantile(candidate, 0.90)))
    reference_area = float((reference >= reference_threshold).mean())
    candidate_area = float((candidate >= candidate_threshold).mean())
    area_error = abs(candidate_area - reference_area) / max(reference_area, 0.02)
    peak_error = abs(float(np.quantile(candidate, 0.99)) - float(np.quantile(reference, 0.99)))
    return _clamp01(0.60 * area_error + 0.40 * peak_error)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def _block_mean(array: np.ndarray, block: int) -> np.ndarray:
    height = array.shape[0] // block * block
    width = array.shape[1] // block * block
    cropped = array[:height, :width]
    return cropped.reshape(height // block, block, width // block, block).mean(axis=(1, 3))


def _erode(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    neighborhoods = [
        padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
        for dy in range(3)
        for dx in range(3)
    ]
    return np.logical_and.reduce(neighborhoods)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
