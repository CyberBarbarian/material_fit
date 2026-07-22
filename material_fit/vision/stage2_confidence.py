"""Frozen trusted-core masks and scores for single-view Stage 2 fitting."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from material_fit.vision.cross_engine_alignment import (
    foreground_mask,
    score_alignment_pair,
    trusted_intersection_core,
)
from material_fit.vision.cross_engine_score import (
    COMPONENT_WEIGHTS_V3,
    _chroma_opponent_means,
    _clamp01,
    _color_distribution_error,
    _detail_error,
    _highlight_error,
    _luminance,
    _multiscale_luminance_error,
    score_cross_engine_pair_v3,
)


DEFAULT_EROSION_PIXELS = 10
MINIMUM_REFERENCE_COVERAGE = 0.55
MINIMUM_CANDIDATE_COVERAGE = 0.95
FROZEN_CORE_WEIGHT = 0.75
FULL_FOREGROUND_WEIGHT = 0.25


def build_frozen_confidence_mask(
    *,
    reference_path: Path,
    registered_start_path: Path,
    output_path: Path,
    erosion_pixels: int = DEFAULT_EROSION_PIXELS,
) -> dict[str, Any]:
    """Freeze a material-only core from target/start geometry before fitting."""

    with Image.open(reference_path) as reference_image:
        reference = reference_image.convert("RGBA")
    with Image.open(registered_start_path) as start_image:
        start = start_image.convert("RGBA")
    if reference.size != start.size:
        raise ValueError(
            f"Stage 2 confidence inputs differ in size: {reference.size} != {start.size}"
        )
    alignment = score_alignment_pair(reference, start)
    if alignment.get("status") != "ok":
        raise ValueError(f"Stage 2 confidence inputs are not alignable: {alignment}")

    reference_mask, _ = foreground_mask(reference)
    start_mask, _ = foreground_mask(start)
    trusted = trusted_intersection_core(
        reference,
        start,
        erosion_iterations=max(int(erosion_pixels), 0),
    )
    reference_pixels = int(reference_mask.sum())
    start_pixels = int(start_mask.sum())
    trusted_pixels = int(trusted.sum())
    reference_coverage = trusted_pixels / max(reference_pixels, 1)
    start_coverage = trusted_pixels / max(start_pixels, 1)
    if reference_coverage < MINIMUM_REFERENCE_COVERAGE:
        raise ValueError(
            "Stage 2 frozen confidence core is too small: "
            f"coverage={reference_coverage:.6f} < {MINIMUM_REFERENCE_COVERAGE:.6f}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(trusted.astype(np.uint8) * 255).save(output_path)
    return {
        "contract": "material_fit_stage2_frozen_confidence_mask_v1",
        "reference_path": str(reference_path.resolve()),
        "registered_start_path": str(registered_start_path.resolve()),
        "output_path": str(output_path.resolve()),
        "output_sha256": _sha256(output_path),
        "size": list(reference.size),
        "erosion_pixels": int(erosion_pixels),
        "reference_foreground_pixels": reference_pixels,
        "start_foreground_pixels": start_pixels,
        "trusted_pixels": trusted_pixels,
        "reference_coverage": reference_coverage,
        "start_coverage": start_coverage,
        "minimum_reference_coverage": MINIMUM_REFERENCE_COVERAGE,
        "minimum_candidate_coverage": MINIMUM_CANDIDATE_COVERAGE,
        "alignment": alignment,
        "frozen_before_optimization": True,
        "candidate_dependent": False,
    }


def score_pair_with_frozen_confidence(
    reference: Image.Image,
    candidate: Image.Image,
    confidence_mask: Image.Image,
    *,
    minimum_candidate_coverage: float = MINIMUM_CANDIDATE_COVERAGE,
) -> dict[str, Any]:
    """Score all material components on one immutable geometry-safe core."""

    reference_rgba = np.asarray(reference.convert("RGBA"), dtype=np.float32) / 255.0
    candidate_rgba = np.asarray(candidate.convert("RGBA"), dtype=np.float32) / 255.0
    confidence = np.asarray(confidence_mask.convert("L"), dtype=np.uint8) >= 128
    if reference_rgba.shape != candidate_rgba.shape or confidence.shape != reference_rgba.shape[:2]:
        return {
            "version": "cross_engine_material_score_v4_frozen_confidence",
            "status": "invalid",
            "reason": "reference, candidate, and confidence mask shapes differ",
        }

    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    frozen_pixels = int(confidence.sum())
    active = confidence & reference_mask & candidate_mask
    active_pixels = int(active.sum())
    candidate_coverage = active_pixels / max(frozen_pixels, 1)
    alignment = score_alignment_pair(reference, candidate)
    if frozen_pixels < 256 or candidate_coverage < float(minimum_candidate_coverage):
        return {
            "version": "cross_engine_material_score_v4_frozen_confidence",
            "status": "invalid_confidence_coverage",
            "score": 0.0,
            "loss": 1.0,
            "alignment": alignment,
            "frozen_confidence_pixels": frozen_pixels,
            "active_confidence_pixels": active_pixels,
            "candidate_confidence_coverage": candidate_coverage,
            "minimum_candidate_confidence_coverage": float(minimum_candidate_coverage),
        }
    if alignment.get("status") != "ok":
        return {
            "version": "cross_engine_material_score_v4_frozen_confidence",
            "status": "invalid_alignment",
            "score": None,
            "alignment": alignment,
        }

    reference_rgb = reference_rgba[:, :, :3]
    candidate_rgb = candidate_rgba[:, :, :3]
    reference_luma = _luminance(reference_rgb)
    candidate_luma = _luminance(candidate_rgb)
    rgb_error = float(np.abs(candidate_rgb[active] - reference_rgb[active]).mean())
    color_error = _color_distribution_error(reference_rgb[active], candidate_rgb[active])
    luminance_error = _multiscale_luminance_error(
        reference_luma,
        candidate_luma,
        active,
    )
    detail_error = _detail_error(reference_luma, candidate_luma, active)
    highlight_error = _highlight_error(reference_luma[active], candidate_luma[active])
    reference_chroma = _chroma_opponent_means(reference_rgb[active])
    candidate_chroma = _chroma_opponent_means(candidate_rgb[active])
    chroma_error = _clamp01(
        2.0
        * (
            0.50 * abs(candidate_chroma[0] - reference_chroma[0])
            + 0.25 * abs(candidate_chroma[1] - reference_chroma[1])
            + 0.25 * abs(candidate_chroma[2] - reference_chroma[2])
        )
    )
    errors = {
        "foreground_rgb": rgb_error,
        "color_distribution": color_error,
        "chroma_hue": chroma_error,
        "luminance_structure": luminance_error,
        "detail_texture": detail_error,
        "highlight_emission": highlight_error,
    }
    components = {name: _clamp01(1.0 - error) for name, error in errors.items()}
    score = sum(components[name] * COMPONENT_WEIGHTS_V3[name] for name in COMPONENT_WEIGHTS_V3)
    return {
        "version": "cross_engine_material_score_v4_frozen_confidence",
        "status": "ok",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "alignment": alignment,
        "frozen_confidence_pixels": frozen_pixels,
        "active_confidence_pixels": active_pixels,
        "candidate_confidence_coverage": candidate_coverage,
        "minimum_candidate_confidence_coverage": float(minimum_candidate_coverage),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V3),
        "mask_is_frozen": True,
    }


def score_pair_with_frozen_confidence_blend(
    reference: Image.Image,
    candidate: Image.Image,
    confidence_mask: Image.Image,
) -> dict[str, Any]:
    """Blend a dominant frozen core with a low-weight full-foreground guard."""

    frozen = score_pair_with_frozen_confidence(reference, candidate, confidence_mask)
    full = score_cross_engine_pair_v3(reference, candidate)
    if frozen.get("status") != "ok" or full.get("status") != "ok":
        return {
            "version": "cross_engine_material_score_v5_frozen_confidence_blend",
            "status": "invalid",
            "score": 0.0,
            "loss": 1.0,
            "frozen_confidence": frozen,
            "full_foreground": full,
        }
    components = {
        name: _clamp01(
            FROZEN_CORE_WEIGHT * float(frozen["components"][name])
            + FULL_FOREGROUND_WEIGHT * float(full["components"][name])
        )
        for name in COMPONENT_WEIGHTS_V3
    }
    score = _clamp01(
        FROZEN_CORE_WEIGHT * float(frozen["score"])
        + FULL_FOREGROUND_WEIGHT * float(full["score"])
    )
    return {
        "version": "cross_engine_material_score_v5_frozen_confidence_blend",
        "status": "ok",
        "score": score,
        "loss": _clamp01(1.0 - score),
        "components": components,
        "weights": {
            "frozen_confidence": FROZEN_CORE_WEIGHT,
            "full_foreground": FULL_FOREGROUND_WEIGHT,
        },
        "candidate_confidence_coverage": frozen["candidate_confidence_coverage"],
        "frozen_confidence_score": frozen["score"],
        "full_foreground_score": full["score"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DEFAULT_EROSION_PIXELS",
    "MINIMUM_CANDIDATE_COVERAGE",
    "MINIMUM_REFERENCE_COVERAGE",
    "FROZEN_CORE_WEIGHT",
    "FULL_FOREGROUND_WEIGHT",
    "build_frozen_confidence_mask",
    "score_pair_with_frozen_confidence",
    "score_pair_with_frozen_confidence_blend",
]
