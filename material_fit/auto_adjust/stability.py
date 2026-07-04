"""Score stability helpers for repeated render validation."""

from __future__ import annotations

import copy
import math
from typing import Any


_STABILITY_SCORE_POLICIES = {
    "min",
    "median",
    "mean",
    "lower_quartile",
    "dominant_mode_lower_quartile",
    "canonical_mode_lower_quartile",
}


def normalize_stability_score_policy(policy: object, *, default: str = "min") -> str:
    normalized = str(policy or default or "min").strip().lower()
    aliases = {
        "conservative": "min",
        "conservative_min": "min",
        "worst": "min",
        "minimum": "min",
        "p50": "median",
        "middle": "median",
        "avg": "mean",
        "average": "mean",
        "p25": "lower_quartile",
        "q25": "lower_quartile",
        "lower": "lower_quartile",
        "low": "lower_quartile",
        "lower_quantile": "lower_quartile",
        "lower_quartile": "lower_quartile",
        "mode_p25": "dominant_mode_lower_quartile",
        "mode_q25": "dominant_mode_lower_quartile",
        "mode_lower": "dominant_mode_lower_quartile",
        "mode_lower_quartile": "dominant_mode_lower_quartile",
        "modal_lower_quartile": "dominant_mode_lower_quartile",
        "dominant_mode_lower_quartile": "dominant_mode_lower_quartile",
        "foreground_mode_lower_quartile": "dominant_mode_lower_quartile",
        "canonical_p25": "canonical_mode_lower_quartile",
        "canonical_q25": "canonical_mode_lower_quartile",
        "canonical_lower": "canonical_mode_lower_quartile",
        "canonical_mode_p25": "canonical_mode_lower_quartile",
        "canonical_mode_q25": "canonical_mode_lower_quartile",
        "canonical_mode_lower": "canonical_mode_lower_quartile",
        "canonical_mode_lower_quartile": "canonical_mode_lower_quartile",
        "selected_mode_lower_quartile": "canonical_mode_lower_quartile",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in _STABILITY_SCORE_POLICIES:
        return normalized
    fallback = aliases.get(str(default or "min").strip().lower(), str(default or "min").strip().lower())
    return fallback if fallback in _STABILITY_SCORE_POLICIES else "min"


def select_stability_policy_value(
    summary: dict[str, Any],
    prefix: str,
    policy: object,
    *,
    allow_conservative_fallback: bool = True,
) -> float | None:
    normalized_policy = normalize_stability_score_policy(policy)
    key_prefix = str(prefix)
    if normalized_policy == "canonical_mode_lower_quartile":
        value = _canonical_mode_policy_value(summary, key_prefix, "lower_quartile")
        if value is not None:
            return value
    if normalized_policy == "dominant_mode_lower_quartile":
        value = _dominant_mode_policy_value(summary, key_prefix, "lower_quartile")
        if value is not None:
            return value
    if summary.get("foreground_stable") is False:
        value = _conservative_policy_value(summary, key_prefix)
        if value is not None:
            return value
    if normalized_policy == "lower_quartile":
        value = _lower_quartile_policy_value(summary, key_prefix)
        if value is not None:
            return value
        value = _optional_float(summary.get(f"{key_prefix}_lower_quartile"))
        if value is not None:
            return value
    if normalized_policy == "median":
        value = _optional_float(summary.get(f"{key_prefix}_median"))
        if value is not None:
            return value
    if normalized_policy == "mean":
        value = _optional_float(summary.get(f"{key_prefix}_mean"))
        if value is not None:
            return value
    if key_prefix == "fit_score":
        return _optional_float(summary.get("conservative_fit_score", summary.get("fit_score_min")))
    if not allow_conservative_fallback:
        return None
    return _optional_float(summary.get("conservative_diff_score", summary.get("diff_score_max")))


def summarize_fresh_oracle_records(
    fresh_summary: dict[str, Any],
    *,
    score_drift_threshold: float = 0.005,
    foreground_abs_threshold: float = 128.0,
    foreground_ratio_threshold: float = 0.005,
    canonical_foreground_signature: object = None,
    foreground_bucket_size: float = 128.0,
    canonical_foreground_bucket_tolerance: float = 128.0,
) -> dict[str, Any] | None:
    """Summarize per-attempt browser_score records from fresh oracle validation."""

    raw_records = fresh_summary.get("records") if isinstance(fresh_summary, dict) else None
    if not isinstance(raw_records, list):
        return None
    samples: list[dict[str, Any]] = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict):
            continue
        sample = _fresh_oracle_record_sample(record, fallback_index=index)
        if sample is not None:
            samples.append(sample)
    if not samples:
        return None
    return summarize_stability_samples(
        samples,
        score_drift_threshold=score_drift_threshold,
        foreground_abs_threshold=foreground_abs_threshold,
        foreground_ratio_threshold=foreground_ratio_threshold,
        canonical_foreground_signature=canonical_foreground_signature,
        foreground_bucket_size=foreground_bucket_size,
        canonical_foreground_bucket_tolerance=canonical_foreground_bucket_tolerance,
    )


def summarize_stability_samples(
    samples: list[dict[str, Any]],
    *,
    score_drift_threshold: float = 0.005,
    foreground_abs_threshold: float = 128.0,
    foreground_ratio_threshold: float = 0.005,
    canonical_foreground_signature: object = None,
    foreground_bucket_size: float = 128.0,
    canonical_foreground_bucket_tolerance: float = 128.0,
) -> dict[str, Any]:
    """Summarize repeated renders of the same candidate parameters.

    The returned conservative score is the minimum fit score across repeats.
    This intentionally penalizes one-off high scores from unstable captures.
    """

    fit_scores = [
        value
        for value in (_optional_float(sample.get("fit_score")) for sample in samples)
        if value is not None
    ]
    diff_scores = [
        value
        for value in (_optional_float(sample.get("diff_score")) for sample in samples)
        if value is not None
    ]
    score_spread = _spread(fit_scores)
    view_stats = _view_stats(samples)
    foreground_modes = _foreground_modes(samples, bucket_size=foreground_bucket_size)
    dominant_foreground_mode = foreground_modes[0] if foreground_modes else None
    canonical_signature = _normalize_foreground_signature(
        canonical_foreground_signature,
        bucket_size=foreground_bucket_size,
    )
    canonical_foreground_mode = _select_canonical_foreground_mode(
        foreground_modes,
        canonical_signature,
        max_bucket_distance=canonical_foreground_bucket_tolerance,
    )
    worst_view = max(
        view_stats,
        key=lambda item: _optional_float(item.get("foreground_weight_sum_spread")) or -math.inf,
        default=None,
    )
    foreground_spread = (
        _optional_float(worst_view.get("foreground_weight_sum_spread"))
        if isinstance(worst_view, dict)
        else None
    )
    foreground_ratio = (
        _optional_float(worst_view.get("foreground_weight_sum_spread_ratio"))
        if isinstance(worst_view, dict)
        else None
    )
    score_stable = bool(score_spread is None or score_spread <= float(score_drift_threshold))
    foreground_stable = not (
        foreground_spread is not None
        and foreground_ratio is not None
        and foreground_spread > float(foreground_abs_threshold)
        and foreground_ratio > float(foreground_ratio_threshold)
    )
    return {
        "stable": bool(score_stable and foreground_stable),
        "sample_count": len(samples),
        "score_stable": score_stable,
        "foreground_stable": foreground_stable,
        "fit_score_min": _round_float(min(fit_scores) if fit_scores else None),
        "fit_score_max": _round_float(max(fit_scores) if fit_scores else None),
        "fit_score_spread": _round_float(score_spread),
        "conservative_fit_score": _round_float(min(fit_scores) if fit_scores else None),
        "conservative_diff_score": _round_float(max(diff_scores) if diff_scores else None),
        "worst_foreground_view_id": worst_view.get("view_id") if isinstance(worst_view, dict) else None,
        "worst_foreground_weight_sum_spread": _round_float(foreground_spread),
        "worst_foreground_weight_sum_spread_ratio": _round_float(foreground_ratio),
        "thresholds": {
            "score_drift_threshold": float(score_drift_threshold),
            "foreground_abs_threshold": float(foreground_abs_threshold),
            "foreground_ratio_threshold": float(foreground_ratio_threshold),
        },
        "samples": copy.deepcopy(samples),
        "view_stats": view_stats,
        "foreground_modes": foreground_modes,
        "dominant_foreground_mode": dominant_foreground_mode,
        "canonical_foreground_signature": _signature_payload(canonical_signature),
        "canonical_foreground_mode": canonical_foreground_mode,
    }


def browser_score_stability_sample(
    browser_score: dict[str, Any],
    *,
    repeat_index: int,
    label: str,
) -> dict[str, Any]:
    fit_score = _optional_float(browser_score.get("fit_score"))
    if fit_score is None:
        fit_score = _optional_float(browser_score.get("score"))
    diff_score = _optional_float(browser_score.get("diff_score"))
    if diff_score is None and fit_score is not None:
        diff_score = 1.0 - fit_score
    return {
        "repeat_index": int(repeat_index),
        "label": str(label),
        "fit_score": fit_score,
        "diff_score": diff_score,
        "views": _score_views(browser_score),
    }


def _view_stats(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_view: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        raw_views = sample.get("views")
        if not isinstance(raw_views, list):
            continue
        for view in raw_views:
            if not isinstance(view, dict):
                continue
            view_id = str(view.get("view_id") or "")
            if not view_id:
                continue
            by_view.setdefault(view_id, []).append(view)

    stats: list[dict[str, Any]] = []
    for view_id, views in sorted(by_view.items()):
        fit_scores = [
            value
            for value in (_optional_float(view.get("fit_score")) for view in views)
            if value is not None
        ]
        foreground_sums = [
            value
            for value in (_optional_float(view.get("foreground_weight_sum")) for view in views)
            if value is not None
        ]
        foreground_spread = _spread(foreground_sums)
        foreground_mean = (sum(foreground_sums) / len(foreground_sums)) if foreground_sums else None
        foreground_ratio = (
            foreground_spread / max(abs(foreground_mean), 1.0)
            if foreground_spread is not None and foreground_mean is not None
            else None
        )
        stats.append(
            {
                "view_id": view_id,
                "sample_count": len(views),
                "fit_score_spread": _round_float(_spread(fit_scores)),
                "foreground_weight_sum_spread": _round_float(foreground_spread),
                "foreground_weight_sum_spread_ratio": _round_float(foreground_ratio),
            }
        )
    return stats


def _lower_quartile_policy_value(summary: dict[str, Any], prefix: str) -> float | None:
    values = _distribution_values(summary, prefix)
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    lower_index = int(math.floor((count - 1) * 0.25))
    if prefix == "diff_score":
        index = count - 1 - lower_index
    else:
        index = lower_index
    return ordered[index]


def _distribution_values(summary: dict[str, Any], prefix: str) -> list[float]:
    values: list[float] = []
    for key in ("records", "samples"):
        raw_items = summary.get(key)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            value = _optional_float(item.get(prefix))
            if value is not None:
                values.append(value)
    return values


def _dominant_mode_policy_value(summary: dict[str, Any], prefix: str, policy: str) -> float | None:
    mode = summary.get("dominant_foreground_mode")
    if not isinstance(mode, dict):
        modes = summary.get("foreground_modes")
        if isinstance(modes, list) and modes and isinstance(modes[0], dict):
            mode = modes[0]
    if not isinstance(mode, dict):
        return None
    if policy == "lower_quartile":
        value = _lower_quartile_policy_value(mode, prefix)
        if value is not None:
            return value
    return _conservative_policy_value(mode, prefix)


def _canonical_mode_policy_value(summary: dict[str, Any], prefix: str, policy: str) -> float | None:
    mode = summary.get("canonical_foreground_mode")
    if not isinstance(mode, dict):
        return None
    if policy == "lower_quartile":
        value = _lower_quartile_policy_value(mode, prefix)
        if value is not None:
            return value
    return _conservative_policy_value(mode, prefix)


def _conservative_policy_value(summary: dict[str, Any], prefix: str) -> float | None:
    if prefix == "fit_score":
        return _optional_float(summary.get("conservative_fit_score", summary.get("fit_score_min")))
    return _optional_float(summary.get("conservative_diff_score", summary.get("diff_score_max")))


def _foreground_modes(samples: list[dict[str, Any]], *, bucket_size: float = 128.0) -> list[dict[str, Any]]:
    by_signature: dict[tuple[tuple[str, int], ...], list[dict[str, Any]]] = {}
    for sample in samples:
        signature = _foreground_signature(sample, bucket_size=bucket_size)
        if not signature:
            continue
        by_signature.setdefault(signature, []).append(sample)
    modes: list[dict[str, Any]] = []
    for index, (signature, mode_samples) in enumerate(by_signature.items()):
        fit_scores = [
            value
            for value in (_optional_float(sample.get("fit_score")) for sample in mode_samples)
            if value is not None
        ]
        diff_scores = [
            value
            for value in (_optional_float(sample.get("diff_score")) for sample in mode_samples)
            if value is not None
        ]
        mode = {
            "mode_id": f"fg_mode_{index:02d}",
            "sample_count": len(mode_samples),
            "foreground_signature": [
                {"view_id": view_id, "foreground_weight_sum_bucket": bucket}
                for view_id, bucket in signature
            ],
            "fit_score_min": _round_float(min(fit_scores) if fit_scores else None),
            "fit_score_max": _round_float(max(fit_scores) if fit_scores else None),
            "fit_score_spread": _round_float(_spread(fit_scores)),
            "conservative_fit_score": _round_float(min(fit_scores) if fit_scores else None),
            "conservative_diff_score": _round_float(max(diff_scores) if diff_scores else None),
            "samples": copy.deepcopy(mode_samples),
        }
        modes.append(mode)
    return sorted(
        modes,
        key=lambda item: (
            -int(item.get("sample_count") or 0),
            _optional_float(item.get("conservative_fit_score")) or -math.inf,
        ),
    )


def _foreground_signature(sample: dict[str, Any], *, bucket_size: float) -> tuple[tuple[str, int], ...]:
    raw_views = sample.get("views")
    if not isinstance(raw_views, list):
        return ()
    signature: list[tuple[str, int]] = []
    for view in raw_views:
        if not isinstance(view, dict):
            continue
        view_id = str(view.get("view_id") or "")
        foreground_sum = _optional_float(view.get("foreground_weight_sum"))
        if not view_id or foreground_sum is None:
            continue
        bucket = int(round(foreground_sum / bucket_size) * bucket_size)
        signature.append((view_id, bucket))
    return tuple(sorted(signature))


def _normalize_foreground_signature(signature: object, *, bucket_size: float) -> tuple[tuple[str, int], ...]:
    if not signature:
        return ()
    raw_signature = signature
    if isinstance(signature, dict):
        raw_signature = signature.get("foreground_signature") or signature.get("signature")
    if not isinstance(raw_signature, (list, tuple)):
        return ()
    out: list[tuple[str, int]] = []
    for item in raw_signature:
        if isinstance(item, dict):
            view_id = str(item.get("view_id") or "")
            raw_bucket = item.get("foreground_weight_sum_bucket")
            if raw_bucket is None:
                raw_bucket = item.get("foreground_bucket")
            if raw_bucket is None:
                raw_sum = _optional_float(item.get("foreground_weight_sum"))
                raw_bucket = round(raw_sum / bucket_size) * bucket_size if raw_sum is not None else None
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            view_id = str(item[0] or "")
            raw_bucket = item[1]
        else:
            continue
        if not view_id:
            continue
        bucket_value = _optional_float(raw_bucket)
        if bucket_value is None:
            continue
        out.append((view_id, int(round(bucket_value))))
    return tuple(sorted(out))


def _mode_signature_tuple(mode: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    return _normalize_foreground_signature(mode.get("foreground_signature"), bucket_size=1.0)


def _select_canonical_foreground_mode(
    modes: list[dict[str, Any]],
    canonical_signature: tuple[tuple[str, int], ...],
    *,
    max_bucket_distance: float,
) -> dict[str, Any] | None:
    if not modes or not canonical_signature:
        return None
    best_mode: dict[str, Any] | None = None
    best_distance = math.inf
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        distance = _foreground_signature_distance(_mode_signature_tuple(mode), canonical_signature)
        if distance < best_distance:
            best_mode = mode
            best_distance = distance
    if best_mode is None or not math.isfinite(best_distance):
        return None
    max_total_distance = max(0.0, float(max_bucket_distance)) * max(len(canonical_signature), 1)
    if best_distance > max_total_distance:
        return None
    selected = copy.deepcopy(best_mode)
    selected["canonical_signature_distance"] = _round_float(best_distance)
    selected["canonical_signature_max_distance"] = _round_float(max_total_distance)
    return selected


def _foreground_signature_distance(
    left: tuple[tuple[str, int], ...],
    right: tuple[tuple[str, int], ...],
) -> float:
    if len(left) != len(right):
        return math.inf
    left_map = {view_id: bucket for view_id, bucket in left}
    right_map = {view_id: bucket for view_id, bucket in right}
    if set(left_map) != set(right_map):
        return math.inf
    return float(sum(abs(int(left_map[view_id]) - int(right_map[view_id])) for view_id in sorted(left_map)))


def _signature_payload(signature: tuple[tuple[str, int], ...]) -> list[dict[str, Any]] | None:
    if not signature:
        return None
    return [
        {"view_id": view_id, "foreground_weight_sum_bucket": bucket}
        for view_id, bucket in signature
    ]


def _fresh_oracle_record_sample(record: dict[str, Any], *, fallback_index: int) -> dict[str, Any] | None:
    repeat_index = _optional_int(record.get("attempt_index"))
    if repeat_index is None:
        repeat_index = fallback_index
    label = str(record.get("label") or f"attempt_{repeat_index:02d}")
    browser_score = record.get("browser_score")
    if isinstance(browser_score, dict):
        sample = browser_score_stability_sample(browser_score, repeat_index=repeat_index, label=label)
        if sample.get("fit_score") is None:
            sample["fit_score"] = _optional_float(record.get("fit_score"))
        if sample.get("diff_score") is None:
            diff_score = _optional_float(record.get("diff_score"))
            if diff_score is None and sample.get("fit_score") is not None:
                diff_score = 1.0 - float(sample["fit_score"])
            sample["diff_score"] = diff_score
        return sample

    fit_score = _optional_float(record.get("fit_score"))
    diff_score = _optional_float(record.get("diff_score"))
    if diff_score is None and fit_score is not None:
        diff_score = 1.0 - fit_score
    if fit_score is None and diff_score is None:
        return None
    return {
        "repeat_index": repeat_index,
        "label": label,
        "fit_score": fit_score,
        "diff_score": diff_score,
        "views": [],
    }


def _score_views(browser_score: dict[str, Any]) -> list[dict[str, Any]]:
    raw_views = browser_score.get("views")
    if not isinstance(raw_views, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_views:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "view_id": str(item.get("view_id") or ""),
                "fit_score": _optional_float(item.get("fit_score")),
                "diff_score": _optional_float(item.get("diff_score")),
                "foreground_weight_sum": _optional_float(item.get("foreground_weight_sum")),
            }
        )
    return out


def _spread(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _round_float(value: float | None, digits: int = 10) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
