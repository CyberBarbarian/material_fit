"""Output summaries and artifact bookkeeping for material fitting runs."""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _number_or_default(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _effective_target_score(target_score: float, score_ceiling: dict[str, Any] | None) -> float:
    if isinstance(score_ceiling, dict):
        candidate = _number_or_default(score_ceiling.get("effective_target_score"), math.nan)
        if math.isfinite(candidate):
            return float(candidate)
    return float(target_score)


def _build_batch_execution_summary(
    iterations: list[dict[str, Any]],
    *,
    analysis_performance: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_counts: dict[str, int] = {}
    disabled_reasons: dict[str, int] = {}
    effective_workers = 1
    renderer_worker_count = 1
    analysis_pipeline_workers = 0
    analysis_pipeline_evaluations = 0
    batch_starts = 0
    cached_evaluations = 0
    cache_sources: dict[str, int] = {}
    for entry in iterations:
        timing = entry.get("timing") if isinstance(entry.get("timing"), dict) else {}
        mode = str(timing.get("evaluation_mode") or "")
        if mode:
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        reason = str(timing.get("evaluation_parallel_disabled_reason") or "")
        if reason:
            disabled_reasons[reason] = disabled_reasons.get(reason, 0) + 1
        try:
            effective_workers = max(effective_workers, int(timing.get("evaluation_workers") or 1))
        except (TypeError, ValueError):
            effective_workers = max(effective_workers, 1)
        try:
            renderer_worker_count = max(renderer_worker_count, int(timing.get("renderer_worker_count") or 1))
        except (TypeError, ValueError):
            renderer_worker_count = max(renderer_worker_count, 1)
        if bool(timing.get("analysis_pipeline_enabled")):
            analysis_pipeline_evaluations += 1
            try:
                analysis_pipeline_workers = max(
                    analysis_pipeline_workers,
                    int(timing.get("analysis_pipeline_workers") or 1),
                )
            except (TypeError, ValueError):
                analysis_pipeline_workers = max(analysis_pipeline_workers, 1)
        if int(timing.get("evaluation_batch_index") or 0) == 0:
            batch_starts += 1
        if bool(timing.get("candidate_evaluation_cache_hit")):
            cached_evaluations += 1
            source = timing.get("candidate_evaluation_cache_source_iteration")
            if source is not None:
                source_key = str(source)
                cache_sources[source_key] = cache_sources.get(source_key, 0) + 1

    total_evaluations = len(iterations)
    real_evaluations = total_evaluations - cached_evaluations

    summary = {
        "enabled": bool(iterations) and bool(mode_counts),
        "evaluation_batch_size": int(analysis_performance.get("evaluation_batch_size") or 1),
        "evaluation_workers_requested": int(analysis_performance.get("evaluation_workers") or 1),
        "evaluation_workers_effective": effective_workers,
        "evaluation_parallel_safe": bool(analysis_performance.get("evaluation_parallel_safe", False)),
        "renderer_parallel_safe": any(
            bool(
                (entry.get("timing") if isinstance(entry.get("timing"), dict) else {}).get("renderer_parallel_safe")
            )
            for entry in iterations
        ),
        "renderer_worker_count": renderer_worker_count,
        "evaluations": total_evaluations,
        "real_evaluations": real_evaluations,
        "cached_evaluations": cached_evaluations,
        "cache_hit_rate": (cached_evaluations / total_evaluations) if total_evaluations else 0.0,
        "cache_sources": dict(sorted(cache_sources.items())),
        "batches": batch_starts,
        "mode_counts": mode_counts,
        "disabled_reasons": disabled_reasons,
    }
    if context is not None:
        summary["context"] = copy.deepcopy(context)
    if analysis_pipeline_evaluations:
        summary["analysis_pipeline_evaluations"] = analysis_pipeline_evaluations
        summary["analysis_pipeline_workers_effective"] = analysis_pipeline_workers
    return summary


def _build_optimizer_evidence_summary(
    *,
    status: str,
    terminal_reason: str | None,
    target_score: float,
    effective_target_score: float | None,
    score_ceiling: dict[str, Any] | None,
    best_fit_score: float,
    iterations: list[dict[str, Any]],
    fit_score_mode: str,
    optimizer_preset: str,
    optimizer: str,
    cma_es_config: dict[str, Any] | None,
    warm_start_history_size: int,
    warm_start_sources: dict[str, Any],
    analysis_performance: dict[str, Any],
    batch_execution: dict[str, Any] | None,
    candidate_archive: dict[str, Any] | None,
    candidate_archive_path: str,
) -> dict[str, Any]:
    batch_summary = batch_execution if isinstance(batch_execution, dict) else {"enabled": False}
    effective_target = (
        float(effective_target_score)
        if effective_target_score is not None
        else _effective_target_score(target_score, score_ceiling)
    )
    return {
        "optimizer_preset": optimizer_preset,
        "optimizer": optimizer,
        "status": status,
        "terminal_reason": terminal_reason,
        "target_score": target_score,
        "effective_target_score": effective_target,
        "score_ceiling": copy.deepcopy(score_ceiling),
        "best_fit_score": best_fit_score,
        "target_reached": bool(best_fit_score >= target_score),
        "effective_target_reached": bool(best_fit_score >= effective_target),
        "iterations": len(iterations),
        "fit_score_mode": fit_score_mode,
        "warm_start_history_size": warm_start_history_size,
        "warm_start_sources": dict(warm_start_sources),
        "cma_es": cma_es_config,
        "initial_design": _build_initial_design_evidence_summary(
            iterations,
            cma_es_config=cma_es_config,
        ),
        "multi_fidelity": {
            "research_metrics_profile": str(analysis_performance.get("research_metrics_profile") or "tiered"),
            "full_rerank_top_k": int(analysis_performance.get("full_rerank_top_k") or 0),
            "best_full_validation": bool(analysis_performance.get("best_full_validation", False)),
            "target_full_validation": bool(analysis_performance.get("target_full_validation", False)),
        },
        "batch_execution": batch_summary,
        "candidate_archive": _build_candidate_archive_evidence_summary(
            candidate_archive,
            path=candidate_archive_path,
        ),
    }


def _build_optimizer_candidate_archive(
    iterations: list[dict[str, Any]],
    *,
    top_k: int = 20,
) -> dict[str, Any]:
    normalized_top_k = max(0, _optional_int_like(top_k, default=20))
    candidates: list[dict[str, Any]] = []
    for entry in iterations:
        fit_score = _number_or_default(entry.get("fit_score_before"), -math.inf)
        if not math.isfinite(fit_score):
            continue
        iteration = _optional_int_like(entry.get("iteration"), default=len(candidates))
        diff_score = _number_or_default(entry.get("diff_score_before"), math.inf)
        scored_params = (
            copy.deepcopy(entry.get("scored_params"))
            if isinstance(entry.get("scored_params"), dict)
            else None
        )
        proposed_params = (
            copy.deepcopy(entry.get("candidate_params"))
            if isinstance(entry.get("candidate_params"), dict)
            else None
        )
        score_aligned_params = scored_params if isinstance(scored_params, dict) else proposed_params
        candidate: dict[str, Any] = {
            "iteration": iteration,
            "iter_id": str(entry.get("iter_id") or f"iter_{iteration:04d}"),
            "fit_score": fit_score,
            "diff_score": diff_score if math.isfinite(diff_score) else None,
            "selected_stage": entry.get("selected_stage"),
            "optimizer": entry.get("optimizer"),
            "is_best": bool(entry.get("is_best", False)),
            "is_snapshot": bool(entry.get("is_snapshot", False)),
            "can_open_detail": bool(entry.get("can_open_detail", False)),
            "params_path": str(entry.get("params_path") or ""),
            "params_path_role": "candidate_params" if entry.get("params_path") else "",
            "candidate_params": (
                copy.deepcopy(score_aligned_params)
                if isinstance(score_aligned_params, dict)
                else None
            ),
            "scored_params": scored_params,
            "proposed_params": proposed_params,
            "score_params_role": entry.get("score_params_role"),
            "candidate_lmat_path": str(entry.get("candidate_lmat_path") or ""),
            "applied_lmat": entry.get("applied_lmat"),
        }
        candidates.append(candidate)

    def sort_key(candidate: dict[str, Any]) -> tuple[float, float, int]:
        fit_score = _number_or_default(candidate.get("fit_score"), -math.inf)
        diff_score = _number_or_default(candidate.get("diff_score"), math.inf)
        iteration = _optional_int_like(candidate.get("iteration"), default=0)
        return (-fit_score, diff_score, iteration)

    candidates.sort(key=sort_key)
    ranked = [dict(candidate, rank=index + 1) for index, candidate in enumerate(candidates[:normalized_top_k])]
    return {
        "top_k": normalized_top_k,
        "selection_metric": "fit_score",
        "ranking": "fit_score_desc_diff_score_asc_iteration_asc",
        "total_candidates": len(candidates),
        "candidates": ranked,
        "best": ranked[0] if ranked else None,
    }


def _build_candidate_archive_evidence_summary(
    candidate_archive: dict[str, Any] | None,
    *,
    path: str,
) -> dict[str, Any]:
    archive = candidate_archive if isinstance(candidate_archive, dict) else {}
    best = archive.get("best") if isinstance(archive.get("best"), dict) else {}
    summary: dict[str, Any] = {
        "path": path,
        "top_k": _optional_int_like(archive.get("top_k"), default=20),
        "total_candidates": _optional_int_like(archive.get("total_candidates"), default=0),
    }
    if best:
        summary["best_iteration"] = _optional_int_like(best.get("iteration"), default=-1)
        best_fit_score = _number_or_default(best.get("fit_score"), -math.inf)
        if math.isfinite(best_fit_score):
            summary["best_fit_score"] = best_fit_score
    return summary


def _build_initial_design_evidence_summary(
    iterations: list[dict[str, Any]],
    *,
    cma_es_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = cma_es_config if isinstance(cma_es_config, dict) else {}
    configured_samples = _optional_int_like(config.get("initial_design_samples"), default=0)
    status_entries = [
        entry.get("cma_initial_design")
        for entry in iterations
        if isinstance(entry.get("cma_initial_design"), dict)
    ]
    latest = dict(status_entries[-1]) if status_entries else {}
    enabled = bool(latest.get("enabled", configured_samples > 0))
    method = str(latest.get("method") or config.get("initial_design_method") or "latin_hypercube")
    requested_samples = _optional_int_like(
        latest.get("requested_samples"),
        default=configured_samples,
    )
    include_current = bool(
        latest.get(
            "include_current",
            config.get("initial_design_include_current", True),
        )
    )
    evaluated_samples = max(
        [_optional_int_like(item.get("evaluated_samples"), default=0) for item in status_entries]
        or [0]
    )
    completed = bool(latest.get("completed", not enabled))
    summary: dict[str, Any] = {
        "enabled": enabled,
        "method": method,
        "requested_samples": requested_samples,
        "include_current": include_current,
        "evaluated_samples": evaluated_samples,
        "completed": completed,
    }
    if method == "local_coordinate_probe":
        summary["local_step_ratio"] = _number_or_default(
            latest.get("local_step_ratio", config.get("initial_design_local_step_ratio")),
            0.05,
        )

    initial_design_iterations = [
        entry
        for entry in iterations
        if entry.get("selected_stage") == "cma_initial_design"
        and math.isfinite(_number_or_default(entry.get("fit_score_before"), -math.inf))
    ]
    if initial_design_iterations:
        best_entry = max(
            initial_design_iterations,
            key=lambda entry: _number_or_default(entry.get("fit_score_before"), -math.inf),
        )
        summary["best_fit_score"] = _number_or_default(best_entry.get("fit_score_before"), -math.inf)
        summary["best_iteration"] = int(best_entry.get("iteration", -1))
    elif math.isfinite(_number_or_default(latest.get("best_fit_score"), -math.inf)):
        summary["best_fit_score"] = _number_or_default(latest.get("best_fit_score"), -math.inf)
        if latest.get("best_index") is not None:
            summary["best_iteration"] = _optional_int_like(latest.get("best_index"), default=-1)
    return summary


def _optional_int_like(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _record_iteration_outputs(
    *,
    auto_dir: Path,
    iteration_payload: dict[str, Any],
    result_iterations: list[dict[str, Any]],
    iteration_series: list[dict[str, Any]],
    snapshot_iterations: set[int],
    full_payloads: dict[int, dict[str, Any]],
    is_snapshot: bool,
    is_best: bool,
) -> None:
    iteration = int(iteration_payload.get("iteration", len(iteration_series)))
    summary = _iteration_series_entry(iteration_payload, is_snapshot=is_snapshot, is_best=is_best)
    iteration_series.append(summary)
    result_iterations.append(summary)
    full_payloads[iteration] = iteration_payload
    if is_snapshot:
        snapshot_iterations.add(iteration)
        _write_json(auto_dir / f"iter_{iteration:04d}" / "decision.json", iteration_payload)
    _write_json(auto_dir / "iteration_series.json", iteration_series)
    _write_snapshot_index(auto_dir, iteration_series, snapshot_iterations)


def _iteration_series_entry(
    iteration_payload: dict[str, Any],
    *,
    is_snapshot: bool,
    is_best: bool,
) -> dict[str, Any]:
    decision = iteration_payload.get("decision") if isinstance(iteration_payload.get("decision"), dict) else {}
    perceptual = (
        iteration_payload.get("perceptual_signals")
        if isinstance(iteration_payload.get("perceptual_signals"), dict)
        else {}
    )
    human = perceptual.get("human_accept") if isinstance(perceptual.get("human_accept"), dict) else {}
    research = perceptual.get("research_metrics") if isinstance(perceptual.get("research_metrics"), dict) else {}
    timing = iteration_payload.get("timing") if isinstance(iteration_payload.get("timing"), dict) else {}
    iteration = int(iteration_payload.get("iteration", 0))
    entry = {
        "iter_id": f"iter_{iteration:04d}",
        "iteration": iteration,
        "kind": "auto_adjust",
        "selected_stage": iteration_payload.get("selected_stage"),
        "diff_score_before": iteration_payload.get("diff_score_before"),
        "fit_score_before": iteration_payload.get("fit_score_before"),
        "target_score": iteration_payload.get("target_score"),
        "effective_target_score": iteration_payload.get("effective_target_score"),
        "stop_reason": decision.get("stop_reason"),
        "iteration_gain": decision.get("iteration_gain"),
        "changes_count": len(decision.get("changes") or []) if isinstance(decision.get("changes"), list) else 0,
        "applied_lmat": decision.get("applied_lmat"),
        "params_path": iteration_payload.get("params_path"),
        "scored_params": (
            copy.deepcopy(iteration_payload.get("scored_params"))
            if isinstance(iteration_payload.get("scored_params"), dict)
            else None
        ),
        "score_params_role": iteration_payload.get("score_params_role"),
        "candidate_params": (
            copy.deepcopy(iteration_payload.get("candidate_params"))
            if isinstance(iteration_payload.get("candidate_params"), dict)
            else None
        ),
        "candidate_lmat_path": iteration_payload.get("candidate_lmat_path"),
        "research_score": research.get("score"),
        "research_loss": research.get("loss"),
        "human_accept_score": human.get("score"),
        "perceptual_fit_score": perceptual.get("fit_score"),
        "weighted_mae": perceptual.get("weighted_mae"),
        "optimizer": decision.get("optimizer"),
        "semantic_action": decision.get("semantic_action"),
        "timing": {
            key: timing.get(key)
            for key in (
                "iteration_total_ms",
                "candidate_capture_ms",
                "analyze_multiview_ms",
                "strategy_propose_ms",
                "multiview_workers",
                "evaluation_batch_size",
                "evaluation_workers",
                "evaluation_workers_requested",
                "evaluation_parallel_safe",
                "renderer_parallel_safe",
                "renderer_worker_count",
                "evaluation_mode",
                "analysis_pipeline_enabled",
                "analysis_pipeline_workers",
                "analysis_pipeline_skipped",
                "evaluation_batch_index",
                "evaluation_batch_count",
                "evaluation_parallel_disabled_reason",
                "candidate_evaluation_cache_hit",
                "candidate_evaluation_cache_source_iteration",
                "initial_context_render_ms",
                "initial_context_render_iteration",
                "initial_context_render_status",
                "initial_context_browser_score_used",
                "browser_score_used",
                "browser_score_metric",
                "research_metrics_profile",
                "fast_score_only_enabled",
                "full_rerank_top_k",
                "full_rerank_selected",
                "full_rerank_profile",
                "full_rerank_source_fit_score",
                "full_rerank_ms",
                "best_full_validation",
                "best_full_validation_selected",
                "best_full_validation_profile",
                "best_full_validation_source_fit_score",
                "best_full_validation_ms",
                "target_full_validation",
                "target_full_validation_selected",
                "target_full_validation_profile",
                "target_full_validation_source_fit_score",
                "target_full_validation_ms",
                "stability_validation_repeats",
                "stability_validation_mode",
                "stability_validation_top_k",
                "stability_validation_top_k_selected",
                "stability_validation_top_k_rank",
                "stability_validation_restart_renderer",
                "stability_validation_selected",
                "stability_validation_fresh_oracle_fallback",
                "stability_validation_skipped",
                "stability_validation_stable",
                "stability_validation_fit_score_spread",
                "stability_validation_worst_foreground_weight_sum_spread",
                "stability_validation_score_policy",
                "stability_validation_ms",
            )
            if key in timing
        },
        "is_snapshot": bool(is_snapshot),
        "can_open_detail": bool(is_snapshot),
        "is_best": bool(is_best),
    }
    stability_validation = iteration_payload.get("stability_validation")
    if isinstance(stability_validation, dict):
        entry["stability_validation"] = {
            key: copy.deepcopy(stability_validation.get(key))
            for key in (
                "stable",
                "sample_count",
                "score_stable",
                "foreground_stable",
                "score_policy",
                "fit_score_min",
                "fit_score_median",
                "fit_score_mean",
                "fit_score_max",
                "fit_score_spread",
                "conservative_fit_score",
                "conservative_diff_score",
                "worst_foreground_view_id",
                "worst_foreground_weight_sum_spread",
                "worst_foreground_weight_sum_spread_ratio",
                "foreground_modes",
                "dominant_foreground_mode",
                "canonical_foreground_signature",
                "canonical_foreground_mode",
            )
            if key in stability_validation
        }
    initial_design = _compact_cma_initial_design(decision)
    if initial_design is not None:
        entry["cma_initial_design"] = initial_design
    research_validity = _compact_research_validity(research)
    if research_validity is not None:
        entry["research_validity"] = research_validity
    return entry


def _compact_research_validity(research: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(research, dict):
        return None
    out: dict[str, Any] = {}
    for key in (
        "status",
        "profile",
        "score_is_proxy",
        "valid_view_count",
        "invalid_view_count",
    ):
        if key in research:
            out[key] = copy.deepcopy(research.get(key))

    validity = research.get("validity") if isinstance(research.get("validity"), dict) else {}
    for key in (
        "passed",
        "mask_iou_min",
        "bbox_center_error_px_max",
        "bbox_scale_error_max",
        "reasons",
    ):
        if key in validity:
            out[key] = copy.deepcopy(validity.get(key))

    guidance = research.get("guidance") if isinstance(research.get("guidance"), dict) else {}
    if "validity_penalty_applied" in guidance:
        out["validity_penalty_applied"] = bool(guidance.get("validity_penalty_applied"))
    penalty = guidance.get("validity_penalty") if isinstance(guidance.get("validity_penalty"), dict) else {}
    if "mode" in penalty:
        out["validity_penalty_mode"] = penalty.get("mode")
    if "loss" in penalty:
        out["validity_penalty_loss"] = penalty.get("loss")
    return out or None


def _compact_cma_initial_design(decision: dict[str, Any]) -> dict[str, Any] | None:
    cma_es = decision.get("cma_es") if isinstance(decision.get("cma_es"), dict) else {}
    initial_design = cma_es.get("initial_design") if isinstance(cma_es.get("initial_design"), dict) else None
    if initial_design is None:
        return None
    out: dict[str, Any] = {
        "enabled": bool(initial_design.get("enabled", False)),
        "method": str(initial_design.get("method") or "latin_hypercube"),
        "requested_samples": _optional_int_like(initial_design.get("requested_samples"), default=0),
        "include_current": bool(initial_design.get("include_current", True)),
        "evaluated_samples": _optional_int_like(initial_design.get("evaluated_samples"), default=0),
        "pending_samples": _optional_int_like(initial_design.get("pending_samples"), default=0),
        "remaining_samples": _optional_int_like(initial_design.get("remaining_samples"), default=0),
        "completed": bool(initial_design.get("completed", False)),
    }
    if out["method"] == "local_coordinate_probe":
        out["local_step_ratio"] = _number_or_default(initial_design.get("local_step_ratio"), 0.05)
    if math.isfinite(_number_or_default(initial_design.get("best_fit_score"), -math.inf)):
        out["best_fit_score"] = _number_or_default(initial_design.get("best_fit_score"), -math.inf)
    if initial_design.get("best_index") is not None:
        out["best_index"] = _optional_int_like(initial_design.get("best_index"), default=-1)
    return out


def _write_snapshot_index(auto_dir: Path, series: list[dict[str, Any]], snapshot_iterations: set[int]) -> None:
    by_iter = {
        int(item.get("iteration")): item
        for item in series
        if isinstance(item.get("iteration"), int)
    }
    snapshots = [
        {
            **by_iter.get(iteration, {"iteration": iteration, "iter_id": f"iter_{iteration:04d}"}),
            "is_snapshot": True,
            "can_open_detail": True,
        }
        for iteration in sorted(snapshot_iterations)
    ]
    _write_json(
        auto_dir / "snapshot_index.json",
        {
            "snapshots": snapshots,
            "snapshot_iterations": sorted(snapshot_iterations),
        },
    )


def _mark_series_snapshots(series: list[dict[str, Any]], snapshot_iterations: set[int]) -> None:
    for item in series:
        iteration = item.get("iteration")
        if isinstance(iteration, int) and iteration in snapshot_iterations:
            item["is_snapshot"] = True
            item["can_open_detail"] = True


def _prune_iteration_artifacts(
    auto_dir: Path,
    iterations: list[dict[str, Any]],
    *,
    current_iteration: int,
    snapshot_interval: int,
    keep_last_n: int,
    always_keep_best: bool,
    always_keep_first: bool,
    snapshot_iterations: set[int] | None = None,
    full_payloads: dict[int, dict[str, Any]] | None = None,
    final_cleanup: bool = False,
) -> None:
    if keep_last_n < 0:
        keep_last_n = 0
    protected: set[int] = set(range(max(0, current_iteration - keep_last_n + 1), current_iteration + 1))
    if always_keep_first:
        protected.add(0)
    if snapshot_interval > 0:
        protected.update(
            iteration
            for iteration in range(0, current_iteration + 1)
            if iteration % snapshot_interval == 0
        )
    if always_keep_best:
        best_iteration = _best_recorded_iteration(iterations)
        if best_iteration is not None:
            protected.add(best_iteration)
    if snapshot_iterations:
        protected.update(snapshot_iterations)
    if full_payloads:
        for iteration in list(protected):
            payload = full_payloads.get(iteration)
            if isinstance(payload, dict):
                protected.update(_referenced_iteration_numbers(payload))
    if not auto_dir.exists():
        return
    for entry in auto_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("iter_"):
            continue
        try:
            iteration = int(entry.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        if iteration in protected or iteration > current_iteration:
            continue
        if final_cleanup:
            shutil.rmtree(entry, ignore_errors=True)
            continue
        _delete_heavy_iteration_artifacts(entry)
        decision_path = entry / "decision.json"
        if decision_path.exists():
            decision_path.unlink()
        candidate_dir = entry / "candidate"
        if candidate_dir.exists():
            for name in ("params.json",):
                target = candidate_dir / name
                if target.exists():
                    target.unlink()
            for lmat in candidate_dir.glob("*.lmat"):
                lmat.unlink(missing_ok=True)


def _referenced_iteration_numbers(iteration_payload: dict[str, Any]) -> set[int]:
    refs: set[int] = set()
    stack: list[Any] = [iteration_payload.get("input_pair"), iteration_payload.get("input_pairs")]
    pattern = re.compile(r"iter_(\d{4,})")
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str):
            for match in pattern.finditer(value.replace("\\", "/")):
                try:
                    refs.add(int(match.group(1)))
                except ValueError:
                    continue
    return refs


def _best_recorded_iteration(iterations: list[dict[str, Any]]) -> int | None:
    best_iteration: int | None = None
    best_score = -math.inf
    for item in iterations:
        score = _number_or_default(item.get("fit_score_before"), -math.inf)
        iteration_value = item.get("iteration")
        if score > best_score and isinstance(iteration_value, int):
            best_score = score
            best_iteration = iteration_value
    return best_iteration


def _delete_heavy_iteration_artifacts(iteration_dir: Path) -> None:
    targets = [
        iteration_dir / "image_analysis",
        iteration_dir / "candidate" / "laya_multiview",
    ]
    for target in targets:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
