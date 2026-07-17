"""Batched CMA optimization execution.

The public compatibility wrapper remains in ``fit_material``. Runtime names
are rebound for each call so existing integrations that patch that module keep
working.
"""

from __future__ import annotations

from typing import Any


def bind_runtime(namespace: dict[str, Any]) -> None:
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value


def run_cma_batch_auto_adjustment(
    *,
    config: dict[str, Any],
    project_root: Path,
    output_dir: Path,
    laya_material_path: Path,
    laya_shader_params: list[Any],
    driver: RenderDriver,
    iterations: int,
    target_score: float,
    use_capture: bool,
    write_candidate_lmat: bool,
    apply_lmat: bool,
    capture_screen_after_apply: bool,
    rerender_wait_ms: int,
    screen_capture_region: str,
    screen_capture_max_keep: int | None,
    fit_score_mode: str,
    optimizer: str,
    cma_es_config: CmaesStrategyConfig | None,
    focus_callback: Callable[[str], dict[str, Any]] | None,
    auto_dir: Path,
    external_backup_dir: Path,
    state: AdjustmentState,
    current_params: dict[str, Any],
    strategy: Any,
    analysis_performance: dict[str, Any],
    warm_history: list[tuple[dict[str, Any], float]],
    warm_start_sources: dict[str, Any],
    semantic_graph: dict[str, Any] | None,
    resume_iteration_series: list[dict[str, Any]] | None = None,
    score_ceiling: dict[str, Any] | None = None,
    effective_target_score: float | None = None,
) -> dict[str, Any]:
    """Run CMA-ES in explicit ask-many/tell-many batches.

    The implementation is intentionally sequential at the renderer boundary:
    the current Laya path writes one shared ``.lmat`` file, so true renderer
    parallelism needs multiple isolated workspaces or renderer instances. This
    helper establishes the optimizer contract first.
    """

    result_iterations: list[dict[str, Any]] = list(resume_iteration_series or [])
    iteration_series: list[dict[str, Any]] = list(resume_iteration_series or [])
    snapshot_iterations: set[int] = {
        int(entry["iteration"])
        for entry in iteration_series
        if isinstance(entry.get("iteration"), int) and bool(entry.get("is_snapshot"))
    }
    full_payloads: dict[int, dict[str, Any]] = {}
    best_fit_score = float(state.best_fit_score) if math.isfinite(float(state.best_fit_score)) else -math.inf
    terminal_reason: str | None = None
    require_real_closed_loop = apply_lmat and capture_screen_after_apply
    snapshot_interval = int(analysis_performance["snapshot_interval"])
    keep_last_n_artifacts = int(analysis_performance["keep_last_n_artifacts"])
    multiview_workers = analysis_performance["multiview_workers"]
    evaluation_batch_size = int(analysis_performance["evaluation_batch_size"])
    evaluation_workers_requested = int(analysis_performance["evaluation_workers"])
    evaluation_parallel_safe = bool(analysis_performance["evaluation_parallel_safe"])
    research_metrics_profile_setting = str(analysis_performance["research_metrics_profile"])
    full_rerank_top_k = int(analysis_performance["full_rerank_top_k"])
    best_full_validation = bool(analysis_performance["best_full_validation"])
    target_full_validation = bool(analysis_performance["target_full_validation"])
    stability_validation_repeats = int(analysis_performance["stability_validation_repeats"])
    stability_validation_mode = str(analysis_performance["stability_validation_mode"])
    stability_validation_score_policy = str(analysis_performance["stability_validation_score_policy"])
    stability_validation_top_k = int(analysis_performance["stability_validation_top_k"])
    stability_validation_batch_chunk_size = int(analysis_performance["stability_validation_batch_chunk_size"])
    stability_validation_restart_renderer = bool(analysis_performance["stability_validation_restart_renderer"])
    stability_score_drift_threshold = float(analysis_performance["stability_score_drift_threshold"])
    stability_foreground_abs_threshold = float(analysis_performance["stability_foreground_abs_threshold"])
    stability_foreground_ratio_threshold = float(analysis_performance["stability_foreground_ratio_threshold"])
    stability_canonical_foreground_signature = analysis_performance.get("stability_canonical_foreground_signature")
    fast_score_only_allowed = (
        bool(analysis_performance["fast_score_only"])
        and optimizer in ("cma_cold", "cma_warm", "cold_start_hybrid")
        and fit_score_mode in ("research", "perceptual")
    )
    if effective_target_score is None:
        effective_target_score = _effective_target_score(target_score, score_ceiling)
    editor_capture_cfg = config.get("laya_editor_capture") if isinstance(config.get("laya_editor_capture"), dict) else {}
    driver_is_dry_run = bool(getattr(driver, "dry_run", False))
    renderer_parallel_safe = bool(getattr(driver, "parallel_safe", False))
    renderer_worker_count_value = getattr(driver, "worker_count", None)
    renderer_worker_count = max(1, int(renderer_worker_count_value or 1))
    renderer_has_worker_pool = renderer_parallel_safe and renderer_worker_count_value is not None and renderer_worker_count > 1
    evaluation_cache_enabled = not (
        apply_lmat
        or capture_screen_after_apply
        or bool(editor_capture_cfg.get("enabled"))
        or focus_callback is not None
    )
    evaluation_cache: dict[str, dict[str, Any]] = {}
    evaluation_cache_lock = threading.Lock()
    parallel_disabled_reason = ""
    if evaluation_workers_requested <= 1:
        parallel_disabled_reason = "evaluation_workers<=1"
    elif apply_lmat:
        parallel_disabled_reason = "apply_lmat_writes_shared_material"
    elif capture_screen_after_apply:
        parallel_disabled_reason = "screen_capture_uses_shared_viewport"
    elif bool(editor_capture_cfg.get("enabled")):
        parallel_disabled_reason = "laya_editor_capture_uses_shared_command_file"
    elif focus_callback is not None:
        parallel_disabled_reason = "focus_callback_controls_shared_window"
    elif not (evaluation_parallel_safe or renderer_parallel_safe or driver_is_dry_run):
        parallel_disabled_reason = "renderer_not_marked_parallel_safe"
    if parallel_disabled_reason:
        effective_evaluation_workers = 1
    else:
        effective_evaluation_workers = min(evaluation_workers_requested, evaluation_batch_size)
        if renderer_has_worker_pool:
            effective_evaluation_workers = min(effective_evaluation_workers, renderer_worker_count)
    analysis_pipeline_enabled = (
        effective_evaluation_workers <= 1
        and evaluation_workers_requested > 1
        and evaluation_batch_size > 1
        and not evaluation_cache_enabled
    )
    analysis_pipeline_workers = (
        min(evaluation_workers_requested, evaluation_batch_size) if analysis_pipeline_enabled else 1
    )

    def _base_timing(iteration: int) -> dict[str, Any]:
        is_snapshot = _is_snapshot_iteration(iteration, snapshot_interval)
        research_metrics_profile = _research_metrics_profile_for_iteration(
            research_metrics_profile_setting,
            is_snapshot=is_snapshot,
        )
        return {
            "snapshot_interval": snapshot_interval,
            "is_snapshot": is_snapshot,
            "perceptual_optional_enabled": is_snapshot,
            "diff_visual_enabled": is_snapshot,
            "keep_last_n_artifacts": keep_last_n_artifacts,
            "multiview_workers": multiview_workers,
            "evaluation_batch_size": evaluation_batch_size,
            "evaluation_workers": effective_evaluation_workers,
            "evaluation_workers_requested": evaluation_workers_requested,
            "evaluation_parallel_safe": evaluation_parallel_safe,
            "renderer_parallel_safe": renderer_parallel_safe,
            "renderer_worker_count": renderer_worker_count,
            "research_metrics_profile": research_metrics_profile,
            "fast_score_only_enabled": fast_score_only_allowed and research_metrics_profile == "fast",
            "full_rerank_top_k": full_rerank_top_k,
            "best_full_validation": best_full_validation,
            "target_full_validation": target_full_validation,
            "evaluation_mode": "cma_batch_parallel" if effective_evaluation_workers > 1 else "cma_batch_sequential",
            **(
                {"evaluation_parallel_disabled_reason": parallel_disabled_reason}
                if parallel_disabled_reason and evaluation_workers_requested > 1
                else {}
            ),
        }

    def _analyze_override(
        *,
        iteration_dir: Path,
        candidate_override: str | dict[str, str] | None,
        timing: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], float, float, dict[str, Any]]:
        timing_step = time.perf_counter()
        image_pairs = _collect_image_pairs(
            config,
            project_root,
            output_dir,
            candidate_override=candidate_override,
        )
        timing["collect_image_pairs_ms"] = _elapsed_ms(timing_step)
        if not image_pairs:
            raise ImagePairCollectionError(
                "No image_pairs/reference_images configured and no auto reference/candidate pair found."
            )

        timing_step = time.perf_counter()
        multiview_result = analyze_multiview_pairs(
            image_pairs,
            iteration_dir / "image_analysis",
            fit_score_mode=fit_score_mode,
            aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            compute_perceptual_optional=bool(timing["perceptual_optional_enabled"]),
            generate_diff_image=bool(timing["diff_visual_enabled"]),
            research_metrics_profile=str(timing["research_metrics_profile"]),
            workers=multiview_workers,
            fast_score_only=bool(timing["fast_score_only_enabled"]),
            write_report=not (
                bool(timing["fast_score_only_enabled"])
                and not bool(timing["is_snapshot"])
            ),
        )
        timing["analyze_multiview_ms"] = _elapsed_ms(timing_step)
        multiview_analysis = (
            multiview_result.get("multiview_analysis")
            if isinstance(multiview_result.get("multiview_analysis"), dict)
            else {}
        )
        multiview_summary = multiview_analysis.get("summary") if isinstance(multiview_analysis.get("summary"), dict) else {}
        analysis = dict(multiview_result.get("strategy_analysis") if isinstance(multiview_result.get("strategy_analysis"), dict) else {})
        diff_score = _number_or_default(multiview_summary.get("mean_diff_score"), math.inf)
        fit_score = _number_or_default(
            multiview_summary.get("optimization_fit_score"),
            _number_or_default(multiview_summary.get("mean_fit_score"), -math.inf),
        )
        if not analysis:
            analysis = {"status": "pending", "score": diff_score, "multiview": multiview_analysis}
        analysis["score"] = diff_score
        analysis["fit_score"] = fit_score
        analysis["optimization_fit_score"] = fit_score
        analysis["optimization_fit_score_source"] = multiview_summary.get("optimization_fit_score_source")
        analysis["multiview"] = multiview_analysis
        return image_pairs, image_pairs[0], analysis, diff_score, fit_score, multiview_analysis

    def _analysis_from_multiview_result(
        multiview_result: dict[str, Any],
    ) -> tuple[dict[str, Any], float, float, dict[str, Any]]:
        multiview_analysis = (
            multiview_result.get("multiview_analysis")
            if isinstance(multiview_result.get("multiview_analysis"), dict)
            else {}
        )
        multiview_summary = multiview_analysis.get("summary") if isinstance(multiview_analysis.get("summary"), dict) else {}
        analysis = dict(multiview_result.get("strategy_analysis") if isinstance(multiview_result.get("strategy_analysis"), dict) else {})
        diff_score = _number_or_default(multiview_summary.get("mean_diff_score"), math.inf)
        fit_score = _number_or_default(
            multiview_summary.get("optimization_fit_score"),
            _number_or_default(multiview_summary.get("mean_fit_score"), -math.inf),
        )
        if not analysis:
            analysis = {"status": "pending", "score": diff_score, "multiview": multiview_analysis}
        analysis["score"] = diff_score
        analysis["fit_score"] = fit_score
        analysis["optimization_fit_score"] = fit_score
        analysis["optimization_fit_score_source"] = multiview_summary.get("optimization_fit_score_source")
        analysis["multiview"] = multiview_analysis
        return analysis, diff_score, fit_score, multiview_analysis

    def _render_candidate(
        *,
        iteration: int,
        iteration_dir: Path,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        timing: dict[str, Any],
    ) -> tuple[Path, str, dict[str, Any], dict[str, Any] | None, str | dict[str, str] | None]:
        candidate_dir = iteration_dir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        params_path = candidate_dir / "params.json"
        timing_step = time.perf_counter()
        _write_json(params_path, next_params)
        candidate_lmat_path = ""
        if write_candidate_lmat or apply_lmat:
            candidate_lmat_path = str(candidate_dir / laya_material_path.name)
            lmat_io.write_candidate_lmat(
                laya_material_path,
                candidate_lmat_path,
                next_params,
                allow_missing_keys=True,
            )
        timing["write_candidate_ms"] = _elapsed_ms(timing_step)

        focus_log: list[dict[str, Any]] = []
        if apply_lmat:
            if focus_callback is not None:
                focus_log.append(focus_callback(f"iter_{iteration:04d}_before_lmat_write"))
            backup_path = lmat_io.backup_lmat(
                laya_material_path,
                suffix=f".auto_adjust_{iteration:04d}.bak",
                target_dir=external_backup_dir,
            )
            lmat_io.write_candidate_lmat(
                laya_material_path,
                laya_material_path,
                next_params,
                allow_missing_keys=True,
            )
            decision["applied_lmat"] = str(laya_material_path)
            decision["backup_lmat"] = str(backup_path)

        timing_step = time.perf_counter()
        try:
            editor_capture_result = trigger_editor_multiview_capture(
                config=config,
                project_root=project_root,
                iteration_dir=iteration_dir / "candidate",
                iteration=iteration,
                laya_material_path=laya_material_path,
            )
        except LayaEditorCaptureError as exc:
            editor_capture_result = {
                "status": "failed",
                "error": str(exc),
                "screenshots": [],
            }
        if editor_capture_result is not None:
            render_result = editor_capture_result
        else:
            render_result = driver.capture_candidate(iteration, next_params) if use_capture else driver.render_candidate(iteration, next_params)
        timing["candidate_capture_ms"] = _elapsed_ms(timing_step)

        candidate_override: str | dict[str, str] | None = None
        screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
        candidate_overrides = render_result.get("candidate_overrides") if isinstance(render_result, dict) else None
        if isinstance(candidate_overrides, dict) and candidate_overrides:
            candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}
        elif screenshots:
            candidate_override = str(screenshots[0])

        screen_capture_result: dict[str, Any] | None = None
        if capture_screen_after_apply:
            timing_step = time.perf_counter()
            if not apply_lmat:
                decision["screen_capture_after_apply_skipped"] = "requires --apply-lmat because this mode verifies the real .lmat write path"
            else:
                screen_capture_cfg = config.get("screen_capture", {}) if isinstance(config.get("screen_capture"), dict) else {}
                capture_dir = _resolve_path(project_root, screen_capture_cfg.get("capture_dir", str(DEFAULT_CAPTURE_DIR)))
                state_file_value = screen_capture_cfg.get("state_file")
                state_file = _resolve_path(project_root, state_file_value) if state_file_value else capture_dir / ".capture_region.json"
                region_text = screen_capture_region or str(screen_capture_cfg.get("region", ""))
                explicit_region = parse_region(region_text) if region_text else None
                wait_cfg = config.get("dynamic_rerender_wait", {}) if isinstance(config.get("dynamic_rerender_wait"), dict) else {}
                dynamic_wait_enabled = bool(wait_cfg.get("enabled", True))
                if dynamic_wait_enabled and rerender_wait_ms > 0:
                    wait_payload = _wait_for_visual_refresh(
                        previous_candidate_path=None,
                        max_wait_ms=rerender_wait_ms,
                        interval_ms=int(wait_cfg.get("interval_ms", 200)),
                        min_wait_ms=int(wait_cfg.get("min_wait_ms", 250)),
                        diff_threshold=float(wait_cfg.get("diff_threshold", 0.25)),
                        capture_dir=capture_dir,
                        region=explicit_region,
                        reuse_last=explicit_region is None,
                        state_file=state_file,
                        anchor=_build_capture_anchor(config),
                        focus_callback=focus_callback,
                    )
                    decision["dynamic_rerender_wait"] = wait_payload
                    if not wait_payload.get("changed"):
                        time.sleep(max(rerender_wait_ms - int(wait_payload.get("elapsed_ms", 0)), 0) / 1000.0)
                elif rerender_wait_ms > 0:
                    time.sleep(rerender_wait_ms / 1000.0)
                if focus_callback is not None:
                    focus_log.append(focus_callback(f"iter_{iteration:04d}_before_capture"))
                max_keep_raw = (
                    screen_capture_max_keep
                    if screen_capture_max_keep is not None
                    else screen_capture_cfg.get("max_keep")
                )
                try:
                    max_keep_int = int(max_keep_raw) if max_keep_raw is not None else 30
                except (TypeError, ValueError):
                    max_keep_int = 30
                effective_max_keep: int | None = max_keep_int if max_keep_int > 0 else None
                screen_capture_result = capture_laya_region(
                    region=explicit_region,
                    reuse_last=explicit_region is None,
                    capture_dir=capture_dir,
                    state_file=state_file,
                    prefix=str(screen_capture_cfg.get("prefix", DEFAULT_PREFIX)),
                    dry_run=False,
                    anchor=_build_capture_anchor(config),
                    max_keep=effective_max_keep,
                )
                candidate_override = str(screen_capture_result["output_path"])
            timing["screen_capture_after_apply_ms"] = _elapsed_ms(timing_step)
        if focus_log:
            decision["focus_log"] = focus_log
        return params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override

    context_timing = _base_timing(state.iteration)
    context_override: str | dict[str, str] | None = None
    initial_editor_capture_result: dict[str, Any] | None = None
    context_browser_score_result: dict[str, Any] | None = None
    initial_context_render_result: dict[str, Any] | None = None
    timing_step = time.perf_counter()
    try:
        initial_editor_capture_result = trigger_editor_multiview_capture(
            config=config,
            project_root=project_root,
            iteration_dir=auto_dir / "batch_context",
            iteration=state.iteration,
            laya_material_path=laya_material_path,
        )
    except LayaEditorCaptureError as exc:
        initial_editor_capture_result = {
            "status": "failed",
            "error": str(exc),
            "screenshots": [],
        }
    context_timing["initial_editor_capture_ms"] = _elapsed_ms(timing_step)
    if initial_editor_capture_result is not None:
        candidate_overrides = initial_editor_capture_result.get("candidate_overrides")
        screenshots = initial_editor_capture_result.get("screenshots", [])
        if isinstance(candidate_overrides, dict) and candidate_overrides:
            context_override = {str(key): str(value) for key, value in candidate_overrides.items()}
        elif screenshots:
            context_override = str(screenshots[0])

    if context_override is None and _browser_score_context_render_enabled(config):
        context_iteration = _context_render_iteration(state.iteration)
        timing_step = time.perf_counter()
        try:
            initial_context_render_result = driver.render_candidate(context_iteration, current_params)
        except Exception as exc:  # noqa: BLE001
            initial_context_render_result = {"status": "failed", "error": str(exc), "screenshots": []}
        context_timing["initial_context_render_ms"] = _elapsed_ms(timing_step)
        context_timing["initial_context_render_iteration"] = context_iteration
        context_timing["initial_context_render_status"] = initial_context_render_result.get("status")
        if _extract_browser_score_payload(initial_context_render_result) is not None:
            context_browser_score_result = copy.deepcopy(initial_context_render_result)
            context_timing["initial_context_browser_score_used"] = True
        else:
            context_timing["initial_context_browser_score_used"] = False
            candidate_overrides = initial_context_render_result.get("candidate_overrides")
            screenshots = initial_context_render_result.get("screenshots", [])
            if isinstance(candidate_overrides, dict) and candidate_overrides:
                context_override = {str(key): str(value) for key, value in candidate_overrides.items()}
            elif screenshots:
                context_override = str(screenshots[0])

    if context_browser_score_result is not None:
        score_payload = _browser_score_analysis_payload(context_browser_score_result, config=config)
        context_image_pairs = score_payload["image_pairs"]
        context_pair = score_payload["pair"]
        context_analysis = score_payload["analysis"]
        context_diff_score = score_payload["diff_score"]
        context_fit_score = score_payload["fit_score"]
        context_multiview = score_payload["multiview_analysis"]
        context_timing["collect_image_pairs_ms"] = 0.0
        context_timing["analyze_multiview_ms"] = 0.0
        context_timing["browser_score_used"] = True
        context_timing["browser_score_metric"] = context_multiview.get("summary", {}).get("metric")
    else:
        try:
            context_image_pairs, context_pair, context_analysis, context_diff_score, context_fit_score, context_multiview = _analyze_override(
                iteration_dir=auto_dir / "batch_context",
                candidate_override=context_override,
                timing=context_timing,
            )
        except ImagePairCollectionError as exc:
            payload = {
                "status": "pending",
                "reason": str(exc),
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

    best_fit_score = context_fit_score
    state.best_fit_score = context_fit_score
    state.best_fit_params = dict(current_params)
    state.best_score = context_diff_score
    state.best_params = dict(current_params)

    context_stop_reason = _target_stop_reason(
        context_fit_score,
        target_score=target_score,
        score_ceiling=score_ceiling,
    )
    if context_stop_reason:
        iteration = state.iteration
        iteration_payload = {
            "iteration": iteration,
            "input_pair": context_pair,
            "input_pairs": [context_pair],
            "diff_score_before": context_diff_score,
            "fit_score_before": context_fit_score,
            "scored_params": copy.deepcopy(current_params),
            "score_params_role": "batch_context",
            "target_score": target_score,
            "effective_target_score": effective_target_score,
            "score_ceiling": copy.deepcopy(score_ceiling),
            "selected_stage": context_stop_reason,
            "decision": {"stop_reason": context_stop_reason},
            "perceptual_signals": _extract_perceptual_signals(context_analysis),
            "multiview_analysis": context_multiview,
            "initial_editor_capture_result": initial_editor_capture_result,
            "timing": {**context_timing, "iteration_total_ms": 0.0},
        }
        _record_iteration_outputs(
            auto_dir=auto_dir,
            iteration_payload=iteration_payload,
            result_iterations=result_iterations,
            iteration_series=iteration_series,
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            is_snapshot=True,
            is_best=True,
        )
        terminal_reason = context_stop_reason

    def _cache_key_for_candidate(iteration: int, next_params: dict[str, Any]) -> str:
        timing = _base_timing(iteration)
        return _candidate_evaluation_cache_key(
            next_params,
            fit_score_mode=fit_score_mode,
            research_metrics_profile=str(timing["research_metrics_profile"]),
            perceptual_optional_enabled=bool(timing["perceptual_optional_enabled"]),
            diff_visual_enabled=bool(timing["diff_visual_enabled"]),
            fast_score_only_enabled=bool(timing["fast_score_only_enabled"]),
        )

    def _cache_payload(cache_key: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "cache_key": cache_key,
            "source_iteration": int(record["iteration"]),
            "render_result": copy.deepcopy(record["render_result"]),
            "image_pairs": copy.deepcopy(record["image_pairs"]),
            "pair": copy.deepcopy(record["pair"]),
            "analysis": copy.deepcopy(record["analysis"]),
            "diff_score": float(record["diff_score"]),
            "fit_score": float(record["fit_score"]),
            "multiview_analysis": copy.deepcopy(record["multiview_analysis"]),
        }

    context_cache_key = _candidate_evaluation_cache_key(
        current_params,
        fit_score_mode=fit_score_mode,
        research_metrics_profile=str(context_timing["research_metrics_profile"]),
        perceptual_optional_enabled=bool(context_timing["perceptual_optional_enabled"]),
        diff_visual_enabled=bool(context_timing["diff_visual_enabled"]),
        fast_score_only_enabled=bool(context_timing["fast_score_only_enabled"]),
    )
    context_render_result = (
        copy.deepcopy(context_browser_score_result)
        if isinstance(context_browser_score_result, dict)
        else copy.deepcopy(initial_context_render_result)
        if isinstance(initial_context_render_result, dict)
        else copy.deepcopy(initial_editor_capture_result)
        if isinstance(initial_editor_capture_result, dict)
        else {"status": "batch_context", "screenshots": []}
    )
    context_render_result.setdefault("status", "batch_context")
    context_cache_payload = _cache_payload(
        context_cache_key,
        {
            "iteration": state.iteration,
            "render_result": context_render_result,
            "image_pairs": context_image_pairs,
            "pair": context_pair,
            "analysis": context_analysis,
            "diff_score": context_diff_score,
            "fit_score": context_fit_score,
            "multiview_analysis": context_multiview,
        },
    )
    if evaluation_cache_enabled:
        evaluation_cache[context_cache_key] = context_cache_payload
    batch_context_summary = {
        "fit_score": context_fit_score,
        "diff_score": context_diff_score,
        "score_params_role": "batch_context",
        "timing": copy.deepcopy(context_timing),
    }

    def _cached_batch_candidate_record(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
        cache_key: str,
        cached: dict[str, Any],
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        candidate_dir = iteration_dir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        timing_step = time.perf_counter()
        params_path = candidate_dir / "params.json"
        _write_json(params_path, next_params)
        candidate_lmat_path = ""
        if write_candidate_lmat:
            candidate_lmat_path = str(candidate_dir / laya_material_path.name)
            lmat_io.write_candidate_lmat(
                laya_material_path,
                candidate_lmat_path,
                next_params,
                allow_missing_keys=True,
            )
        timing["write_candidate_ms"] = _elapsed_ms(timing_step)
        timing["candidate_capture_ms"] = 0.0
        timing["collect_image_pairs_ms"] = 0.0
        timing["analyze_multiview_ms"] = 0.0
        timing["candidate_evaluation_cache_hit"] = True
        timing["candidate_evaluation_cache_key"] = cache_key
        timing["candidate_evaluation_cache_source_iteration"] = int(cached["source_iteration"])
        timing["iteration_total_ms"] = _elapsed_ms(iteration_started)
        return {
            "batch_index": batch_index,
            "iteration": iteration,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": {
                "status": "cached_evaluation",
                "cache_key": cache_key,
                "source_iteration": int(cached["source_iteration"]),
                "source_render_result": copy.deepcopy(cached.get("render_result")),
            },
            "screen_capture_result": None,
            "image_pairs": copy.deepcopy(cached["image_pairs"]),
            "pair": copy.deepcopy(cached["pair"]),
            "analysis": copy.deepcopy(cached["analysis"]),
            "diff_score": float(cached["diff_score"]),
            "fit_score": float(cached["fit_score"]),
            "multiview_analysis": copy.deepcopy(cached["multiview_analysis"]),
            "timing": timing,
        }

    def _evaluate_batch_candidate(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        cache_key = _cache_key_for_candidate(iteration, next_params)
        if cache_key == context_cache_key:
            return _cached_batch_candidate_record(
                batch_index=batch_index,
                batch_size=batch_size,
                iteration=iteration,
                next_params=next_params,
                decision=decision,
                batch_propose_ms=batch_propose_ms,
                cache_key=cache_key,
                cached=context_cache_payload,
            )
        if evaluation_cache_enabled:
            with evaluation_cache_lock:
                cached = evaluation_cache.get(cache_key)
            if cached is not None:
                return _cached_batch_candidate_record(
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=iteration,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                    cache_key=cache_key,
                    cached=cached,
                )
        timing["candidate_evaluation_cache_hit"] = False
        timing["candidate_evaluation_cache_key"] = cache_key
        params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override = _render_candidate(
            iteration=iteration,
            iteration_dir=iteration_dir,
            next_params=next_params,
            decision=decision,
            timing=timing,
        )
        if _extract_browser_score_payload(render_result) is not None:
            score_payload = _browser_score_analysis_payload(render_result, config=config)
            image_pairs = score_payload["image_pairs"]
            pair = score_payload["pair"]
            analysis = score_payload["analysis"]
            diff_score = score_payload["diff_score"]
            fit_score = score_payload["fit_score"]
            multiview_analysis = score_payload["multiview_analysis"]
            timing["collect_image_pairs_ms"] = 0.0
            timing["analyze_multiview_ms"] = 0.0
            timing["browser_score_used"] = True
            timing["browser_score_metric"] = multiview_analysis.get("summary", {}).get("metric")
        else:
            image_pairs, pair, analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                iteration_dir=iteration_dir,
                candidate_override=candidate_override,
                timing=timing,
            )
        timing["iteration_total_ms"] = _elapsed_ms(iteration_started)
        record = {
            "batch_index": batch_index,
            "iteration": iteration,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "screen_capture_result": screen_capture_result,
            "image_pairs": image_pairs,
            "pair": pair,
            "analysis": analysis,
            "diff_score": diff_score,
            "fit_score": fit_score,
            "multiview_analysis": multiview_analysis,
            "timing": timing,
        }
        if evaluation_cache_enabled:
            with evaluation_cache_lock:
                evaluation_cache.setdefault(cache_key, _cache_payload(cache_key, record))
        return record

    def _render_batch_candidate_for_analysis_pipeline(
        *,
        batch_index: int,
        batch_size: int,
        iteration: int,
        next_params: dict[str, Any],
        decision: dict[str, Any],
        batch_propose_ms: float,
    ) -> dict[str, Any]:
        iteration_started = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        timing = _base_timing(iteration)
        timing["evaluation_batch_index"] = batch_index
        timing["evaluation_batch_count"] = batch_size
        timing["strategy_propose_ms"] = batch_propose_ms if batch_index == 0 else 0.0
        timing["candidate_evaluation_cache_hit"] = False
        timing["candidate_evaluation_cache_key"] = _cache_key_for_candidate(iteration, next_params)
        timing["evaluation_mode"] = "cma_batch_render_analysis_pipeline"
        timing["analysis_pipeline_enabled"] = True
        timing["analysis_pipeline_workers"] = min(analysis_pipeline_workers, batch_size)
        params_path, candidate_lmat_path, render_result, screen_capture_result, candidate_override = _render_candidate(
            iteration=iteration,
            iteration_dir=iteration_dir,
            next_params=next_params,
            decision=decision,
            timing=timing,
        )
        return {
            "batch_index": batch_index,
            "iteration": iteration,
            "iteration_started": iteration_started,
            "iteration_dir": iteration_dir,
            "next_params": next_params,
            "decision": decision,
            "params_path": params_path,
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "screen_capture_result": screen_capture_result,
            "candidate_override": candidate_override,
            "timing": timing,
        }

    def _finish_analysis_pipeline_candidate(rendered: dict[str, Any]) -> dict[str, Any]:
        timing = rendered["timing"]
        render_result = rendered["render_result"]
        if _extract_browser_score_payload(render_result) is not None:
            score_payload = _browser_score_analysis_payload(render_result, config=config)
            image_pairs = score_payload["image_pairs"]
            pair = score_payload["pair"]
            analysis = score_payload["analysis"]
            diff_score = score_payload["diff_score"]
            fit_score = score_payload["fit_score"]
            multiview_analysis = score_payload["multiview_analysis"]
            timing["collect_image_pairs_ms"] = 0.0
            timing["analyze_multiview_ms"] = 0.0
            timing["browser_score_used"] = True
            timing["browser_score_metric"] = multiview_analysis.get("summary", {}).get("metric")
        else:
            image_pairs, pair, analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                iteration_dir=rendered["iteration_dir"],
                candidate_override=rendered["candidate_override"],
                timing=timing,
            )
        timing["iteration_total_ms"] = _elapsed_ms(float(rendered["iteration_started"]))
        return {
            "batch_index": rendered["batch_index"],
            "iteration": rendered["iteration"],
            "next_params": rendered["next_params"],
            "decision": rendered["decision"],
            "params_path": rendered["params_path"],
            "candidate_lmat_path": rendered["candidate_lmat_path"],
            "render_result": rendered["render_result"],
            "screen_capture_result": rendered["screen_capture_result"],
            "image_pairs": image_pairs,
            "pair": pair,
            "analysis": analysis,
            "diff_score": diff_score,
            "fit_score": fit_score,
            "multiview_analysis": multiview_analysis,
            "timing": timing,
        }

    def _evaluate_batch_records_with_analysis_pipeline(
        proposals: list[tuple[dict[str, Any], dict[str, Any]]],
        *,
        batch_size: int,
        first_iteration: int,
        batch_propose_ms: float,
    ) -> list[dict[str, Any]]:
        records_by_index: dict[int, dict[str, Any]] = {}
        max_workers = max(1, min(analysis_pipeline_workers, batch_size))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="candidate-analysis") as executor:
            futures = {}
            for batch_index, (next_params, decision) in enumerate(proposals):
                cache_key = _cache_key_for_candidate(first_iteration + batch_index, next_params)
                if cache_key == context_cache_key:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=context_cache_payload,
                    )
                    continue
                rendered = _render_batch_candidate_for_analysis_pipeline(
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=first_iteration + batch_index,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                )
                if rendered.get("candidate_override") is None and require_real_closed_loop:
                    timing = rendered["timing"]
                    timing["evaluation_mode"] = "cma_batch_sequential"
                    timing["analysis_pipeline_enabled"] = False
                    timing["analysis_pipeline_skipped"] = "missing_candidate_override"
                    records_by_index[batch_index] = _finish_analysis_pipeline_candidate(rendered)
                    continue
                futures[executor.submit(_finish_analysis_pipeline_candidate, rendered)] = batch_index
            for future in as_completed(futures):
                batch_index = futures[future]
                records_by_index[batch_index] = future.result()
        return [records_by_index[index] for index in range(batch_size)]

    def _evaluate_batch_records(
        proposals: list[tuple[dict[str, Any], dict[str, Any]]],
        *,
        batch_size: int,
        first_iteration: int,
        batch_propose_ms: float,
    ) -> list[dict[str, Any]]:
        records_by_index: dict[int, dict[str, Any]] = {}
        max_workers = min(effective_evaluation_workers, batch_size)
        cache_keys: dict[int, str] = {
            batch_index: _cache_key_for_candidate(first_iteration + batch_index, next_params)
            for batch_index, (next_params, _decision) in enumerate(proposals)
        }
        first_index_by_cache_key: dict[str, int] = {}
        duplicate_source_by_index: dict[int, int] = {}
        scheduled_unique_indices: set[int] = set()

        if evaluation_cache_enabled:
            for batch_index, (next_params, decision) in enumerate(proposals):
                cache_key = cache_keys[batch_index]
                if cache_key == context_cache_key:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=context_cache_payload,
                    )
                    continue
                with evaluation_cache_lock:
                    cached = evaluation_cache.get(cache_key)
                if cached is not None:
                    records_by_index[batch_index] = _cached_batch_candidate_record(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                        cache_key=cache_key,
                        cached=cached,
                    )
                    continue
                source_index = first_index_by_cache_key.get(cache_key)
                if source_index is not None:
                    duplicate_source_by_index[batch_index] = source_index
                    continue
                first_index_by_cache_key[cache_key] = batch_index
                scheduled_unique_indices.add(batch_index)
        else:
            scheduled_unique_indices = set(range(batch_size))

        def _submit_wave(
            executor: ThreadPoolExecutor,
            wave: list[tuple[int, tuple[dict[str, Any], dict[str, Any]]]],
        ) -> None:
            if not wave:
                return
            futures = {
                executor.submit(
                    _evaluate_batch_candidate,
                    batch_index=batch_index,
                    batch_size=batch_size,
                    iteration=first_iteration + batch_index,
                    next_params=next_params,
                    decision=decision,
                    batch_propose_ms=batch_propose_ms,
                ): batch_index
                for batch_index, (next_params, decision) in wave
            }
            for future in as_completed(futures):
                batch_index = futures[future]
                records_by_index[batch_index] = future.result()

        def _materialize_duplicate(batch_index: int) -> None:
            if batch_index in records_by_index:
                return
            cache_key = cache_keys[batch_index]
            with evaluation_cache_lock:
                cached = evaluation_cache.get(cache_key)
            if cached is None:
                source_index = duplicate_source_by_index[batch_index]
                source_record = records_by_index.get(source_index)
                if source_record is None:
                    raise RuntimeError(
                        "Duplicate candidate cache source was not evaluated: "
                        f"source batch index {source_index}, duplicate batch index {batch_index}"
                    )
                cached = _cache_payload(cache_key, source_record)
                with evaluation_cache_lock:
                    cached = evaluation_cache.setdefault(cache_key, cached)
            next_params, decision = proposals[batch_index]
            records_by_index[batch_index] = _cached_batch_candidate_record(
                batch_index=batch_index,
                batch_size=batch_size,
                iteration=first_iteration + batch_index,
                next_params=next_params,
                decision=decision,
                batch_propose_ms=batch_propose_ms,
                cache_key=cache_key,
                cached=cached,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            if renderer_has_worker_pool:
                for start in range(0, batch_size, max_workers):
                    end = min(start + max_workers, batch_size)
                    wave = [
                        (batch_index, proposals[batch_index])
                        for batch_index in range(start, end)
                        if batch_index in scheduled_unique_indices
                    ]
                    _submit_wave(executor, wave)
                    for batch_index in range(start, end):
                        if batch_index in duplicate_source_by_index:
                            _materialize_duplicate(batch_index)
            else:
                wave = [
                    (batch_index, proposals[batch_index])
                    for batch_index in range(batch_size)
                    if batch_index in scheduled_unique_indices
                ]
                _submit_wave(executor, wave)
                for batch_index in range(batch_size):
                    if batch_index in duplicate_source_by_index:
                        _materialize_duplicate(batch_index)

        return [records_by_index[index] for index in range(batch_size)]

    def _full_rerank_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if full_rerank_top_k <= 0 or len(batch_records) <= 1:
            return
        eligible_records = [
            record
            for record in batch_records
            if str(record.get("timing", {}).get("research_metrics_profile") or "").lower() != "full"
        ]
        if not eligible_records:
            return
        top_records = sorted(
            eligible_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )[:full_rerank_top_k]
        selected_ids = {int(record["iteration"]) for record in top_records}
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["full_rerank_selected"] = int(record.get("iteration", -1)) in selected_ids
            timing["full_rerank_top_k"] = full_rerank_top_k
        for record in top_records:
            timing = record["timing"]
            source_fit_score = float(record["fit_score"])
            source_diff_score = float(record["diff_score"])
            timing["full_rerank_source_fit_score"] = source_fit_score
            timing["full_rerank_source_diff_score"] = source_diff_score
            timing["full_rerank_profile"] = "full"
            timing_step = time.perf_counter()
            iteration_dir = auto_dir / f"iter_{int(record['iteration']):04d}"
            multiview_result = analyze_multiview_pairs(
                record["image_pairs"],
                iteration_dir / "full_rerank",
                fit_score_mode=fit_score_mode,
                aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
                compute_perceptual_optional=False,
                generate_diff_image=False,
                research_metrics_profile="full",
                workers=multiview_workers,
            )
            timing["full_rerank_ms"] = _elapsed_ms(timing_step)
            analysis, diff_score, fit_score, multiview_analysis = _analysis_from_multiview_result(multiview_result)
            record["analysis"] = analysis
            record["diff_score"] = diff_score
            record["fit_score"] = fit_score
            record["multiview_analysis"] = multiview_analysis

    def _record_has_full_profile(record: dict[str, Any]) -> bool:
        timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
        return (
            str(timing.get("research_metrics_profile") or "").lower() == "full"
            or str(timing.get("full_rerank_profile") or "").lower() == "full"
            or str(timing.get("best_full_validation_profile") or "").lower() == "full"
            or str(timing.get("target_full_validation_profile") or "").lower() == "full"
        )

    def _full_validate_record(record: dict[str, Any], subdir_name: str) -> None:
        timing = record["timing"]
        timing_step = time.perf_counter()
        iteration_dir = auto_dir / f"iter_{int(record['iteration']):04d}"
        multiview_result = analyze_multiview_pairs(
            record["image_pairs"],
            iteration_dir / subdir_name,
            fit_score_mode=fit_score_mode,
            aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
            compute_perceptual_optional=False,
            generate_diff_image=False,
            research_metrics_profile="full",
            workers=multiview_workers,
        )
        timing[f"{subdir_name}_ms"] = _elapsed_ms(timing_step)
        analysis, diff_score, fit_score, multiview_analysis = _analysis_from_multiview_result(multiview_result)
        record["analysis"] = analysis
        record["diff_score"] = diff_score
        record["fit_score"] = fit_score
        record["multiview_analysis"] = multiview_analysis

    def _stability_validate_record(record: dict[str, Any], subdir_name: str) -> None:
        timing = record["timing"]
        timing["stability_validation_repeats"] = stability_validation_repeats
        timing["stability_validation_mode"] = stability_validation_mode
        timing["stability_validation_score_policy_config"] = stability_validation_score_policy
        timing["stability_validation_restart_renderer"] = stability_validation_restart_renderer
        timing["stability_validation_selected"] = False
        if stability_validation_repeats <= 1:
            return
        if isinstance(record.get("stability_validation"), dict):
            timing["stability_validation_skipped"] = "already_validated"
            return
        if apply_lmat or capture_screen_after_apply:
            timing["stability_validation_skipped"] = "mutating_apply_or_screen_capture_path"
            return

        timing["stability_validation_selected"] = True
        timing_step = time.perf_counter()
        original_iteration = int(record["iteration"])

        def _apply_fresh_oracle_summary(fresh_summary: dict[str, Any] | None) -> None:
            summary = _fresh_oracle_stability_summary(fresh_summary)
            record["stability_validation"] = summary
            timing["stability_validation_ms"] = _elapsed_ms(timing_step)
            timing["stability_validation_stable"] = bool(summary["stable"])
            timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
            timing["stability_validation_worst_foreground_weight_sum_spread"] = summary.get(
                "worst_foreground_weight_sum_spread"
            )
            timing["stability_validation_score_policy"] = summary["score_policy"]
            if summary["conservative_fit_score"] is not None:
                record["fit_score"] = float(summary["conservative_fit_score"])
            if summary["conservative_diff_score"] is not None:
                record["diff_score"] = float(summary["conservative_diff_score"])

        if stability_validation_mode == "fresh_oracle":
            validator = getattr(driver, "validate_persistent_oracle_stability", None)
            if callable(validator):
                output_subdir = str(
                    Path("auto_adjust")
                    / f"iter_{original_iteration:04d}"
                    / f"{subdir_name}_fresh_oracle"
                )
                fresh_summary = validator(
                    iteration=original_iteration + 1_000_000,
                    params=record["next_params"],
                    attempts=stability_validation_repeats,
                    output_subdir=output_subdir,
                )
                _apply_fresh_oracle_summary(fresh_summary)
                return
            timing["stability_validation_fresh_oracle_fallback"] = "driver_does_not_support_validation"

        samples = [_stability_sample_from_record(record, repeat_index=0, label="primary")]
        for repeat_index in range(1, stability_validation_repeats):
            validation_iteration = original_iteration + repeat_index * 1_000_000
            validation_dir = auto_dir / f"iter_{original_iteration:04d}" / f"{subdir_name}_repeat_{repeat_index:02d}"
            repeat_timing = _base_timing(validation_iteration)
            repeat_timing["stability_validation_repeat_index"] = repeat_index
            if stability_validation_restart_renderer:
                restart_payload = _restart_renderer_for_stability(repeat_index)
                timing.setdefault("stability_validation_restart_results", []).append(restart_payload)
            repeat_decision = copy.deepcopy(record["decision"])
            _params_path, _candidate_lmat_path, render_result, _screen_capture_result, candidate_override = _render_candidate(
                iteration=validation_iteration,
                iteration_dir=validation_dir,
                next_params=record["next_params"],
                decision=repeat_decision,
                timing=repeat_timing,
            )
            if _extract_browser_score_payload(render_result) is not None:
                score_payload = _browser_score_analysis_payload(render_result, config=config)
                diff_score = float(score_payload["diff_score"])
                fit_score = float(score_payload["fit_score"])
                multiview_analysis = score_payload["multiview_analysis"]
            else:
                screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
                if not candidate_override and not screenshots:
                    repeat_timing["stability_validation_render_failed"] = True
                    repeat_timing["stability_validation_render_status"] = (
                        render_result.get("status") if isinstance(render_result, dict) else None
                    )
                    if stability_validation_restart_renderer:
                        recovery_payload = _restart_renderer_for_stability(repeat_index)
                        recovery_payload["phase"] = "after_failed_stability_render"
                        timing.setdefault("stability_validation_restart_results", []).append(recovery_payload)
                    diff_score = 1.0
                    fit_score = 0.0
                    multiview_analysis = _failed_stability_multiview_analysis(render_result)
                else:
                    _image_pairs, _pair, _analysis, diff_score, fit_score, multiview_analysis = _analyze_override(
                        iteration_dir=validation_dir,
                        candidate_override=candidate_override,
                        timing=repeat_timing,
                    )
            samples.append(
                _stability_sample(
                    repeat_index=repeat_index,
                    label=f"repeat_{repeat_index:02d}",
                    fit_score=float(fit_score),
                    diff_score=float(diff_score),
                    multiview_analysis=multiview_analysis,
                    render_result=render_result,
                    timing=repeat_timing,
                )
            )

        summary = _stability_summary(samples)
        record["stability_validation"] = summary
        timing["stability_validation_ms"] = _elapsed_ms(timing_step)
        timing["stability_validation_stable"] = bool(summary["stable"])
        timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
        timing["stability_validation_worst_foreground_weight_sum_spread"] = summary[
            "worst_foreground_weight_sum_spread"
        ]
        timing["stability_validation_score_policy"] = "conservative_min"
        if summary["conservative_fit_score"] is not None:
            record["fit_score"] = float(summary["conservative_fit_score"])
        if summary["conservative_diff_score"] is not None:
            record["diff_score"] = float(summary["conservative_diff_score"])

    def _restart_renderer_for_stability(repeat_index: int) -> dict[str, Any]:
        reset_fn = getattr(driver, "reset_persistent_queue", None)
        if not callable(reset_fn):
            return {
                "repeat_index": repeat_index,
                "applied": False,
                "reason": "driver_does_not_support_reset",
            }
        timing_step = time.perf_counter()
        applied = bool(reset_fn())
        return {
            "repeat_index": repeat_index,
            "applied": applied,
            "elapsed_ms": _elapsed_ms(timing_step),
            **({} if applied else {"reason": "driver_reset_no_stop_command"}),
        }

    def _stability_sample_from_record(
        record: dict[str, Any],
        *,
        repeat_index: int,
        label: str,
    ) -> dict[str, Any]:
        return _stability_sample(
            repeat_index=repeat_index,
            label=label,
            fit_score=float(record["fit_score"]),
            diff_score=float(record["diff_score"]),
            multiview_analysis=record["multiview_analysis"],
            render_result=record["render_result"],
            timing=record["timing"],
        )

    def _stability_sample(
        *,
        repeat_index: int,
        label: str,
        fit_score: float,
        diff_score: float,
        multiview_analysis: dict[str, Any],
        render_result: dict[str, Any],
        timing: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "repeat_index": repeat_index,
            "label": label,
            "fit_score": fit_score,
            "diff_score": diff_score,
            "render_status": render_result.get("status") if isinstance(render_result, dict) else None,
            "candidate_capture_ms": timing.get("candidate_capture_ms"),
            "views": _stability_views(multiview_analysis),
        }

    def _stability_views(multiview_analysis: dict[str, Any]) -> list[dict[str, Any]]:
        raw_views = multiview_analysis.get("views") if isinstance(multiview_analysis, dict) else None
        if not isinstance(raw_views, list):
            return []
        views: list[dict[str, Any]] = []
        for item in raw_views:
            if not isinstance(item, dict):
                continue
            views.append(
                {
                    "view_id": str(item.get("view_id") or item.get("pair_id") or item.get("pair_index") or ""),
                    "fit_score": _optional_float_value(item.get("fit_score")),
                    "diff_score": _optional_float_value(item.get("diff_score")),
                    "foreground_weight_sum": _optional_float_value(item.get("foreground_weight_sum")),
                }
            )
        return views

    def _failed_stability_multiview_analysis(render_result: dict[str, Any] | None) -> dict[str, Any]:
        render_status = render_result.get("status") if isinstance(render_result, dict) else None
        return {
            "summary": {
                "mean_diff_score": 1.0,
                "mean_fit_score": 0.0,
                "optimization_fit_score": 0.0,
                "optimization_fit_score_source": "stability_render_failed",
                "metric": "stability_render_failed",
                "render_status": render_status,
            },
            "views": [],
            "source": "stability_render_failed",
        }

    def _fresh_oracle_stability_summary(fresh_summary: dict[str, Any] | None) -> dict[str, Any]:
        score_policy = f"fresh_oracle_{stability_validation_score_policy}"
        if not isinstance(fresh_summary, dict) or fresh_summary.get("status") != "ok":
            return {
                "stable": False,
                "sample_count": 0,
                "score_stable": False,
                "foreground_stable": None,
                "score_policy": score_policy,
                "fit_score_min": 0.0,
                "fit_score_max": None,
                "fit_score_median": None,
                "fit_score_mean": None,
                "fit_score_spread": None,
                "conservative_fit_score": 0.0,
                "conservative_diff_score": 1.0,
                "thresholds": {
                    "score_drift_threshold": stability_score_drift_threshold,
                    "foreground_abs_threshold": stability_foreground_abs_threshold,
                    "foreground_ratio_threshold": stability_foreground_ratio_threshold,
                },
                "fresh_oracle_summary": copy.deepcopy(fresh_summary),
            }

        spread = _optional_float_value(fresh_summary.get("fit_score_spread"))
        record_stability = _summarize_fresh_oracle_records(
            fresh_summary,
            score_drift_threshold=stability_score_drift_threshold,
            foreground_abs_threshold=stability_foreground_abs_threshold,
            foreground_ratio_threshold=stability_foreground_ratio_threshold,
            canonical_foreground_signature=stability_canonical_foreground_signature,
        )
        policy_summary = copy.deepcopy(fresh_summary)
        if isinstance(record_stability, dict):
            policy_summary.update(record_stability)
        score_stable = (
            bool(record_stability["score_stable"])
            if isinstance(record_stability, dict) and "score_stable" in record_stability
            else bool(spread is None or spread <= stability_score_drift_threshold)
        )
        foreground_stable = (
            record_stability.get("foreground_stable")
            if isinstance(record_stability, dict)
            else None
        )
        stable = bool(score_stable and foreground_stable is not False)
        selected_fit_score = _fresh_oracle_policy_value(policy_summary, "fit_score")
        selected_diff_score = _fresh_oracle_policy_value(
            policy_summary,
            "diff_score",
            allow_conservative_fallback=stability_validation_score_policy == "min",
        )
        if selected_diff_score is None and selected_fit_score is not None:
            selected_diff_score = max(0.0, 1.0 - selected_fit_score)
        return {
            "stable": stable,
            "sample_count": int(
                record_stability.get("sample_count")
                if isinstance(record_stability, dict) and record_stability.get("sample_count") is not None
                else fresh_summary.get("attempts_scored") or fresh_summary.get("attempts_completed") or 0
            ),
            "score_stable": score_stable,
            "foreground_stable": foreground_stable,
            "score_policy": score_policy,
            "fit_score_min": _optional_float_value(fresh_summary.get("fit_score_min")),
            "fit_score_max": _optional_float_value(fresh_summary.get("fit_score_max")),
            "fit_score_median": _optional_float_value(fresh_summary.get("fit_score_median")),
            "fit_score_mean": _optional_float_value(fresh_summary.get("fit_score_mean")),
            "fit_score_spread": spread,
            "conservative_fit_score": selected_fit_score,
            "conservative_diff_score": selected_diff_score,
            "worst_foreground_view_id": (
                record_stability.get("worst_foreground_view_id")
                if isinstance(record_stability, dict)
                else None
            ),
            "worst_foreground_weight_sum_spread": (
                record_stability.get("worst_foreground_weight_sum_spread")
                if isinstance(record_stability, dict)
                else None
            ),
            "worst_foreground_weight_sum_spread_ratio": (
                record_stability.get("worst_foreground_weight_sum_spread_ratio")
                if isinstance(record_stability, dict)
                else None
            ),
            "thresholds": {
                "score_drift_threshold": stability_score_drift_threshold,
                "foreground_abs_threshold": stability_foreground_abs_threshold,
                "foreground_ratio_threshold": stability_foreground_ratio_threshold,
            },
            "view_stats": copy.deepcopy(record_stability.get("view_stats")) if isinstance(record_stability, dict) else [],
            "foreground_modes": copy.deepcopy(record_stability.get("foreground_modes"))
            if isinstance(record_stability, dict)
            else [],
            "dominant_foreground_mode": copy.deepcopy(record_stability.get("dominant_foreground_mode"))
            if isinstance(record_stability, dict)
            else None,
            "canonical_foreground_signature": copy.deepcopy(record_stability.get("canonical_foreground_signature"))
            if isinstance(record_stability, dict)
            else copy.deepcopy(stability_canonical_foreground_signature),
            "canonical_foreground_mode": copy.deepcopy(record_stability.get("canonical_foreground_mode"))
            if isinstance(record_stability, dict)
            else None,
            "fresh_oracle_summary": copy.deepcopy(fresh_summary),
        }

    def _fresh_oracle_policy_value(
        fresh_summary: dict[str, Any],
        prefix: str,
        *,
        allow_conservative_fallback: bool = True,
    ) -> float | None:
        return _select_stability_policy_value(
            fresh_summary,
            prefix,
            stability_validation_score_policy,
            allow_conservative_fallback=allow_conservative_fallback,
        )

    def _stability_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
        return _summarize_stability_samples(
            samples,
            score_drift_threshold=stability_score_drift_threshold,
            foreground_abs_threshold=stability_foreground_abs_threshold,
            foreground_ratio_threshold=stability_foreground_ratio_threshold,
        )

    def _best_full_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        stability_enabled = stability_validation_repeats > 1
        if not best_full_validation and not stability_enabled:
            return
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["best_full_validation_selected"] = False

        confirmed_best_score = best_fit_score
        ranked_records = sorted(
            batch_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )
        for record in ranked_records:
            current_score = float(record.get("fit_score", -math.inf))
            if current_score <= confirmed_best_score:
                break
            timing = record["timing"]
            if not best_full_validation and target_full_validation:
                timing["best_stability_validation_skipped"] = "target_validation_enabled"
                continue
            if best_full_validation:
                timing["best_full_validation_source_fit_score"] = float(record["fit_score"])
                timing["best_full_validation_source_diff_score"] = float(record["diff_score"])
                if _record_has_full_profile(record):
                    timing["best_full_validation_skipped"] = "already_full_profile"
                else:
                    timing["best_full_validation_selected"] = True
                    timing["best_full_validation_profile"] = "full"
                    _full_validate_record(record, "best_full_validation")
            else:
                timing["best_full_validation_skipped"] = "disabled"
            if isinstance(record.get("stability_validation"), dict):
                timing["best_stability_validation_skipped"] = "already_validated"
            else:
                _stability_validate_record(record, "best_stability_validation")
            confirmed_best_score = max(confirmed_best_score, float(record["fit_score"]))

    def _top_k_stability_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if stability_validation_repeats <= 1 or stability_validation_top_k <= 0:
            return
        ranked_records = sorted(
            batch_records,
            key=lambda record: float(record.get("fit_score", -math.inf)),
            reverse=True,
        )
        selected_records = [
            record for record in ranked_records[:stability_validation_top_k]
            if not isinstance(record.get("stability_validation"), dict)
        ]
        if not selected_records:
            return
        for rank, record in enumerate(selected_records):
            timing = record["timing"]
            timing["stability_validation_top_k"] = stability_validation_top_k
            timing["stability_validation_batch_chunk_size"] = stability_validation_batch_chunk_size
            timing["stability_validation_top_k_selected"] = True
            timing["stability_validation_top_k_rank"] = rank
        batch_validator = getattr(driver, "validate_persistent_oracle_stability_many", None)
        if stability_validation_mode == "fresh_oracle" and callable(batch_validator):
            chunk_size = (
                stability_validation_batch_chunk_size
                if stability_validation_batch_chunk_size > 0
                else len(selected_records)
            )
            chunks = [
                selected_records[start : start + chunk_size]
                for start in range(0, len(selected_records), chunk_size)
            ]
            fallback_records: list[dict[str, Any]] = []
            for chunk_index, chunk_records in enumerate(chunks):
                timing_step = time.perf_counter()
                candidates = []
                for record in chunk_records:
                    candidate_id = f"iter_{int(record['iteration']):04d}"
                    candidates.append(
                        {
                            "candidate_id": candidate_id,
                            "params": copy.deepcopy(record["next_params"]),
                        }
                    )
                    record["timing"]["stability_validation_repeats"] = stability_validation_repeats
                    record["timing"]["stability_validation_mode"] = stability_validation_mode
                    record["timing"]["stability_validation_score_policy_config"] = stability_validation_score_policy
                    record["timing"]["stability_validation_restart_renderer"] = stability_validation_restart_renderer
                    record["timing"]["stability_validation_selected"] = True
                    record["timing"]["stability_validation_batch_candidate_id"] = candidate_id
                    record["timing"]["stability_validation_batch_chunk_index"] = chunk_index
                    record["timing"]["stability_validation_batch_chunk_count"] = len(chunks)
                output_path = (
                    Path("auto_adjust")
                    / f"iter_{int(chunk_records[0]['iteration']):04d}"
                    / "batch_top_k_stability_validation_fresh_oracle"
                )
                if len(chunks) > 1:
                    output_path = output_path / f"chunk_{chunk_index:02d}"
                batch_summary = batch_validator(
                    iteration=int(chunk_records[0]["iteration"]) + 1_000_000,
                    candidates=candidates,
                    attempts=stability_validation_repeats,
                    output_subdir=str(output_path),
                )
                if isinstance(batch_summary, dict) and batch_summary.get("status") in ("ok", "partial", "failed"):
                    candidate_summaries = batch_summary.get("candidates")
                    if isinstance(candidate_summaries, list):
                        summary_by_id = {
                            str(item.get("candidate_id")): item
                            for item in candidate_summaries
                            if isinstance(item, dict) and item.get("candidate_id") is not None
                        }
                        for index, record in enumerate(chunk_records):
                            timing = record["timing"]
                            candidate_id = str(timing.get("stability_validation_batch_candidate_id"))
                            fresh_summary = summary_by_id.get(candidate_id)
                            if fresh_summary is None and index < len(candidate_summaries):
                                fallback_summary = candidate_summaries[index]
                                fresh_summary = fallback_summary if isinstance(fallback_summary, dict) else None
                            summary = _fresh_oracle_stability_summary(fresh_summary)
                            record["stability_validation"] = summary
                            timing["stability_validation_ms"] = _elapsed_ms(timing_step)
                            timing["stability_validation_batch_ms"] = _elapsed_ms(timing_step)
                            timing["stability_validation_stable"] = bool(summary["stable"])
                            timing["stability_validation_fit_score_spread"] = summary["fit_score_spread"]
                            timing["stability_validation_worst_foreground_weight_sum_spread"] = summary.get(
                                "worst_foreground_weight_sum_spread"
                            )
                            timing["stability_validation_score_policy"] = summary["score_policy"]
                            timing["stability_validation_batch_status"] = batch_summary.get("status")
                            if summary["conservative_fit_score"] is not None:
                                record["fit_score"] = float(summary["conservative_fit_score"])
                            if summary["conservative_diff_score"] is not None:
                                record["diff_score"] = float(summary["conservative_diff_score"])
                        continue
                for record in chunk_records:
                    record["timing"]["stability_validation_batch_fallback"] = (
                        batch_summary.get("reason") if isinstance(batch_summary, dict) else "invalid_batch_summary"
                    )
                    fallback_records.append(record)
            if not fallback_records:
                return
            selected_records = fallback_records
        for rank, record in enumerate(selected_records):
            _stability_validate_record(record, f"batch_top_k_stability_validation_rank_{rank:02d}")

    def _target_full_validate_batch_records(batch_records: list[dict[str, Any]]) -> None:
        if not target_full_validation:
            return
        for record in batch_records:
            timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
            timing["target_full_validation_selected"] = False
            if float(record.get("fit_score", -math.inf)) < float(effective_target_score):
                continue
            if _record_has_full_profile(record):
                timing["target_full_validation_skipped"] = "already_full_profile"
            else:
                timing["target_full_validation_selected"] = True
                timing["target_full_validation_source_fit_score"] = float(record["fit_score"])
                timing["target_full_validation_source_diff_score"] = float(record["diff_score"])
                timing["target_full_validation_profile"] = "full"
                _full_validate_record(record, "target_full_validation")
            if isinstance(record.get("stability_validation"), dict):
                timing["target_stability_validation_skipped"] = "already_validated"
            else:
                _stability_validate_record(record, "target_stability_validation")

    while terminal_reason is None and state.iteration < iterations:
        remaining = iterations - state.iteration
        batch_size = min(evaluation_batch_size, remaining)
        timing_step = time.perf_counter()
        proposals = strategy.propose_many(
            StrategyContext(
                iteration=state.iteration,
                current_params=current_params,
                analysis=context_analysis,
                diff_score=context_diff_score,
                fit_score=context_fit_score,
                state=state,
            ),
            count=batch_size,
        )
        if not proposals:
            terminal_reason = "no_candidate_proposals"
            break
        batch_size = len(proposals)
        batch_propose_ms = _elapsed_ms(timing_step)
        score_pairs: list[tuple[float, float]] = []
        batch_context: tuple[dict[str, Any], dict[str, Any], float, float] | None = None
        batch_context_score = -math.inf
        first_iteration = state.iteration

        try:
            if analysis_pipeline_enabled and batch_size > 1:
                batch_records = _evaluate_batch_records_with_analysis_pipeline(
                    proposals,
                    batch_size=batch_size,
                    first_iteration=first_iteration,
                    batch_propose_ms=batch_propose_ms,
                )
            elif effective_evaluation_workers > 1 and batch_size > 1:
                batch_records = _evaluate_batch_records(
                    proposals,
                    batch_size=batch_size,
                    first_iteration=first_iteration,
                    batch_propose_ms=batch_propose_ms,
                )
            else:
                batch_records = [
                    _evaluate_batch_candidate(
                        batch_index=batch_index,
                        batch_size=batch_size,
                        iteration=first_iteration + batch_index,
                        next_params=next_params,
                        decision=decision,
                        batch_propose_ms=batch_propose_ms,
                    )
                    for batch_index, (next_params, decision) in enumerate(proposals)
                ]
        except ImagePairCollectionError as exc:
            payload = {
                "status": "failed",
                "reason": str(exc),
                "target_score": target_score,
                "iterations": result_iterations,
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload
        _full_rerank_batch_records(batch_records)
        _top_k_stability_validate_batch_records(batch_records)
        _best_full_validate_batch_records(batch_records)
        _target_full_validate_batch_records(batch_records)

        for record in batch_records:
            iteration = int(record["iteration"])
            next_params = record["next_params"]
            decision = record["decision"]
            timing = record["timing"]
            diff_score = float(record["diff_score"])
            fit_score = float(record["fit_score"])
            prev_best_score = state.best_score
            is_new_best = fit_score > best_fit_score
            if is_new_best:
                best_fit_score = fit_score
            if fit_score > state.best_fit_score:
                state.best_fit_score = fit_score
                state.best_fit_params = dict(next_params)
            if diff_score < state.best_score:
                state.best_score = diff_score
                state.best_params = dict(next_params)
            if diff_score < prev_best_score - 1e-6:
                state.global_no_improve = 0
            else:
                state.global_no_improve += 1
            decision["global_no_improve"] = state.global_no_improve

            decision_stage = decision.get("stage")
            selected_stage_name = decision_stage.get("name") if isinstance(decision_stage, dict) else None
            target_stop_reason = _target_stop_reason(
                fit_score,
                target_score=target_score,
                score_ceiling=score_ceiling,
            )
            if target_stop_reason:
                decision["stop_reason"] = target_stop_reason
                selected_stage_name = target_stop_reason
            iteration_payload = {
                "iteration": iteration,
                "input_pair": record["pair"],
                "input_pairs": record["image_pairs"],
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(next_params),
                "score_params_role": "candidate_params",
                "target_score": target_score,
                "effective_target_score": effective_target_score,
                "score_ceiling": copy.deepcopy(score_ceiling),
                "selected_stage": selected_stage_name,
                "decision": decision,
                "params_path": str(record["params_path"]),
                "candidate_params": copy.deepcopy(next_params),
                "candidate_lmat_path": record["candidate_lmat_path"],
                "render_result": record["render_result"],
                "initial_editor_capture_result": initial_editor_capture_result if iteration == 0 else None,
                "screen_capture_after_apply": record["screen_capture_result"],
                "perceptual_signals": _extract_perceptual_signals(record["analysis"]),
                "multiview_analysis": record["multiview_analysis"],
                "stability_validation": copy.deepcopy(record.get("stability_validation")),
                "timing": timing,
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
                is_snapshot=bool(timing["is_snapshot"]),
                is_best=is_new_best,
            )
            _prune_iteration_artifacts(
                auto_dir,
                iteration_series,
                current_iteration=iteration,
                snapshot_interval=snapshot_interval,
                keep_last_n=keep_last_n_artifacts,
                always_keep_best=bool(analysis_performance["always_keep_best_artifact"]),
                always_keep_first=bool(analysis_performance["always_keep_first_artifact"]),
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            )
            score_pairs.append((fit_score, diff_score))
            if fit_score > batch_context_score:
                batch_context_score = fit_score
                batch_context = (dict(next_params), record["analysis"], diff_score, fit_score)
            if target_stop_reason and not (require_real_closed_loop and not result_iterations):
                terminal_reason = target_stop_reason
            state.iteration += 1
            state.history = list(iteration_series)
            save_adjustment_state(auto_dir / "state.json", state)

        strategy.tell_many_scores(score_pairs)
        if hasattr(strategy, "save_checkpoint"):
            strategy.save_checkpoint(auto_dir / "optimizer_checkpoint.pkl")
        if batch_context is not None:
            current_params, context_analysis, context_diff_score, context_fit_score = batch_context
        strategy_stop = strategy.stop_reason()
        if strategy_stop:
            terminal_reason = strategy_stop

    best_fit_params = dict(state.best_fit_params or state.best_params or current_params)
    best_dir = auto_dir / "best"
    _write_json(best_dir / "params.json", best_fit_params)
    best_lmat_path = ""
    if write_candidate_lmat or apply_lmat:
        best_lmat_path = str(best_dir / laya_material_path.name)
        lmat_io.write_candidate_lmat(
            laya_material_path,
            best_lmat_path,
            best_fit_params,
            allow_missing_keys=True,
        )
    if apply_lmat and best_fit_params:
        backup_path = lmat_io.backup_lmat(
            laya_material_path,
            suffix=".auto_adjust_best_guard.bak",
            target_dir=external_backup_dir,
        )
        lmat_io.write_candidate_lmat(
            laya_material_path,
            laya_material_path,
            best_fit_params,
            allow_missing_keys=True,
        )
        final_best_restore = {
            "applied_lmat": str(laya_material_path),
            "backup_lmat": str(backup_path),
        }
    else:
        final_best_restore = None

    state.history = list(iteration_series)
    save_adjustment_state(auto_dir / "state.json", state)
    if iteration_series:
        final_iteration = int(iteration_series[-1].get("iteration", len(iteration_series) - 1))
        snapshot_iterations.add(final_iteration)
        if keep_last_n_artifacts > 0:
            for item in iteration_series[-keep_last_n_artifacts:]:
                value = item.get("iteration")
                if isinstance(value, int):
                    snapshot_iterations.add(value)
        best_iteration = _best_recorded_iteration(iteration_series)
        if best_iteration is not None:
            snapshot_iterations.add(best_iteration)
            best_payload = full_payloads.get(best_iteration)
            if isinstance(best_payload, dict):
                _write_json(auto_dir / f"iter_{best_iteration:04d}" / "decision.json", best_payload)
        for snapshot_iteration in snapshot_iterations:
            snapshot_payload = full_payloads.get(snapshot_iteration)
            if isinstance(snapshot_payload, dict):
                _write_json(auto_dir / f"iter_{snapshot_iteration:04d}" / "decision.json", snapshot_payload)
        _mark_series_snapshots(iteration_series, snapshot_iterations)
        _write_json(auto_dir / "iteration_series.json", iteration_series)
        _write_snapshot_index(auto_dir, iteration_series, snapshot_iterations)
        _prune_iteration_artifacts(
            auto_dir,
            iteration_series,
            current_iteration=final_iteration,
            snapshot_interval=snapshot_interval,
            keep_last_n=keep_last_n_artifacts,
            always_keep_best=bool(analysis_performance["always_keep_best_artifact"]),
            always_keep_first=bool(analysis_performance["always_keep_first_artifact"]),
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            final_cleanup=True,
        )

    optimizer_research_summary = strategy.research_summary()
    if isinstance(optimizer_research_summary, dict) and optimizer_research_summary:
        _write_json(
            output_dir / "optimizer_artifacts" / optimizer / "research_summary.json",
            optimizer_research_summary,
        )
    final_status = _resolve_auto_adjust_status(
        best_fit_score=best_fit_score,
        target_score=target_score,
        score_ceiling=score_ceiling,
        terminal_reason=terminal_reason,
        completed_iterations=len(result_iterations),
        requested_iterations=iterations,
        optimizer_research_summary=optimizer_research_summary,
    )
    cma_es_payload = (
        cmaes_strategy_config_to_dict(cma_es_config)
        if cma_es_config and optimizer in ("cma_cold", "cma_warm")
        else None
    )
    optimizer_candidate_archive = _build_optimizer_candidate_archive(iteration_series)
    optimizer_candidate_archive_path = auto_dir / "optimizer_candidate_archive.json"
    _write_json(optimizer_candidate_archive_path, optimizer_candidate_archive)
    optimizer_evidence_summary = _build_optimizer_evidence_summary(
        status=final_status,
        terminal_reason=terminal_reason,
        target_score=target_score,
        effective_target_score=float(effective_target_score),
        score_ceiling=score_ceiling,
        best_fit_score=best_fit_score,
        iterations=iteration_series,
        fit_score_mode=fit_score_mode,
        optimizer_preset=_optimizer_preset_from_config(config),
        optimizer=optimizer,
        cma_es_config=cma_es_payload,
        warm_start_history_size=len(warm_history) if optimizer == "cma_warm" else 0,
        warm_start_sources=warm_start_sources,
        analysis_performance=analysis_performance,
        batch_execution=_build_batch_execution_summary(
            iteration_series,
            analysis_performance=analysis_performance,
            context=batch_context_summary,
        ),
        candidate_archive=optimizer_candidate_archive,
        candidate_archive_path=str(optimizer_candidate_archive_path),
    )
    optimizer_evidence_summary_path = auto_dir / "optimizer_evidence_summary.json"
    _write_json(optimizer_evidence_summary_path, optimizer_evidence_summary)
    payload = {
        "status": final_status,
        "terminal_reason": terminal_reason,
        "target_score": target_score,
        "effective_target_score": effective_target_score,
        "score_ceiling": copy.deepcopy(score_ceiling),
        "best_score": state.best_score,
        "best_fit_score": best_fit_score,
        "best_params": best_fit_params,
        "best_fit_params": best_fit_params,
        "best_lmat_path": best_lmat_path,
        "final_best_restore": final_best_restore,
        "best_guard": {
            "enabled": True,
            "selection_metric": "fit_score",
            "note": "Final output is restored to best-fit params instead of the last explored candidate.",
        },
        "iterations": iteration_series,
        "iteration_series_path": str(auto_dir / "iteration_series.json"),
        "snapshot_index_path": str(auto_dir / "snapshot_index.json"),
        "state_path": str(auto_dir / "state.json"),
        "fit_score_mode": fit_score_mode,
        "analysis_performance": analysis_performance,
        "batch_execution": optimizer_evidence_summary["batch_execution"],
        "optimizer_preset": _optimizer_preset_from_config(config),
        "optimizer": optimizer,
        "cma_es_config": cma_es_payload,
        "warm_start_history_size": len(warm_history) if optimizer == "cma_warm" else 0,
        "warm_start_sources": warm_start_sources,
        "optimizer_evidence_summary": optimizer_evidence_summary,
        "optimizer_evidence_summary_path": str(optimizer_evidence_summary_path),
        "optimizer_candidate_archive": optimizer_candidate_archive,
        "optimizer_candidate_archive_path": str(optimizer_candidate_archive_path),
        "effect_graph": semantic_graph,
        "optimizer_research_summary": optimizer_research_summary,
    }
    _write_json(auto_dir / "auto_adjust_result.json", payload)
    return payload
