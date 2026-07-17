"""Stateless helpers for the joint discrete/continuous strategy."""

from __future__ import annotations

import copy
import math
from typing import Any

from .strategy_core import StrategyContext


def _select_diverse_survivors(
    branches: Sequence[_Branch],
    width: int,
    *,
    use_diversity: bool,
) -> list[_Branch]:
    ranked = sorted(branches, key=lambda branch: branch.best_score, reverse=True)
    if width >= len(ranked):
        return ranked
    if not use_diversity or width < 3:
        return ranked[:width]

    selected: list[_Branch] = []
    selected_ids: set[str] = set()

    def add_best(axis: str, value: Any) -> None:
        if len(selected) >= width:
            return
        for branch in ranked:
            if branch.candidate_id in selected_ids:
                continue
            if branch.candidate.get("axes", {}).get(axis) == value:
                selected.append(branch)
                selected_ids.add(branch.candidate_id)
                return

    normal_values = tuple(
        dict.fromkeys(branch.candidate.get("axes", {}).get("normal_mode") for branch in ranked)
    )
    for value in normal_values:
        add_best("normal_mode", value)
    blend_values = tuple(
        dict.fromkeys(branch.candidate.get("axes", {}).get("blend_src") for branch in ranked)
    )
    for value in blend_values:
        add_best("blend_src", value)
    for branch in ranked:
        if len(selected) >= width:
            break
        if branch.candidate_id not in selected_ids:
            selected.append(branch)
            selected_ids.add(branch.candidate_id)
    return selected


def _quantize_optimizer_feedback(
    ctx: StrategyContext,
    *,
    score_step: float,
    residual_step: float,
    residual_projection_size: int = 0,
) -> tuple[StrategyContext, dict[str, Any]]:
    score_step = max(float(score_step), 0.0)
    residual_step = max(float(residual_step), 0.0)
    enabled = score_step > 0.0 or residual_step > 0.0
    if not enabled:
        return ctx, {
            "enabled": False,
            "score_step": score_step,
            "residual_step": residual_step,
        }

    fit_score = float(ctx.fit_score)
    if score_step > 0.0 and math.isfinite(fit_score):
        fit_score = round(fit_score / score_step) * score_step
    diff_score = max(0.0, 1.0 - fit_score)
    analysis = copy.deepcopy(ctx.analysis)
    residual_count = 0
    residual_changed_count = 0
    maximum_residual_delta = 0.0
    payload = analysis.get("structured_residual_features")
    features = payload.get("features") if isinstance(payload, dict) else None
    original_residual_count = len(features) if isinstance(features, list) else 0
    if (
        residual_projection_size > 0
        and isinstance(features, list)
        and len(features) > residual_projection_size
    ):
        features = _count_sketch_residual_features(
            features,
            residual_projection_size,
        )
        payload["features"] = features
    if residual_step > 0.0 and isinstance(features, list):
        quantized_features: list[Any] = []
        for raw_value in features:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                quantized_features.append(raw_value)
                continue
            if not math.isfinite(value):
                quantized_features.append(raw_value)
                continue
            quantized = round(value / residual_step) * residual_step
            delta = abs(quantized - value)
            residual_count += 1
            if delta > 0.0:
                residual_changed_count += 1
                maximum_residual_delta = max(maximum_residual_delta, delta)
            quantized_features.append(quantized)
        payload["features"] = quantized_features

    audit = {
        "enabled": True,
        "score_step": score_step,
        "residual_step": residual_step,
        "raw_fit_score": float(ctx.fit_score),
        "quantized_fit_score": fit_score,
        "residual_count": residual_count,
        "original_residual_count": original_residual_count,
        "projected_residual_count": len(features) if isinstance(features, list) else 0,
        "residual_projection_size": residual_projection_size,
        "residual_changed_count": residual_changed_count,
        "maximum_residual_delta": maximum_residual_delta,
    }
    return (
        StrategyContext(
            iteration=ctx.iteration,
            current_params=ctx.current_params,
            analysis=analysis,
            diff_score=diff_score,
            fit_score=fit_score,
            state=ctx.state,
        ),
        audit,
    )


def _count_sketch_residual_features(
    features: Sequence[Any],
    projection_size: int,
) -> list[float]:
    size = max(int(projection_size), 1)
    sums = [0.0] * size
    counts = [0] * size
    for index, raw_value in enumerate(features):
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        bucket = ((index * 2654435761) & 0xFFFFFFFF) % size
        sign = -1.0 if ((index * 2246822519) & 0x80000000) else 1.0
        sums[bucket] += sign * value
        counts[bucket] += 1
    return [
        value / math.sqrt(max(count, 1))
        for value, count in zip(sums, counts, strict=True)
    ]


def _positive_int_tuple(value: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = value if isinstance(value, (list, tuple)) else default
    parsed = tuple(max(int(item), 1) for item in raw)
    return parsed or default


def _normalized_grid_step(value: Any, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool):
        raise ValueError("proposal quantization normalized step must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 0.01:
        raise ValueError(
            "proposal quantization normalized step must be finite and in [0, 0.01]"
        )
    return parsed


def _positive_float_tuple(value: Any, default: tuple[float, ...]) -> tuple[float, ...]:
    raw = value if isinstance(value, (list, tuple)) else default
    parsed = tuple(float(item) for item in raw)
    if not parsed or any(not math.isfinite(item) or item <= 0.0 for item in parsed):
        return default
    return parsed


def _finite_unique_float_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    parsed: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number not in parsed:
            parsed.append(number)
    return tuple(parsed)


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0.0 else default


def _nonnegative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else default


def _semantic_branch_seed_offset(candidate: dict[str, Any]) -> int:
    axes = candidate.get("axes", {})
    normal_offsets = {
        "normal": 0,
        "normal_y_invert": 1,
        "flat": 2,
        "legacy_y_invert_only": 3,
    }
    normal_offset = normal_offsets.get(str(axes.get("normal_mode")), 3)
    rim_offset = 0 if bool(axes.get("rim_smooth")) else 4
    blend_offset = 0 if int(axes.get("blend_src", 0)) == 0 else 8
    return normal_offset + rim_offset + blend_offset


def _axis_value_filter(value: Any) -> dict[str, tuple[Any, ...]]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, tuple[Any, ...]] = {}
    for axis, raw_values in value.items():
        if not isinstance(raw_values, (list, tuple, set)):
            continue
        values = tuple(dict.fromkeys(raw_values))
        if values:
            parsed[str(axis)] = values
    return parsed


def _observable_score_summary(analysis: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only target-PNG-derived score signals useful for hard-state audits."""
    if not isinstance(analysis, dict):
        return {}
    browser_score = analysis.get("browser_score")
    if not isinstance(browser_score, dict):
        return {}
    views = browser_score.get("views")
    if not isinstance(views, list) or not views:
        return {}

    component_names = (
        "foreground_rgb",
        "color_distribution",
        "luminance_structure",
        "detail_texture",
        "highlight_emission",
    )
    component_values: dict[str, list[float]] = {name: [] for name in component_names}
    view_rows: list[dict[str, Any]] = []
    for raw_view in views:
        if not isinstance(raw_view, dict):
            continue
        components = raw_view.get("material_components")
        components = components if isinstance(components, dict) else {}
        row: dict[str, Any] = {"view_id": raw_view.get("view_id")}
        fit_score = raw_view.get("fit_score")
        if isinstance(fit_score, (int, float)) and math.isfinite(float(fit_score)):
            row["fit_score"] = float(fit_score)
        for name in component_names:
            value = components.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                number = float(value)
                component_values[name].append(number)
                row[name] = number
        view_rows.append(row)

    component_means = {
        name: sum(values) / len(values)
        for name, values in component_values.items()
        if values
    }
    return {
        "metric": browser_score.get("metric"),
        "fit_score": browser_score.get("fit_score", browser_score.get("score")),
        "component_means": component_means,
        "views": view_rows,
    }
