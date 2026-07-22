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

COMPONENT_WEIGHTS_V4 = {
    "foreground_rgb": 0.22,
    "color_distribution": 0.13,
    "chroma_hue": 0.15,
    "luminance_structure": 0.10,
    "detail_texture": 0.05,
    "highlight_emission": 0.03,
    "texture_detail_distribution": 0.32,
}

COMPONENT_WEIGHTS_V5 = {
    "foreground_rgb": 0.17,
    "color_distribution": 0.10,
    "chroma_hue": 0.10,
    "luminance_structure": 0.08,
    "detail_texture": 0.04,
    "highlight_emission": 0.02,
    "texture_detail_distribution": 0.25,
    "spatial_luminance_layout": 0.24,
}

COMPONENT_WEIGHTS_V6 = {
    "foreground_rgb": 0.0935,
    "color_distribution": 0.055,
    "chroma_hue": 0.055,
    "luminance_structure": 0.044,
    "detail_texture": 0.022,
    "highlight_emission": 0.011,
    "texture_detail_distribution": 0.1375,
    "spatial_luminance_layout": 0.132,
    "spatial_hue_mass": 0.45,
}

COMPONENT_WEIGHTS_V7 = {
    "foreground_rgb": 0.051425,
    "color_distribution": 0.03025,
    "chroma_hue": 0.03025,
    "luminance_structure": 0.0242,
    "detail_texture": 0.0121,
    "highlight_emission": 0.00605,
    "texture_detail_distribution": 0.075625,
    "spatial_luminance_layout": 0.0726,
    "spatial_hue_mass": 0.2475,
    "spatial_dark_chroma": 0.45,
}

COMPONENT_WEIGHTS_V8 = {
    "foreground_rgb": 0.034,
    "color_distribution": 0.020,
    "chroma_hue": 0.020,
    "luminance_structure": 0.016,
    "detail_texture": 0.008,
    "highlight_emission": 0.004,
    "texture_detail_distribution": 0.050,
    "spatial_luminance_layout": 0.048,
    "spatial_chromaticity": 0.550,
    "spatial_dark_chroma": 0.250,
}

COMPONENT_WEIGHTS_V9 = {
    "foreground_rgb": 0.0221,
    "color_distribution": 0.0130,
    "chroma_hue": 0.0130,
    "luminance_structure": 0.0104,
    "detail_texture": 0.0052,
    "highlight_emission": 0.0026,
    "texture_detail_distribution": 0.0325,
    "spatial_luminance_layout": 0.0312,
    "spatial_chromaticity": 0.3575,
    "spatial_dark_chroma": 0.1625,
    "spatial_radiance": 0.3500,
}

COMPONENT_WEIGHTS_V10 = {
    "foreground_rgb": 0.0221,
    "color_distribution": 0.0130,
    "chroma_hue": 0.0130,
    "luminance_structure": 0.0104,
    "detail_texture": 0.0052,
    "highlight_emission": 0.0026,
    "texture_detail_distribution": 0.0325,
    "spatial_luminance_layout": 0.0312,
    "spatial_chromaticity": 0.3575,
    "spatial_dark_chroma": 0.1625,
    "spatial_highlight_energy": 0.3500,
}

COMPONENT_WEIGHTS_V11 = {
    "spatial_chromaticity": 0.25,
    "spatial_dark_chroma": 0.25,
    "spatial_highlight_energy": 0.30,
    "spatial_luminance_layout": 0.15,
    "texture_detail_distribution": 0.05,
}

COMPONENT_NAMES_V12 = tuple(COMPONENT_WEIGHTS_V11)


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


def score_cross_engine_pair_v4(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score with pose-tolerant texture-detail preservation.

    V3's pointwise gradient error can reward a bright, smooth candidate when
    its remaining gradients happen to have the target's average magnitude.
    V4 also compares foreground-internal gradient, high-pass, and Laplacian
    distributions. Those statistics survive small pose changes while exposing
    lost shell plates, scales, seams, and other material-driven detail.
    """

    base = score_cross_engine_pair_v3(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v4"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_detail = _texture_detail_descriptor(
        _luminance(reference_rgb),
        _erode_n(reference_mask, 8),
    )
    candidate_detail = _texture_detail_descriptor(
        _luminance(candidate_rgb),
        _erode_n(candidate_mask, 8),
    )
    detail_log_error = float(
        np.abs(np.log((candidate_detail + 0.005) / (reference_detail + 0.005))).mean()
    )
    detail_distribution_score = _clamp01(float(np.exp(-1.2 * detail_log_error)))

    components = dict(base["components"])
    components["texture_detail_distribution"] = detail_distribution_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V4[name] for name in COMPONENT_WEIGHTS_V4)
    errors = dict(base["errors"])
    errors["texture_detail_distribution"] = _clamp01(1.0 - detail_distribution_score)
    return {
        **base,
        "version": "cross_engine_material_score_v4",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V4),
        "texture_detail": {
            "metric": "foreground_texture_quantiles_v1",
            "log_ratio_error": detail_log_error,
            "reference_descriptor": [float(value) for value in reference_detail],
            "candidate_descriptor": [float(value) for value in candidate_detail],
            "pose_tolerance": "independent foreground distributions; no candidate registration",
        },
    }


def score_cross_engine_pair_v5(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score that preserves model-relative dark and light placement."""

    base = score_cross_engine_pair_v4(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v5"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_descriptor = _spatial_luminance_descriptor(
        _luminance(reference_rgb),
        reference_mask,
    )
    candidate_descriptor = _spatial_luminance_descriptor(
        _luminance(candidate_rgb),
        candidate_mask,
    )
    dark_distribution_error = 0.5 * float(
        np.abs(
            candidate_descriptor["dark_distribution"]
            - reference_descriptor["dark_distribution"]
        ).sum()
    )
    valid_cells = (
        (reference_descriptor["occupancy"] > 0.15)
        & (candidate_descriptor["occupancy"] > 0.15)
    )
    if int(valid_cells.sum()) == 0:
        spatial_luminance_error = 1.0
    else:
        spatial_luminance_error = float(
            np.abs(
                candidate_descriptor["luminance_quantiles"][valid_cells]
                - reference_descriptor["luminance_quantiles"][valid_cells]
            ).mean()
        )
    dark_distribution_score = _clamp01(float(np.exp(-4.0 * dark_distribution_error)))
    spatial_luminance_score = _clamp01(float(np.exp(-3.0 * spatial_luminance_error)))
    layout_score = _clamp01(
        0.65 * dark_distribution_score + 0.35 * spatial_luminance_score
    )

    components = dict(base["components"])
    components["spatial_luminance_layout"] = layout_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V5[name] for name in COMPONENT_WEIGHTS_V5)
    errors = dict(base["errors"])
    errors["spatial_luminance_layout"] = _clamp01(1.0 - layout_score)
    return {
        **base,
        "version": "cross_engine_material_score_v5",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V5),
        "spatial_luminance": {
            "metric": "model_relative_spatial_luminance_v1",
            "grid": [4, 6],
            "dark_distribution_error": dark_distribution_error,
            "spatial_luminance_error": spatial_luminance_error,
            "dark_distribution_score": dark_distribution_score,
            "spatial_luminance_score": spatial_luminance_score,
            "valid_cell_count": int(valid_cells.sum()),
            "reference_dark_distribution": reference_descriptor[
                "dark_distribution"
            ].reshape(-1).tolist(),
            "candidate_dark_distribution": candidate_descriptor[
                "dark_distribution"
            ].reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v6(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score that preserves where chromatic colors appear on the model."""

    base = score_cross_engine_pair_v5(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v6"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_hue_mass = _spatial_hue_mass_descriptor(reference_rgb, reference_mask)
    candidate_hue_mass = _spatial_hue_mass_descriptor(candidate_rgb, candidate_mask)
    hue_mass_error = 0.5 * float(np.abs(candidate_hue_mass - reference_hue_mass).sum())
    hue_mass_score = _clamp01(float(np.exp(-5.0 * hue_mass_error)))

    components = dict(base["components"])
    components["spatial_hue_mass"] = hue_mass_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V6[name] for name in COMPONENT_WEIGHTS_V6)
    errors = dict(base["errors"])
    errors["spatial_hue_mass"] = _clamp01(1.0 - hue_mass_score)
    return {
        **base,
        "version": "cross_engine_material_score_v6",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V6),
        "spatial_hue_mass": {
            "metric": "model_relative_spatial_hue_mass_v1",
            "grid": [4, 6],
            "hue_bins": 12,
            "hue_mass_error": hue_mass_error,
            "hue_mass_score": hue_mass_score,
            "reference_descriptor": reference_hue_mass.reshape(-1).tolist(),
            "candidate_descriptor": candidate_hue_mass.reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v7(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score that rejects colored contamination in dark model regions."""

    base = score_cross_engine_pair_v6(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v7"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_dark_chroma = _spatial_dark_chroma_descriptor(reference_rgb, reference_mask)
    candidate_dark_chroma = _spatial_dark_chroma_descriptor(candidate_rgb, candidate_mask)
    dark_chroma_error = float(np.abs(candidate_dark_chroma - reference_dark_chroma).sum())
    dark_chroma_score = _clamp01(float(np.exp(-8.0 * dark_chroma_error)))

    components = dict(base["components"])
    components["spatial_dark_chroma"] = dark_chroma_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V7[name] for name in COMPONENT_WEIGHTS_V7)
    errors = dict(base["errors"])
    errors["spatial_dark_chroma"] = _clamp01(1.0 - dark_chroma_score)
    return {
        **base,
        "version": "cross_engine_material_score_v7",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V7),
        "spatial_dark_chroma": {
            "metric": "model_relative_spatial_dark_chroma_v1",
            "grid": [4, 6],
            "dark_chroma_error": dark_chroma_error,
            "dark_chroma_score": dark_chroma_score,
            "reference_descriptor": reference_dark_chroma.reshape(-1).tolist(),
            "candidate_descriptor": candidate_dark_chroma.reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v8(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score dominated by model-relative RGB chromaticity fidelity."""

    base = score_cross_engine_pair_v7(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v8"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_descriptor = _spatial_chromaticity_descriptor(reference_rgb, reference_mask)
    candidate_descriptor = _spatial_chromaticity_descriptor(candidate_rgb, candidate_mask)
    valid_cells = (
        (reference_descriptor["occupancy"] > 0.15)
        & (candidate_descriptor["occupancy"] > 0.15)
    )
    if int(valid_cells.sum()) == 0:
        chromaticity_error = 1.0
    else:
        chromaticity_error = float(
            np.abs(
                candidate_descriptor["quantiles"][valid_cells]
                - reference_descriptor["quantiles"][valid_cells]
            ).mean()
        )
    chromaticity_score = _clamp01(float(np.exp(-6.0 * chromaticity_error)))

    components = dict(base["components"])
    components["spatial_chromaticity"] = chromaticity_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V8[name] for name in COMPONENT_WEIGHTS_V8)
    errors = dict(base["errors"])
    errors["spatial_chromaticity"] = _clamp01(1.0 - chromaticity_score)
    return {
        **base,
        "version": "cross_engine_material_score_v8",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V8),
        "spatial_chromaticity": {
            "metric": "model_relative_spatial_rgb_chromaticity_v1",
            "grid": [4, 6],
            "quantiles": [0.25, 0.50, 0.75],
            "chromaticity_error": chromaticity_error,
            "chromaticity_score": chromaticity_score,
            "valid_cell_count": int(valid_cells.sum()),
            "reference_descriptor": reference_descriptor["quantiles"].reshape(-1).tolist(),
            "candidate_descriptor": candidate_descriptor["quantiles"].reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v9(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score that preserves absolute per-cell RGB radiance."""

    base = score_cross_engine_pair_v8(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v9"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_descriptor = _spatial_radiance_descriptor(reference_rgb, reference_mask)
    candidate_descriptor = _spatial_radiance_descriptor(candidate_rgb, candidate_mask)
    valid_cells = (
        (reference_descriptor["occupancy"] > 0.15)
        & (candidate_descriptor["occupancy"] > 0.15)
    )
    if int(valid_cells.sum()) == 0:
        radiance_error = 1.0
    else:
        radiance_error = float(
            np.abs(
                candidate_descriptor["quantiles"][valid_cells]
                - reference_descriptor["quantiles"][valid_cells]
            ).mean()
        )
    radiance_score = _clamp01(float(np.exp(-4.0 * radiance_error)))

    components = dict(base["components"])
    components["spatial_radiance"] = radiance_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V9[name] for name in COMPONENT_WEIGHTS_V9)
    errors = dict(base["errors"])
    errors["spatial_radiance"] = _clamp01(1.0 - radiance_score)
    return {
        **base,
        "version": "cross_engine_material_score_v9",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V9),
        "spatial_radiance": {
            "metric": "model_relative_spatial_rgb_radiance_v1",
            "grid": [4, 6],
            "quantiles": [0.50, 0.75, 0.90, 0.95, 0.99],
            "radiance_error": radiance_error,
            "radiance_score": radiance_score,
            "valid_cell_count": int(valid_cells.sum()),
            "reference_descriptor": reference_descriptor["quantiles"].reshape(-1).tolist(),
            "candidate_descriptor": candidate_descriptor["quantiles"].reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v10(reference: Any, candidate: Any) -> dict[str, Any]:
    """Material score with target-adaptive spatial highlight energy."""

    base = score_cross_engine_pair_v8(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v10"
        return result

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float32) / 255.0
    reference_mask, _ = foreground_mask(reference)
    candidate_mask, _ = foreground_mask(candidate)
    reference_luma = _luminance(reference_rgb)
    candidate_luma = _luminance(candidate_rgb)
    thresholds = np.quantile(reference_luma[reference_mask], [0.75, 0.90, 0.95])
    reference_descriptor = _spatial_highlight_descriptor(
        reference_luma,
        reference_mask,
        thresholds,
    )
    candidate_descriptor = _spatial_highlight_descriptor(
        candidate_luma,
        candidate_mask,
        thresholds,
    )
    valid_cells = (
        (reference_descriptor["occupancy"] > 0.15)
        & (candidate_descriptor["occupancy"] > 0.15)
    )
    if int(valid_cells.sum()) == 0:
        area_error = 1.0
        energy_error = 1.0
    else:
        area_error = float(
            np.abs(
                candidate_descriptor["area"][valid_cells]
                - reference_descriptor["area"][valid_cells]
            ).mean()
        )
        energy_error = float(
            np.abs(
                candidate_descriptor["energy"][valid_cells]
                - reference_descriptor["energy"][valid_cells]
            ).mean()
        )
    highlight_score = _clamp01(float(np.exp(-3.0 * area_error - 8.0 * energy_error)))

    components = dict(base["components"])
    components["spatial_highlight_energy"] = highlight_score
    score = sum(components[name] * COMPONENT_WEIGHTS_V10[name] for name in COMPONENT_WEIGHTS_V10)
    errors = dict(base["errors"])
    errors["spatial_highlight_energy"] = _clamp01(1.0 - highlight_score)
    return {
        **base,
        "version": "cross_engine_material_score_v10",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "errors": errors,
        "weights": dict(COMPONENT_WEIGHTS_V10),
        "spatial_highlight_energy": {
            "metric": "model_relative_target_adaptive_highlight_energy_v1",
            "grid": [4, 6],
            "reference_quantiles": [0.75, 0.90, 0.95],
            "thresholds": thresholds.tolist(),
            "area_error": area_error,
            "energy_error": energy_error,
            "highlight_score": highlight_score,
            "valid_cell_count": int(valid_cells.sum()),
            "reference_area": reference_descriptor["area"].reshape(-1).tolist(),
            "candidate_area": candidate_descriptor["area"].reshape(-1).tolist(),
            "reference_energy": reference_descriptor["energy"].reshape(-1).tolist(),
            "candidate_energy": candidate_descriptor["energy"].reshape(-1).tolist(),
        },
    }


def score_cross_engine_pair_v11(reference: Any, candidate: Any) -> dict[str, Any]:
    """Balance all essential material dimensions with a weighted geometric mean."""

    base = score_cross_engine_pair_v10(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v11"
        return result

    components = dict(base["components"])
    score = float(
        np.exp(
            sum(
                weight * np.log(max(1e-6, float(components[name])))
                for name, weight in COMPONENT_WEIGHTS_V11.items()
            )
        )
    )
    return {
        **base,
        "version": "cross_engine_material_score_v11",
        "score": _clamp01(score),
        "loss": _clamp01(1.0 - score),
        "components": components,
        "weights": dict(COMPONENT_WEIGHTS_V11),
        "aggregation": "weighted_geometric_mean",
    }


def score_cross_engine_pair_v12(reference: Any, candidate: Any) -> dict[str, Any]:
    """Use a conservative lower bound across generic material dimensions."""

    base = score_cross_engine_pair_v10(reference, candidate)
    if base.get("status") != "ok":
        result = dict(base)
        result["version"] = "cross_engine_material_score_v12"
        return result

    components = dict(base["components"])
    values = np.asarray(
        [float(components[name]) for name in COMPONENT_NAMES_V12],
        dtype=np.float64,
    )
    component_mean = float(values.mean())
    component_std = float(values.std())
    score = _clamp01(component_mean - component_std)
    return {
        **base,
        "version": "cross_engine_material_score_v12",
        "score": score,
        "loss": _clamp01(1.0 - score),
        "components": components,
        "component_names": list(COMPONENT_NAMES_V12),
        "component_mean": component_mean,
        "component_std": component_std,
        "aggregation": "equal_component_mean_minus_population_std",
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


def aggregate_cross_engine_scores_v4(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v4")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V4
    }
    return result


def aggregate_cross_engine_scores_v5(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v5")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V5
    }
    return result


def aggregate_cross_engine_scores_v6(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v6")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V6
    }
    return result


def aggregate_cross_engine_scores_v7(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v7")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V7
    }
    return result


def aggregate_cross_engine_scores_v8(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v8")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V8
    }
    return result


def aggregate_cross_engine_scores_v9(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v9")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V9
    }
    return result


def aggregate_cross_engine_scores_v10(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v10")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V10
    }
    return result


def aggregate_cross_engine_scores_v11(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v11")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_WEIGHTS_V11
    }
    return result


def aggregate_cross_engine_scores_v12(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payloads = list(items)
    result = _aggregate_scores(payloads, version="cross_engine_material_score_v12")
    if result.get("status") != "ok":
        return result
    valid = [item for item in payloads if item.get("status") == "ok"]
    result["components"] = {
        name: float(np.mean([float(item["components"][name]) for item in valid]))
        for name in COMPONENT_NAMES_V12
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


def score_cross_engine_views_v4(
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
            scored = score_cross_engine_pair_v4(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v4(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v5(
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
            scored = score_cross_engine_pair_v5(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v5(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v6(
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
            scored = score_cross_engine_pair_v6(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v6(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v7(
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
            scored = score_cross_engine_pair_v7(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v7(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v8(
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
            scored = score_cross_engine_pair_v8(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v8(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v9(
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
            scored = score_cross_engine_pair_v9(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v9(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v10(
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
            scored = score_cross_engine_pair_v10(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v10(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v11(
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
            scored = score_cross_engine_pair_v11(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v11(items)
    result["reference_dir"] = str(reference_dir)
    result["candidate_dir"] = str(candidate_dir)
    return result


def score_cross_engine_views_v12(
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
            scored = score_cross_engine_pair_v12(reference, candidate)
        items.append({"view_id": str(view["view_id"]), "file_name": str(view["file_name"]), **scored})
    result = aggregate_cross_engine_scores_v12(items)
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


def _spatial_luminance_descriptor(
    luminance: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
) -> dict[str, np.ndarray]:
    """Describe brightness placement in coordinates normalized to the model bbox."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial luminance descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    foreground_luminance = luminance[mask]
    q10, q50 = np.quantile(foreground_luminance, [0.10, 0.50])
    dark_scale = max(0.05, float(q50 - q10))
    dark_weight = np.clip((float(q50) - luminance) / dark_scale, 0.0, 1.0) * mask

    dark_distribution = np.zeros((rows, columns), dtype=np.float64)
    luminance_quantiles = np.zeros((rows, columns, 3), dtype=np.float64)
    occupancy = np.zeros((rows, columns), dtype=np.float64)
    for row in range(rows):
        cell_y0 = y0 + (y1 - y0) * row // rows
        cell_y1 = y0 + (y1 - y0) * (row + 1) // rows
        for column in range(columns):
            cell_x0 = x0 + (x1 - x0) * column // columns
            cell_x1 = x0 + (x1 - x0) * (column + 1) // columns
            cell_mask = mask[cell_y0:cell_y1, cell_x0:cell_x1]
            occupancy[row, column] = float(cell_mask.mean())
            cell_luminance = luminance[cell_y0:cell_y1, cell_x0:cell_x1][cell_mask]
            if cell_luminance.size:
                luminance_quantiles[row, column] = np.quantile(
                    cell_luminance,
                    [0.25, 0.50, 0.75],
                )
            dark_distribution[row, column] = float(
                dark_weight[cell_y0:cell_y1, cell_x0:cell_x1].sum()
            )
    dark_total = float(dark_distribution.sum())
    if dark_total > 0.0:
        dark_distribution /= dark_total
    return {
        "dark_distribution": dark_distribution,
        "luminance_quantiles": luminance_quantiles,
        "occupancy": occupancy,
    }


def _spatial_hue_mass_descriptor(
    rgb: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
    hue_bins: int = 12,
) -> np.ndarray:
    """Accumulate soft hue-bin mass in coordinates normalized to the model bbox."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial hue descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    values = rgb[mask]
    maximum = values.max(axis=1)
    minimum = values.min(axis=1)
    chroma = maximum - minimum
    hue = np.zeros(len(values), dtype=np.float64)
    nonzero = chroma > 1e-6
    red = nonzero & (maximum == values[:, 0])
    green = nonzero & (maximum == values[:, 1])
    blue = nonzero & (maximum == values[:, 2])
    hue[red] = ((values[red, 1] - values[red, 2]) / chroma[red]) % 6.0
    hue[green] = (values[green, 2] - values[green, 0]) / chroma[green] + 2.0
    hue[blue] = (values[blue, 0] - values[blue, 1]) / chroma[blue] + 4.0
    hue /= 6.0

    hue_position = hue * hue_bins
    lower_bins = np.floor(hue_position).astype(np.int64) % hue_bins
    upper_fraction = hue_position - np.floor(hue_position)
    model_columns = np.minimum(
        columns - 1,
        ((xs - x0) * columns // max(1, x1 - x0)).astype(np.int64),
    )
    model_rows = np.minimum(
        rows - 1,
        ((ys - y0) * rows // max(1, y1 - y0)).astype(np.int64),
    )
    descriptor = np.zeros((rows, columns, hue_bins), dtype=np.float64)
    np.add.at(
        descriptor,
        (model_rows, model_columns, lower_bins),
        chroma * (1.0 - upper_fraction),
    )
    np.add.at(
        descriptor,
        (model_rows, model_columns, (lower_bins + 1) % hue_bins),
        chroma * upper_fraction,
    )
    descriptor /= max(1, len(values))
    return descriptor


def _spatial_dark_chroma_descriptor(
    rgb: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
) -> np.ndarray:
    """Describe low-luminance chroma mass in model-relative coordinates."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial dark chroma descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    values = rgb[mask]
    chroma = values.max(axis=1) - values.min(axis=1)
    luminance = 0.2126 * values[:, 0] + 0.7152 * values[:, 1] + 0.0722 * values[:, 2]
    dark_chroma = chroma * np.square(1.0 - luminance)
    model_columns = np.minimum(
        columns - 1,
        ((xs - x0) * columns // max(1, x1 - x0)).astype(np.int64),
    )
    model_rows = np.minimum(
        rows - 1,
        ((ys - y0) * rows // max(1, y1 - y0)).astype(np.int64),
    )
    descriptor = np.zeros((rows, columns), dtype=np.float64)
    np.add.at(descriptor, (model_rows, model_columns), dark_chroma)
    descriptor /= max(1, len(values))
    return descriptor


def _spatial_chromaticity_descriptor(
    rgb: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
) -> dict[str, np.ndarray]:
    """Describe per-cell RGB ratios independently of overall intensity."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial chromaticity descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    quantiles = np.zeros((rows, columns, 3, 3), dtype=np.float64)
    occupancy = np.zeros((rows, columns), dtype=np.float64)
    for row in range(rows):
        cell_y0 = y0 + (y1 - y0) * row // rows
        cell_y1 = y0 + (y1 - y0) * (row + 1) // rows
        for column in range(columns):
            cell_x0 = x0 + (x1 - x0) * column // columns
            cell_x1 = x0 + (x1 - x0) * (column + 1) // columns
            cell_mask = mask[cell_y0:cell_y1, cell_x0:cell_x1]
            occupancy[row, column] = float(cell_mask.mean())
            values = rgb[cell_y0:cell_y1, cell_x0:cell_x1][cell_mask]
            if values.size == 0:
                continue
            chromaticity = values / np.maximum(values.sum(axis=1, keepdims=True), 0.05)
            quantiles[row, column] = np.quantile(
                chromaticity,
                [0.25, 0.50, 0.75],
                axis=0,
            )
    return {"quantiles": quantiles, "occupancy": occupancy}


def _spatial_radiance_descriptor(
    rgb: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
) -> dict[str, np.ndarray]:
    """Describe absolute RGB intensity in model-relative coordinates."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial radiance descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    quantiles = np.zeros((rows, columns, 5, 3), dtype=np.float64)
    occupancy = np.zeros((rows, columns), dtype=np.float64)
    for row in range(rows):
        cell_y0 = y0 + (y1 - y0) * row // rows
        cell_y1 = y0 + (y1 - y0) * (row + 1) // rows
        for column in range(columns):
            cell_x0 = x0 + (x1 - x0) * column // columns
            cell_x1 = x0 + (x1 - x0) * (column + 1) // columns
            cell_mask = mask[cell_y0:cell_y1, cell_x0:cell_x1]
            occupancy[row, column] = float(cell_mask.mean())
            values = rgb[cell_y0:cell_y1, cell_x0:cell_x1][cell_mask]
            if values.size == 0:
                continue
            quantiles[row, column] = np.quantile(
                values,
                [0.50, 0.75, 0.90, 0.95, 0.99],
                axis=0,
            )
    return {"quantiles": quantiles, "occupancy": occupancy}


def _spatial_highlight_descriptor(
    luminance: np.ndarray,
    mask: np.ndarray,
    thresholds: np.ndarray,
    *,
    rows: int = 4,
    columns: int = 6,
) -> dict[str, np.ndarray]:
    """Describe highlight area and excess energy using target-derived thresholds."""

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("spatial highlight descriptor requires foreground pixels")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    area = np.zeros((rows, columns, len(thresholds)), dtype=np.float64)
    energy = np.zeros((rows, columns, len(thresholds)), dtype=np.float64)
    occupancy = np.zeros((rows, columns), dtype=np.float64)
    for row in range(rows):
        cell_y0 = y0 + (y1 - y0) * row // rows
        cell_y1 = y0 + (y1 - y0) * (row + 1) // rows
        for column in range(columns):
            cell_x0 = x0 + (x1 - x0) * column // columns
            cell_x1 = x0 + (x1 - x0) * (column + 1) // columns
            cell_mask = mask[cell_y0:cell_y1, cell_x0:cell_x1]
            occupancy[row, column] = float(cell_mask.mean())
            values = luminance[cell_y0:cell_y1, cell_x0:cell_x1][cell_mask]
            if values.size == 0:
                continue
            for index, threshold in enumerate(thresholds):
                area[row, column, index] = float(np.mean(values >= threshold))
                energy[row, column, index] = float(
                    np.maximum(values - threshold, 0.0).mean()
                )
    return {"area": area, "energy": energy, "occupancy": occupancy}


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


def _texture_detail_descriptor(luminance: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if int(mask.sum()) < 256:
        mask = np.ones(luminance.shape, dtype=bool)
    padded = np.pad(luminance, 1, mode="edge")
    north_west = padded[:-2, :-2]
    north = padded[:-2, 1:-1]
    north_east = padded[:-2, 2:]
    west = padded[1:-1, :-2]
    center = padded[1:-1, 1:-1]
    east = padded[1:-1, 2:]
    south_west = padded[2:, :-2]
    south = padded[2:, 1:-1]
    south_east = padded[2:, 2:]

    gradient_x = (
        north_east + 2.0 * east + south_east
        - north_west - 2.0 * west - south_west
    ) / 8.0
    gradient_y = (
        south_west + 2.0 * south + south_east
        - north_west - 2.0 * north - north_east
    ) / 8.0
    gradient = np.hypot(gradient_x, gradient_y)
    gaussian = (
        north_west + 2.0 * north + north_east
        + 2.0 * west + 4.0 * center + 2.0 * east
        + south_west + 2.0 * south + south_east
    ) / 16.0
    high_pass = np.abs(center - gaussian)
    laplacian = np.abs(north + south + west + east - 4.0 * center) / 4.0
    quantiles = (0.50, 0.75, 0.90, 0.95, 0.99)
    return np.concatenate(
        [np.quantile(values[mask], quantiles) for values in (gradient, high_pass, laplacian)]
    ).astype(np.float64)


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


def _erode_n(mask: np.ndarray, iterations: int) -> np.ndarray:
    eroded = mask.astype(bool)
    for _ in range(max(0, int(iterations))):
        next_mask = _erode(eroded)
        if int(next_mask.sum()) < 256:
            break
        eroded = next_mask
    return eroded


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
