from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - environment dependent
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

_PERCEPTUAL_CACHE: dict[str, Any] = {}
_REFERENCE_FEATURE_CACHE: dict[str, dict[str, Any]] = {}
_VALIDITY_FAILED_LOSS_FLOOR = 0.85


def build_research_metrics(
    reference: Any,
    candidate: Any,
    *,
    explicit_mask: Any = None,
    fallback_mask: Any = None,
    compute_perceptual_optional: bool = True,
    reference_cache_key: str | None = None,
) -> dict[str, Any]:
    """Compute P0 research metrics for one reference/candidate render pair.

    The P0 contract is intentionally conservative: use RGBA alpha as the
    primary foreground source, fall back to an existing mask for legacy opaque
    captures, then report validity separately from visual error metrics.
    """

    if np is None:
        return {
            "version": "research_metrics_p0_v1",
            "status": "unavailable",
            "reason": "numpy not installed",
        }

    ref_features = _reference_features(reference, reference_cache_key)
    ref = ref_features.get("rgba") if ref_features else None
    cand = _to_rgba_float(candidate)
    if ref is None or cand is None:
        return {
            "version": "research_metrics_p0_v1",
            "status": "unavailable",
            "reason": "could not convert images to RGBA arrays",
        }
    if ref.shape != cand.shape:
        return {
            "version": "research_metrics_p0_v1",
            "status": "unavailable",
            "reason": f"shape mismatch: ref={ref.shape}, candidate={cand.shape}",
        }

    masks = _build_masks(ref[..., 3], cand[..., 3], explicit_mask=explicit_mask, fallback_mask=fallback_mask)
    core_mask = masks["core_mask"]
    full_mask = masks["full_mask"]
    validity = _build_validity(masks)
    if int(core_mask.sum()) <= 0:
        return {
            "version": "research_metrics_p0_v1",
            "status": "low_signal",
            "mask_source": masks["source"],
            "validity": validity,
            "score": None,
            "loss": None,
            "notes": ["core_mask has no pixels; visual metrics skipped"],
        }

    ref_rgb = ref_features["rgb"]
    cand_rgb = cand[..., :3]
    cand_lab = _rgb_to_lab(cand_rgb)
    cand_y = _linear_luminance(cand_rgb)
    delta_e = _delta_e_ciede2000(ref_features["lab"], cand_lab)
    color = _color_metrics(ref_rgb, cand_rgb, core_mask, ref_lab=ref_features["lab"], cand_lab=cand_lab, delta_e=delta_e)
    luminance = _luminance_metrics(ref_rgb, cand_rgb, core_mask, ref_y=ref_features["luminance"], cand_y=cand_y)
    structure = _structure_metrics(ref_rgb, cand_rgb, core_mask, ref_y=ref_features["luminance"], cand_y=cand_y)
    highlight = _highlight_metrics(ref_rgb, cand_rgb, core_mask, ref_y=ref_features["luminance"], cand_y=cand_y, delta_e=delta_e)
    detail = _detail_metrics(ref_rgb, cand_rgb, core_mask, ref_y=ref_features["luminance"], cand_y=cand_y)
    perceptual = (
        _perceptual_optional_metrics(ref_rgb, cand_rgb, core_mask, ref_y=ref_features["luminance"], cand_y=cand_y)
        if compute_perceptual_optional
        else _perceptual_optional_skipped()
    )
    loss_payload = _guidance_loss(color, luminance, structure, highlight, detail, validity)

    return {
        "version": "research_metrics_p0_v1",
        "status": "ok",
        "mask_source": masks["source"],
        "validity": validity,
        "masks": {
            "core_pixels": int(core_mask.sum()),
            "full_pixels": int(full_mask.sum()),
            "edge_pixels": int(masks["edge_mask"].sum()),
            "image_pixels": int(core_mask.shape[0] * core_mask.shape[1]),
            "core_ratio": _safe_ratio(float(core_mask.sum()), float(core_mask.size)),
            "full_ratio": _safe_ratio(float(full_mask.sum()), float(full_mask.size)),
        },
        "scientific": {
            "color_accuracy": color,
            "luminance_structure": {
                **luminance,
                **structure,
            },
            "highlight_reflection": highlight,
            "detail_texture": detail,
            "perceptual_optional": perceptual,
        },
        "loss": loss_payload["loss"],
        "score": loss_payload["score"],
        "components": loss_payload["components"],
        "weights": loss_payload["weights"],
        "guidance": loss_payload["guidance"],
        "acceptance_thresholds": loss_payload["acceptance_thresholds"],
        "notes": loss_payload["notes"],
    }


def aggregate_research_metrics(view_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-view P0 metrics with mean + p90 + max loss."""

    passed_items = [
        item
        for item in view_metrics
        if isinstance(item, dict)
        and item.get("status") == "ok"
        and isinstance(item.get("validity"), dict)
        and item["validity"].get("passed")
        and _finite_float(item.get("loss")) is not None
    ]
    all_ok_items = [
        item
        for item in view_metrics
        if isinstance(item, dict) and item.get("status") == "ok" and _finite_float(item.get("loss")) is not None
    ]
    scored_items = all_ok_items
    losses = [_finite_float(item.get("loss")) for item in scored_items]
    losses = [value for value in losses if value is not None]
    if not losses:
        return {
            "version": "research_metrics_p0_v1",
            "status": "pending",
            "valid_view_count": 0,
            "view_count": len(view_metrics),
            "loss": None,
            "score": None,
            "reason": "no valid research metrics",
        }

    mean_loss = _mean(losses)
    p90_loss = _percentile(losses, 90.0)
    max_loss = max(losses)
    final_loss = _clamp01(0.65 * mean_loss + 0.20 * p90_loss + 0.15 * max_loss)
    worst_index = max(range(len(scored_items)), key=lambda idx: _finite_float(scored_items[idx].get("loss")) or -1.0)
    invalid_count = max(0, len(view_metrics) - len(passed_items))
    scored_invalid_count = sum(
        1
        for item in scored_items
        if not (isinstance(item.get("validity"), dict) and item["validity"].get("passed"))
    )
    validity = _aggregate_validity(all_ok_items, passed_count=len(passed_items), view_count=len(view_metrics))
    return {
        "version": "research_metrics_p0_v1",
        "status": "ok" if invalid_count == 0 else "ok_with_invalid_views",
        "view_count": len(view_metrics),
        "valid_view_count": len(passed_items),
        "invalid_view_count": invalid_count,
        "scored_view_count": len(scored_items),
        "scored_invalid_view_count": scored_invalid_count,
        "score_uses_invalid_views": scored_invalid_count > 0,
        "invalid_view_policy": "validity_failed_views_are_penalized_and_kept_in_aggregation",
        "loss": final_loss,
        "score": 100.0 * (1.0 - final_loss),
        "mean_loss": mean_loss,
        "p90_loss": p90_loss,
        "max_loss": max_loss,
        "worst_view_index": worst_index,
        "formula": "guidance: 0.65*mean_loss + 0.20*p90_loss + 0.15*max_loss",
        "validity": validity,
        "masks": _aggregate_masks(all_ok_items),
        "components": _aggregate_mean_section(scored_items, "components"),
        "weights": _aggregate_mean_section(scored_items, "weights"),
        "guidance": _aggregate_guidance(scored_items, final_loss, mean_loss, p90_loss, max_loss),
        "acceptance_thresholds": _aggregate_acceptance_thresholds(scored_items),
        "aggregated_scientific": _aggregate_scientific(scored_items),
    }


def _to_rgba_float(image: Any) -> Any:
    if np is None:
        return None
    if hasattr(image, "convert"):
        arr = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
        return arr
    if hasattr(image, "shape"):
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return None
        arr = arr.astype(np.float32)
        if arr.max(initial=0.0) > 1.0:
            arr = arr / 255.0
        if arr.shape[2] == 3:
            alpha = np.ones(arr.shape[:2] + (1,), dtype=np.float32)
            arr = np.concatenate([arr[..., :3], alpha], axis=2)
        return arr[..., :4]
    return None


def _reference_features(image: Any, cache_key: str | None) -> dict[str, Any] | None:
    if cache_key:
        cached = _REFERENCE_FEATURE_CACHE.get(cache_key)
        if cached is not None:
            return cached
    rgba = _to_rgba_float(image)
    if rgba is None:
        return None
    rgb = rgba[..., :3]
    features = {
        "rgba": rgba,
        "rgb": rgb,
        "lab": _rgb_to_lab(rgb),
        "luminance": _linear_luminance(rgb),
    }
    if cache_key:
        _REFERENCE_FEATURE_CACHE[cache_key] = features
        if len(_REFERENCE_FEATURE_CACHE) > 64:
            oldest_key = next(iter(_REFERENCE_FEATURE_CACHE))
            _REFERENCE_FEATURE_CACHE.pop(oldest_key, None)
    return features


def _to_mask_array(mask: Any, shape: tuple[int, int]) -> Any:
    if np is None or mask is None:
        return None
    if hasattr(mask, "convert"):
        arr = np.asarray(mask.convert("L"), dtype=np.float32) / 255.0
    else:
        arr = np.asarray(mask, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[..., 0]
        if arr.max(initial=0.0) > 1.0:
            arr = arr / 255.0
    if arr.shape[:2] != shape:
        return None
    return arr


def _build_masks(ref_alpha: Any, cand_alpha: Any, *, explicit_mask: Any, fallback_mask: Any) -> dict[str, Any]:
    h, w = ref_alpha.shape[:2]
    alpha_has_signal = bool((ref_alpha < 0.999).any() or (cand_alpha < 0.999).any())
    if alpha_has_signal:
        ref_full = ref_alpha > 0.05
        cand_full = cand_alpha > 0.05
        full_mask = ref_full | cand_full
        core_mask = (ref_alpha > 0.95) & (cand_alpha > 0.95)
        source = "alpha"
    else:
        mask_arr = _to_mask_array(explicit_mask, (h, w))
        source = "explicit_mask"
        if mask_arr is None:
            mask_arr = _to_mask_array(fallback_mask, (h, w))
            source = "fallback_mask" if mask_arr is not None else "full_image"
        if mask_arr is None:
            core_mask = np.ones((h, w), dtype=bool)
            full_mask = np.ones((h, w), dtype=bool)
        else:
            core_mask = mask_arr > 0.50
            full_mask = mask_arr > 0.05
    edge_mask = full_mask & ~core_mask
    ref_full = ref_alpha > 0.05 if alpha_has_signal else full_mask
    cand_full = cand_alpha > 0.05 if alpha_has_signal else full_mask
    return {
        "source": source,
        "core_mask": core_mask,
        "full_mask": full_mask,
        "edge_mask": edge_mask,
        "reference_full_mask": ref_full,
        "candidate_full_mask": cand_full,
    }


def _build_validity(masks: dict[str, Any]) -> dict[str, Any]:
    ref_mask = masks["reference_full_mask"]
    cand_mask = masks["candidate_full_mask"]
    union = ref_mask | cand_mask
    intersection = ref_mask & cand_mask
    mask_iou = _safe_ratio(float(intersection.sum()), float(union.sum()))
    ref_bbox = _bbox(ref_mask)
    cand_bbox = _bbox(cand_mask)
    h, w = ref_mask.shape[:2]
    center_error_px = None
    center_error_norm = None
    scale_error = None
    if ref_bbox is not None and cand_bbox is not None:
        rcx, rcy, rbw, rbh = _bbox_features(ref_bbox)
        ccx, ccy, cbw, cbh = _bbox_features(cand_bbox)
        center_error_px = math.hypot(ccx - rcx, ccy - rcy)
        center_error_norm = center_error_px / max(float(max(w, h)), 1.0)
        scale_error = 0.5 * (abs(cbw / max(rbw, 1.0) - 1.0) + abs(cbh / max(rbh, 1.0) - 1.0))
    foreground_ratio_ref = _safe_ratio(float(ref_mask.sum()), float(ref_mask.size))
    foreground_ratio_candidate = _safe_ratio(float(cand_mask.sum()), float(cand_mask.size))
    reasons: list[str] = []
    if union.sum() <= 0:
        reasons.append("empty foreground")
    if mask_iou < 0.990:
        reasons.append("mask_iou below 0.990")
    if center_error_norm is not None and center_error_norm > 0.020:
        reasons.append("bbox center error above 2% image size")
    if scale_error is not None and scale_error > 0.050:
        reasons.append("bbox scale error above 5%")
    return {
        "passed": not reasons,
        "mask_iou": mask_iou,
        "bbox_center_error_px": center_error_px,
        "bbox_center_error_norm": center_error_norm,
        "bbox_scale_error": scale_error,
        "reference_bbox": list(ref_bbox) if ref_bbox else None,
        "candidate_bbox": list(cand_bbox) if cand_bbox else None,
        "reference_foreground_ratio": foreground_ratio_ref,
        "candidate_foreground_ratio": foreground_ratio_candidate,
        "reasons": reasons,
        "thresholds": {
            "mask_iou_min": 0.990,
            "bbox_center_error_norm_max": 0.020,
            "bbox_scale_error_max": 0.050,
        },
    }


def _color_metrics(
    ref_rgb: Any,
    cand_rgb: Any,
    mask: Any,
    *,
    ref_lab: Any = None,
    cand_lab: Any = None,
    delta_e: Any = None,
) -> dict[str, Any]:
    ref_lab = ref_lab if ref_lab is not None else _rgb_to_lab(ref_rgb)
    cand_lab = cand_lab if cand_lab is not None else _rgb_to_lab(cand_rgb)
    delta = delta_e if delta_e is not None else _delta_e_ciede2000(ref_lab, cand_lab)
    values = delta[mask]
    rgb_bias = (cand_rgb[mask] - ref_rgb[mask]).mean(axis=0)
    lab_bias = (cand_lab[mask] - ref_lab[mask]).mean(axis=0)
    return {
        "mean_deltaE00": float(values.mean()),
        "p95_deltaE00": float(np.percentile(values, 95)),
        "median_deltaE00": float(np.percentile(values, 50)),
        "max_deltaE00": float(values.max(initial=0.0)),
        "rgb_bias_candidate_minus_reference": [float(v) for v in rgb_bias],
        "lab_bias_candidate_minus_reference": [float(v) for v in lab_bias],
    }


def _luminance_metrics(ref_rgb: Any, cand_rgb: Any, mask: Any, *, ref_y: Any = None, cand_y: Any = None) -> dict[str, Any]:
    ref_y = ref_y if ref_y is not None else _linear_luminance(ref_rgb)
    cand_y = cand_y if cand_y is not None else _linear_luminance(cand_rgb)
    diff = cand_y[mask] - ref_y[mask]
    return {
        "luminance_mae": float(np.abs(diff).mean()),
        "luminance_bias": float(diff.mean()),
        "p95_luminance_abs_error": float(np.percentile(np.abs(diff), 95)),
    }


def _structure_metrics(ref_rgb: Any, cand_rgb: Any, mask: Any, *, ref_y: Any = None, cand_y: Any = None) -> dict[str, Any]:
    try:
        from skimage.metrics import structural_similarity
    except ImportError:
        return {
            "ssim_l": None,
            "ssim_l_status": "unavailable",
            "ssim_l_notes": ["scikit-image not installed"],
        }
    ref_y = ref_y if ref_y is not None else _linear_luminance(ref_rgb)
    cand_y = cand_y if cand_y is not None else _linear_luminance(cand_rgb)
    h, w = ref_y.shape[:2]
    win = min(7, h, w)
    if win % 2 == 0:
        win = max(3, win - 1)
    try:
        full_score, full_map = structural_similarity(
            ref_y,
            cand_y,
            data_range=1.0,
            win_size=win,
            full=True,
        )
    except ValueError as exc:
        return {
            "ssim_l": None,
            "ssim_l_status": "unavailable",
            "ssim_l_notes": [f"ssim_l failed: {exc}"],
        }
    weight_sum = float(mask.sum())
    if weight_sum <= 0.0:
        masked_score = float(full_score)
        notes = ["core_mask is empty; used unmasked SSIM-L"]
    else:
        masked_score = float((full_map * mask.astype(np.float32)).sum() / weight_sum)
        notes = []
    return {
        "ssim_l": masked_score,
        "ssim_l_unmasked": float(full_score),
        "ssim_l_status": "ok",
        "ssim_l_win_size": win,
        "ssim_l_notes": notes,
    }


def _highlight_metrics(
    ref_rgb: Any,
    cand_rgb: Any,
    mask: Any,
    *,
    ref_y: Any = None,
    cand_y: Any = None,
    delta_e: Any = None,
) -> dict[str, Any]:
    ref_y = ref_y if ref_y is not None else _linear_luminance(ref_rgb)
    cand_y = cand_y if cand_y is not None else _linear_luminance(cand_rgb)
    ref_values = ref_y[mask]
    if ref_values.size <= 0:
        return {"enabled": False, "status": "not_applicable", "reason": "empty core mask"}
    threshold = float(np.percentile(ref_values, 95))
    contrast = float(np.percentile(ref_values, 99) - np.percentile(ref_values, 80))
    highlight_mask = mask & (ref_y >= threshold)
    area_ratio = _safe_ratio(float(highlight_mask.sum()), float(mask.sum()))
    enabled = contrast > 0.08 and 0.002 <= area_ratio <= 0.35 and int(highlight_mask.sum()) >= 16
    if not enabled:
        return {
            "enabled": False,
            "status": "not_applicable",
            "threshold": threshold,
            "contrast_p99_p80": contrast,
            "area_ratio": area_ratio,
            "reason": "reference highlight region is too weak, too small, or too large",
        }

    delta = delta_e if delta_e is not None else _delta_e_ciede2000(_rgb_to_lab(ref_rgb), _rgb_to_lab(cand_rgb))
    ref_area = float(highlight_mask.sum())
    cand_threshold = threshold
    cand_highlight_mask = mask & (cand_y >= cand_threshold)
    cand_area = float(cand_highlight_mask.sum())
    y_diff = np.abs(cand_y[highlight_mask] - ref_y[highlight_mask])
    peak_ref = float(np.percentile(ref_y[highlight_mask], 99))
    peak_cand = float(np.percentile(cand_y[highlight_mask], 99))
    return {
        "enabled": True,
        "status": "ok",
        "threshold": threshold,
        "contrast_p99_p80": contrast,
        "area_ratio": area_ratio,
        "highlight_deltaE00": float(delta[highlight_mask].mean()),
        "highlight_luminance_mae": float(y_diff.mean()),
        "highlight_area_error": abs(cand_area - ref_area) / max(ref_area, 1.0),
        "peak_luminance_error": abs(peak_cand - peak_ref),
    }


def _detail_metrics(ref_rgb: Any, cand_rgb: Any, mask: Any, *, ref_y: Any = None, cand_y: Any = None) -> dict[str, Any]:
    ref_y = ref_y if ref_y is not None else _linear_luminance(ref_rgb)
    cand_y = cand_y if cand_y is not None else _linear_luminance(cand_rgb)
    interior = _erode_mask(mask, iterations=1)
    if int(interior.sum()) <= 0:
        interior = mask
    ref_grad = _gradient_magnitude(ref_y)
    cand_grad = _gradient_magnitude(cand_y)
    ref_lap = _laplacian(ref_y)
    cand_lap = _laplacian(cand_y)
    grad_loss = float(np.abs(ref_grad[interior] - cand_grad[interior]).mean()) if int(interior.sum()) > 0 else None
    lap_loss = float(np.abs(ref_lap[interior] - cand_lap[interior]).mean()) if int(interior.sum()) > 0 else None
    return {
        "enabled": grad_loss is not None and lap_loss is not None,
        "status": "ok" if grad_loss is not None and lap_loss is not None else "not_applicable",
        "gradient_loss": grad_loss,
        "laplacian_loss": lap_loss,
        "mask_pixels": int(interior.sum()),
    }


def _perceptual_optional_metrics(ref_rgb: Any, cand_rgb: Any, mask: Any, *, ref_y: Any = None, cand_y: Any = None) -> dict[str, Any]:
    ref_y = ref_y if ref_y is not None else _linear_luminance(ref_rgb)
    cand_y = cand_y if cand_y is not None else _linear_luminance(cand_rgb)
    rgb_abs = np.abs(ref_rgb - cand_rgb).mean(axis=2)
    y_abs = np.abs(ref_y - cand_y)
    combined = 0.65 * y_abs + 0.35 * rgb_abs
    if int(mask.sum()) > 0:
        flip_like = float(combined[mask].mean())
        flip_like_p95 = float(np.percentile(combined[mask], 95))
    else:
        flip_like = None
        flip_like_p95 = None
    lpips_value, lpips_status, lpips_notes = _lpips_metric(ref_rgb, cand_rgb, mask)
    dists_value, dists_status, dists_notes = _dists_metric(ref_rgb, cand_rgb, mask)
    return {
        "status": "ok",
        "enters_loss": False,
        "flip_like_error": flip_like,
        "flip_like_p95": flip_like_p95,
        "lpips": lpips_value,
        "lpips_status": lpips_status,
        "lpips_notes": lpips_notes,
        "dists": dists_value,
        "dists_status": dists_status,
        "dists_notes": dists_notes,
    }


def _perceptual_optional_skipped() -> dict[str, Any]:
    return {
        "status": "skipped",
        "enters_loss": False,
        "reason": "disabled for this optimization iteration",
        "flip_like_error": None,
        "flip_like_p95": None,
        "lpips": None,
        "lpips_status": "skipped",
        "lpips_notes": ["P2 perceptual metrics are evaluated at the configured interval only"],
        "dists": None,
        "dists_status": "skipped",
        "dists_notes": ["P2 perceptual metrics are evaluated at the configured interval only"],
    }


def _lpips_metric(ref_rgb: Any, cand_rgb: Any, mask: Any) -> tuple[float | None, str, list[str]]:
    try:
        torch, _lpips, _ = _load_perceptual_dependencies()
        tensor_ref, tensor_cand, notes = _perceptual_tensors(ref_rgb, cand_rgb, mask, torch)
        model = _PERCEPTUAL_CACHE.get("lpips")
        if model is None:
            model = _lpips.LPIPS(net="alex", verbose=False)
            model.eval()
            _PERCEPTUAL_CACHE["lpips"] = model
        with torch.no_grad():
            score = model(tensor_ref * 2.0 - 1.0, tensor_cand * 2.0 - 1.0)
        return float(score.reshape(-1)[0].item()), "ok", notes
    except Exception as exc:  # pragma: no cover - dependency/model/environment dependent
        return None, "unavailable", [f"LPIPS unavailable: {exc}"]


def _dists_metric(ref_rgb: Any, cand_rgb: Any, mask: Any) -> tuple[float | None, str, list[str]]:
    try:
        torch, _, dists_module = _load_perceptual_dependencies()
        tensor_ref, tensor_cand, notes = _perceptual_tensors(ref_rgb, cand_rgb, mask, torch)
        model = _PERCEPTUAL_CACHE.get("dists")
        if model is None:
            old_prefix = sys.prefix
            try:
                # DISTS-pytorch 0.1 ships weights.pt inside the package, but its
                # loader looks under sys.prefix. Point it at the package only for
                # model construction so the installed weights are used.
                sys.prefix = str(Path(dists_module.__file__).resolve().parent)
                model = dists_module.DISTS()
            finally:
                sys.prefix = old_prefix
            model.eval()
            _PERCEPTUAL_CACHE["dists"] = model
        with torch.no_grad():
            score = model(tensor_ref, tensor_cand)
        return float(score.reshape(-1)[0].item()), "ok", notes
    except Exception as exc:  # pragma: no cover - dependency/model/environment dependent
        return None, "unavailable", [f"DISTS unavailable: {exc}"]


def _load_perceptual_dependencies() -> tuple[Any, Any, Any]:
    cached = _PERCEPTUAL_CACHE.get("deps")
    if cached is not None:
        return cached

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import torch  # type: ignore[import-not-found]
    import lpips  # type: ignore[import-not-found]
    import DISTS_pytorch  # type: ignore[import-not-found]

    deps = (torch, lpips, DISTS_pytorch)
    _PERCEPTUAL_CACHE["deps"] = deps
    return deps


def _perceptual_tensors(ref_rgb: Any, cand_rgb: Any, mask: Any, torch: Any) -> tuple[Any, Any, list[str]]:
    if int(mask.sum()) <= 0:
        raise ValueError("core_mask has no pixels")

    bbox = _bbox(mask)
    if bbox is None:
        raise ValueError("core_mask has no bbox")
    x0, y0, x1, y1 = bbox
    height, width = mask.shape[:2]
    pad = max(4, int(0.05 * max(x1 - x0 + 1, y1 - y0 + 1)))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(width - 1, x1 + pad)
    y1 = min(height - 1, y1 + pad)

    crop_mask = mask[y0 : y1 + 1, x0 : x1 + 1].astype(np.float32)[..., None]
    ref_crop = np.clip(ref_rgb[y0 : y1 + 1, x0 : x1 + 1] * crop_mask, 0.0, 1.0)
    cand_crop = np.clip(cand_rgb[y0 : y1 + 1, x0 : x1 + 1] * crop_mask, 0.0, 1.0)
    ref_tensor = torch.from_numpy(ref_crop.transpose(2, 0, 1)).float().unsqueeze(0)
    cand_tensor = torch.from_numpy(cand_crop.transpose(2, 0, 1)).float().unsqueeze(0)

    notes: list[str] = ["computed on core_mask foreground crop; does not enter research_loss"]
    _, _, crop_h, crop_w = ref_tensor.shape
    long_side = max(crop_h, crop_w)
    short_side = min(crop_h, crop_w)
    scale = 1.0
    if long_side > 256:
        scale = 256.0 / float(long_side)
    if short_side * scale < 64:
        scale = max(scale, 64.0 / float(short_side))
    if not math.isclose(scale, 1.0):
        new_h = max(64, int(round(crop_h * scale)))
        new_w = max(64, int(round(crop_w * scale)))
        ref_tensor = torch.nn.functional.interpolate(ref_tensor, size=(new_h, new_w), mode="bilinear", align_corners=False)
        cand_tensor = torch.nn.functional.interpolate(cand_tensor, size=(new_h, new_w), mode="bilinear", align_corners=False)
        notes.append(f"foreground crop resized from {crop_w}x{crop_h} to {new_w}x{new_h}")
    return ref_tensor, cand_tensor, notes


def _guidance_loss(
    color: dict[str, Any],
    luminance: dict[str, Any],
    structure: dict[str, Any],
    highlight: dict[str, Any],
    detail: dict[str, Any],
    validity: dict[str, Any],
) -> dict[str, Any]:
    components = {
        "color_mean": _soft_saturating_loss(float(color["mean_deltaE00"]), 10.0),
        "color_p95": _soft_saturating_loss(float(color["p95_deltaE00"]), 20.0),
        "luminance_mae": _soft_saturating_loss(float(luminance["luminance_mae"]), 0.20),
        "luminance_bias": _soft_saturating_loss(abs(float(luminance["luminance_bias"])), 0.15),
    }
    scales = {
        "color_mean": {"raw": "mean_deltaE00", "scale": 10.0, "reason": "average ΔE00 half-saturation for clearly visible whole-object color mismatch"},
        "color_p95": {"raw": "p95_deltaE00", "scale": 20.0, "reason": "tail ΔE00 half-saturation; p95 is expected to be larger around highlights, edges, and localized reflections"},
        "luminance_mae": {"raw": "luminance_mae", "scale": 0.20, "reason": "linear luminance half-saturation for large material brightness mismatch"},
        "luminance_bias": {"raw": "abs(luminance_bias)", "scale": 0.15, "reason": "signed luminance bias half-saturation"},
    }
    weights = {
        "color_mean": 0.35,
        "color_p95": 0.15,
        "luminance_mae": 0.20,
        "luminance_bias": 0.10,
    }
    ssim_l = _finite_float(structure.get("ssim_l"))
    notes: list[str] = []
    if ssim_l is not None:
        components["structure_ssim_l"] = _soft_saturating_loss(max(1.0 - ssim_l, 0.0), 0.15)
        weights["structure_ssim_l"] = 0.20
        scales["structure_ssim_l"] = {"raw": "1.0 - ssim_l", "scale": 0.15, "reason": "SSIM-L deficit half-saturation"}
    else:
        notes.append("SSIM-L unavailable; loss weights renormalized over color/luminance components")
    if highlight.get("enabled"):
        h_delta = _finite_float(highlight.get("highlight_deltaE00"))
        h_area = _finite_float(highlight.get("highlight_area_error"))
        h_peak = _finite_float(highlight.get("peak_luminance_error"))
        if h_delta is not None and h_area is not None and h_peak is not None:
            components["highlight"] = (
                0.45 * _soft_saturating_loss(h_delta, 20.0)
                + 0.35 * _soft_saturating_loss(h_area, 0.50)
                + 0.20 * _soft_saturating_loss(h_peak, 0.25)
            )
            weights["highlight"] = 0.12
            scales["highlight"] = {
                "raw": "0.45*highlight_deltaE00 + 0.35*highlight_area_error + 0.20*peak_luminance_error",
                "scales": {
                    "highlight_deltaE00": 20.0,
                    "highlight_area_error": 0.50,
                    "peak_luminance_error": 0.25,
                },
                "reason": "conditional highlight/reflection guidance",
            }
    else:
        notes.append("highlight metric not applicable for this view; loss weights renormalized")
    grad = _finite_float(detail.get("gradient_loss"))
    lap = _finite_float(detail.get("laplacian_loss"))
    if grad is not None and lap is not None:
        components["detail_texture"] = 0.60 * _soft_saturating_loss(grad, 0.25) + 0.40 * _soft_saturating_loss(lap, 0.50)
        weights["detail_texture"] = 0.06
        scales["detail_texture"] = {
            "raw": "0.60*gradient_loss + 0.40*laplacian_loss",
            "scales": {"gradient_loss": 0.25, "laplacian_loss": 0.50},
            "reason": "texture/detail guidance",
        }
    total_weight = sum(weights[key] for key in components)
    raw_loss = sum(components[key] * weights[key] for key in components) / max(total_weight, 1e-8)
    loss = raw_loss
    validity_penalty_applied = False
    if not validity.get("passed"):
        validity_penalty_applied = True
        loss = max(loss, _VALIDITY_FAILED_LOSS_FLOOR)
        notes.append(
            "validity failed; optimizer guidance loss was raised to the validity penalty floor"
        )
    normalized_weights = {key: weights[key] / max(total_weight, 1e-8) for key in components}
    clamped_loss = _clamp01(loss)
    return {
        "loss": clamped_loss,
        "score": 100.0 * (1.0 - clamped_loss),
        "components": components,
        "weights": normalized_weights,
        "guidance": {
            "version": "optimizer_guidance_v1",
            "normalization": "soft_saturating_half_scale",
            "formula": "g(x; s) = x / (x + s)",
            "loss": clamped_loss,
            "score": 100.0 * (1.0 - clamped_loss),
            "raw_loss_before_validity_penalty": _clamp01(raw_loss),
            "validity_penalty_applied": validity_penalty_applied,
            "validity_failed_loss_floor": _VALIDITY_FAILED_LOSS_FLOOR,
            "components": components,
            "weights": normalized_weights,
            "scales": scales,
            "notes": [
                "soft guidance replaces hard-clamped research_loss as the optimization target",
                "raw scientific metrics remain the report/acceptance evidence",
            ],
        },
        "acceptance_thresholds": _acceptance_thresholds(color, luminance, structure, highlight, detail),
        "notes": notes,
    }


def _aggregate_scientific(items: list[dict[str, Any]]) -> dict[str, Any]:
    def pick(path: tuple[str, ...]) -> list[float]:
        values: list[float] = []
        for item in items:
            cur: Any = item
            for key in path:
                cur = cur.get(key) if isinstance(cur, dict) else None
            number = _finite_float(cur)
            if number is not None:
                values.append(number)
        return values

    fields = {
        "mean_deltaE00": ("scientific", "color_accuracy", "mean_deltaE00"),
        "p95_deltaE00": ("scientific", "color_accuracy", "p95_deltaE00"),
        "median_deltaE00": ("scientific", "color_accuracy", "median_deltaE00"),
        "max_deltaE00": ("scientific", "color_accuracy", "max_deltaE00"),
        "luminance_mae": ("scientific", "luminance_structure", "luminance_mae"),
        "luminance_bias": ("scientific", "luminance_structure", "luminance_bias"),
        "p95_luminance_abs_error": ("scientific", "luminance_structure", "p95_luminance_abs_error"),
        "ssim_l": ("scientific", "luminance_structure", "ssim_l"),
        "highlight_deltaE00": ("scientific", "highlight_reflection", "highlight_deltaE00"),
        "highlight_luminance_mae": ("scientific", "highlight_reflection", "highlight_luminance_mae"),
        "highlight_area_error": ("scientific", "highlight_reflection", "highlight_area_error"),
        "peak_luminance_error": ("scientific", "highlight_reflection", "peak_luminance_error"),
        "gradient_loss": ("scientific", "detail_texture", "gradient_loss"),
        "laplacian_loss": ("scientific", "detail_texture", "laplacian_loss"),
        "flip_like_error": ("scientific", "perceptual_optional", "flip_like_error"),
        "flip_like_p95": ("scientific", "perceptual_optional", "flip_like_p95"),
        "lpips": ("scientific", "perceptual_optional", "lpips"),
        "dists": ("scientific", "perceptual_optional", "dists"),
    }
    out: dict[str, Any] = {}
    for name, path in fields.items():
        vals = pick(path)
        if vals:
            out[name] = {
                "mean": _mean(vals),
                "p90": _percentile(vals, 90.0),
                "max": max(vals),
                "min": min(vals),
            }
    vector_fields = {
        "rgb_bias_candidate_minus_reference": ("scientific", "color_accuracy", "rgb_bias_candidate_minus_reference"),
        "lab_bias_candidate_minus_reference": ("scientific", "color_accuracy", "lab_bias_candidate_minus_reference"),
    }
    for name, path in vector_fields.items():
        vals = _pick_vectors(items, path)
        if vals:
            arr = np.asarray(vals, dtype=np.float32)
            out[name] = {
                "mean": [float(v) for v in arr.mean(axis=0)],
                "max_abs": [float(v) for v in np.max(np.abs(arr), axis=0)],
            }
    return out


def _aggregate_guidance(
    items: list[dict[str, Any]],
    final_loss: float,
    mean_loss: float,
    p90_loss: float,
    max_loss: float,
) -> dict[str, Any]:
    first_guidance = next((item.get("guidance") for item in items if isinstance(item.get("guidance"), dict)), {})
    return {
        "version": "optimizer_guidance_v1",
        "normalization": "soft_saturating_half_scale",
        "formula": "g(x; s) = x / (x + s); final_loss = 0.65*mean + 0.20*p90 + 0.15*max",
        "loss": final_loss,
        "score": 100.0 * (1.0 - final_loss),
        "mean_loss": mean_loss,
        "p90_loss": p90_loss,
        "max_loss": max_loss,
        "components": _aggregate_mean_section(items, "components"),
        "weights": _aggregate_mean_section(items, "weights"),
        "scales": first_guidance.get("scales") if isinstance(first_guidance, dict) else {},
        "notes": [
            "This is the optimization guidance score used by fit_score_mode='research'.",
            "It is intentionally not a hard pass/fail acceptance metric.",
        ],
    }


def _aggregate_acceptance_thresholds(items: list[dict[str, Any]]) -> dict[str, Any]:
    thresholds = [item.get("acceptance_thresholds") for item in items if isinstance(item.get("acceptance_thresholds"), dict)]
    if not thresholds:
        return {}
    keys = sorted({str(key) for item in thresholds for key in item})
    out: dict[str, Any] = {}
    for key in keys:
        entries = [item.get(key) for item in thresholds if isinstance(item.get(key), dict)]
        if not entries:
            continue
        pass_values = [entry.get("passed") for entry in entries if isinstance(entry.get("passed"), bool)]
        values = [_finite_float(entry.get("value")) for entry in entries]
        values = [value for value in values if value is not None]
        first = entries[0]
        out[key] = {
            "value_mean": _mean(values) if values else None,
            "threshold": first.get("threshold"),
            "operator": first.get("operator"),
            "passed_view_count": sum(1 for value in pass_values if value),
            "view_count": len(pass_values),
            "passed": bool(pass_values) and all(bool(value) for value in pass_values),
        }
    return out


def _acceptance_thresholds(
    color: dict[str, Any],
    luminance: dict[str, Any],
    structure: dict[str, Any],
    highlight: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    thresholds: dict[str, Any] = {
        "mean_deltaE00": _threshold(float(color["mean_deltaE00"]), "<=", 10.0, "average color difference"),
        "p95_deltaE00": _threshold(float(color["p95_deltaE00"]), "<=", 20.0, "tail color difference"),
        "luminance_mae": _threshold(float(luminance["luminance_mae"]), "<=", 0.20, "foreground luminance MAE"),
        "luminance_bias_abs": _threshold(abs(float(luminance["luminance_bias"])), "<=", 0.15, "absolute luminance bias"),
    }
    ssim_l = _finite_float(structure.get("ssim_l"))
    if ssim_l is not None:
        thresholds["ssim_l"] = _threshold(ssim_l, ">=", 0.85, "luminance structure similarity")
    h_delta = _finite_float(highlight.get("highlight_deltaE00"))
    if highlight.get("enabled") and h_delta is not None:
        thresholds["highlight_deltaE00"] = _threshold(h_delta, "<=", 20.0, "conditional highlight color difference")
    grad = _finite_float(detail.get("gradient_loss"))
    if grad is not None:
        thresholds["gradient_loss"] = _threshold(grad, "<=", 0.25, "detail gradient loss")
    return thresholds


def _threshold(value: float, operator: str, threshold: float, label: str) -> dict[str, Any]:
    passed = value <= threshold if operator == "<=" else value >= threshold
    return {
        "label": label,
        "value": float(value),
        "operator": operator,
        "threshold": float(threshold),
        "passed": bool(passed),
    }


def _pick_vectors(items: list[dict[str, Any]], path: tuple[str, ...]) -> list[list[float]]:
    values: list[list[float]] = []
    for item in items:
        cur: Any = item
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            vector: list[float] = []
            for value in cur:
                number = _finite_float(value)
                if number is not None:
                    vector.append(number)
            if len(vector) == len(cur) and vector:
                values.append(vector)
    return values


def _aggregate_mean_section(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {}
    for item in items:
        section = item.get(key)
        if not isinstance(section, dict):
            continue
        for name, value in section.items():
            number = _finite_float(value)
            if number is not None:
                buckets.setdefault(str(name), []).append(number)
    return {name: _mean(values) for name, values in sorted(buckets.items()) if values}


def _aggregate_validity(items: list[dict[str, Any]], *, passed_count: int, view_count: int) -> dict[str, Any]:
    validities = [
        item.get("validity")
        for item in items
        if isinstance(item.get("validity"), dict)
    ]

    def values(key: str) -> list[float]:
        out: list[float] = []
        for payload in validities:
            number = _finite_float(payload.get(key))
            if number is not None:
                out.append(number)
        return out

    reasons = sorted({
        str(reason)
        for payload in validities
        for reason in (payload.get("reasons") if isinstance(payload.get("reasons"), list) else [])
    })
    mask_iou_values = values("mask_iou")
    center_values = values("bbox_center_error_px")
    scale_values = values("bbox_scale_error")
    return {
        "passed": passed_count == view_count and view_count > 0,
        "passed_view_count": passed_count,
        "failed_view_count": max(0, view_count - passed_count),
        "mask_iou": _mean(mask_iou_values) if mask_iou_values else None,
        "mask_iou_min": min(mask_iou_values) if mask_iou_values else None,
        "bbox_center_error_px": _mean(center_values) if center_values else None,
        "bbox_center_error_px_max": max(center_values) if center_values else None,
        "bbox_scale_error": _mean(scale_values) if scale_values else None,
        "bbox_scale_error_max": max(scale_values) if scale_values else None,
        "reasons": reasons,
    }


def _aggregate_masks(items: list[dict[str, Any]]) -> dict[str, Any]:
    masks = [
        item.get("masks")
        for item in items
        if isinstance(item.get("masks"), dict)
    ]

    def values(key: str) -> list[float]:
        out: list[float] = []
        for payload in masks:
            number = _finite_float(payload.get(key))
            if number is not None:
                out.append(number)
        return out

    core_ratios = values("core_ratio")
    full_ratios = values("full_ratio")
    return {
        "core_ratio": _mean(core_ratios) if core_ratios else None,
        "full_ratio": _mean(full_ratios) if full_ratios else None,
    }


def _rgb_to_lab(rgb: Any) -> Any:
    linear = _srgb_to_linear(rgb)
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = np.tensordot(linear, matrix.T, axes=1)
    white = np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)
    xyz = xyz / white
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    l = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([l, a, b], axis=-1)


def _delta_e_ciede2000(lab1: Any, lab2: Any) -> Any:
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    c1 = np.sqrt(a1 * a1 + b1 * b1)
    c2 = np.sqrt(a2 * a2 + b2 * b2)
    c_bar = (c1 + c2) * 0.5
    c_bar7 = c_bar ** 7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0 ** 7 + 1e-12)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.sqrt(a1p * a1p + b1 * b1)
    c2p = np.sqrt(a2p * a2p + b2 * b2)
    h1p = (np.degrees(np.arctan2(b1, a1p)) + 360.0) % 360.0
    h2p = (np.degrees(np.arctan2(b2, a2p)) + 360.0) % 360.0
    dlp = l2 - l1
    dcp = c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, dh)
    dh = np.where(dh < -180.0, dh + 360.0, dh)
    dhp = np.where((c1p * c2p) == 0.0, 0.0, dh)
    dh_term = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) * 0.5)
    l_bar = (l1 + l2) * 0.5
    cp_bar = (c1p + c2p) * 0.5
    h_sum = h1p + h2p
    h_diff = np.abs(h1p - h2p)
    hp_bar = np.where(
        (c1p * c2p) == 0.0,
        h_sum,
        np.where(h_diff <= 180.0, h_sum * 0.5, np.where(h_sum < 360.0, (h_sum + 360.0) * 0.5, (h_sum - 360.0) * 0.5)),
    )
    t = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )
    delta_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    cp_bar7 = cp_bar ** 7
    rc = 2.0 * np.sqrt(cp_bar7 / (cp_bar7 + 25.0 ** 7 + 1e-12))
    sl = 1.0 + (0.015 * ((l_bar - 50.0) ** 2)) / np.sqrt(20.0 + ((l_bar - 50.0) ** 2))
    sc = 1.0 + 0.045 * cp_bar
    sh = 1.0 + 0.015 * cp_bar * t
    rt = -np.sin(np.radians(2.0 * delta_theta)) * rc
    return np.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dh_term / sh) ** 2
        + rt * (dcp / sc) * (dh_term / sh)
    )


def _linear_luminance(rgb: Any) -> Any:
    linear = _srgb_to_linear(rgb)
    return linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722


def _srgb_to_linear(rgb: Any) -> Any:
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _gradient_magnitude(values: Any) -> Any:
    gy, gx = np.gradient(values.astype(np.float32))
    return np.sqrt(gx * gx + gy * gy)


def _laplacian(values: Any) -> Any:
    arr = values.astype(np.float32)
    padded = np.pad(arr, 1, mode="edge")
    return (
        padded[1:-1, :-2]
        + padded[1:-1, 2:]
        + padded[:-2, 1:-1]
        + padded[2:, 1:-1]
        - 4.0 * padded[1:-1, 1:-1]
    )


def _erode_mask(mask: Any, *, iterations: int = 1) -> Any:
    out = mask.astype(bool)
    for _ in range(max(0, iterations)):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        out = (
            padded[1:-1, 1:-1]
            & padded[:-2, 1:-1]
            & padded[2:, 1:-1]
            & padded[1:-1, :-2]
            & padded[1:-1, 2:]
        )
    return out


def _bbox(mask: Any) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _bbox_features(bbox: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    width = max(float(x1 - x0 + 1), 1.0)
    height = max(float(y1 - y0 + 1), 1.0)
    return x0 + width * 0.5, y0 + height * 0.5, width, height


def _mean(values: list[float]) -> float:
    return float(sum(values) / max(len(values), 1))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.inf
    return float(np.percentile(np.asarray(values, dtype=np.float32), percentile))


def _finite_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator <= 0.0 else float(numerator / denominator)


def _soft_saturating_loss(value: float, scale: float) -> float:
    if not math.isfinite(value):
        return 1.0
    value = max(float(value), 0.0)
    scale = max(float(scale), 1e-8)
    return value / (value + scale)


def _clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 1.0
    return max(0.0, min(1.0, float(value)))
