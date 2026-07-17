"""Single-candidate optimization execution.

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


def run_auto_adjustment(
    *,
    config: dict[str, Any],
    project_root: Path,
    output_dir: Path,
    laya_material_path: Path,
    laya_shader_params: list[Any],
    initial_params: dict[str, Any],
    policies: list[Any],
    unity_material_params: dict[str, Any],
    driver: RenderDriver,
    iterations: int,
    target_score: float,
    use_capture: bool,
    write_candidate_lmat: bool,
    apply_lmat: bool,
    capture_screen_after_apply: bool,
    rerender_wait_ms: int,
    screen_capture_region: str,
    screen_capture_max_keep: int | None = None,
    fit_score_mode: str = "linear",
    optimizer: str = "heuristic",
    cma_es_config: CmaesStrategyConfig | None = None,
    focus_callback: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the fourth part: analysis-driven adjustment orchestration."""

    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)
    external_backup_dir = _resolve_external_backup_dir(config, project_root, output_dir)
    state = AdjustmentState(best_params=dict(initial_params), best_fit_params=dict(initial_params))
    current_params = dict(initial_params)
    resume_requested = bool(config.get("auto_adjust_resume", False))
    resume_iteration_series: list[dict[str, Any]] = []
    if resume_requested and (auto_dir / "state.json").exists():
        state = load_adjustment_state(auto_dir / "state.json")
        resume_iteration_series = _load_iteration_series(auto_dir)
        if not resume_iteration_series and state.history:
            resume_iteration_series = list(state.history)
        current_params = dict(state.best_fit_params or state.best_params or initial_params)
    result_iterations: list[dict[str, Any]] = []
    iteration_series: list[dict[str, Any]] = []
    snapshot_iterations: set[int] = set()
    full_payloads: dict[int, dict[str, Any]] = {}
    best_fit_score = -math.inf
    candidate_override: str | dict[str, str] | None = None
    candidate_browser_score_result: dict[str, Any] | None = None
    require_real_closed_loop = apply_lmat and capture_screen_after_apply
    terminal_reason: str | None = None

    warm_history: list[tuple[dict[str, Any], float]] = []
    warm_start_sources: dict[str, Any] = {
        "limit": 0,
        "source": "none",
        "elite_archive": 0,
        "iteration_history": 0,
        "total": 0,
    }
    if optimizer == "cma_warm":
        warm_history, warm_start_sources = _load_optimizer_warm_start_history(
            auto_dir,
            limit=(cma_es_config.warm_start_iters if cma_es_config else 12),
            source=(cma_es_config.warm_start_source if cma_es_config else "elite_archive_first"),
        )
    semantic_graph = config.get("effect_graph") if isinstance(config.get("effect_graph"), dict) else None
    if semantic_graph is None:
        try:
            material_defines = lmat_io.extract_defines(lmat_io.load_lmat(laya_material_path))
        except Exception:  # noqa: BLE001
            material_defines = []
        semantic_graph = graph_to_dict(
            build_shader_effect_graph(
                laya_shader_params,
                material_params=initial_params,
                material_defines=material_defines,
            )
        )
    try:
        proposal_quantization_step, proposal_quantization_coordinates = (
            _proposal_quantization_coordinates(
                config,
                optimizer=optimizer,
                initial_params=current_params,
                shader_params=laya_shader_params,
                policy_graph=semantic_graph,
            )
        )
        strategy = build_strategy(
            optimizer=optimizer,
            initial_params=current_params,
            shader_params=laya_shader_params,
            policies=policies,
            unity_material_params=unity_material_params,
            cma_es_config=cma_es_config,
            warm_start_history=warm_history,
            semantic_graph=semantic_graph,
            auto_adjust_mode=str(config.get("auto_adjust_mode", "fresh_fit")),
            cold_start_prior_anchors=_cold_start_prior_anchors_from_config(config),
            search_param_names=_configured_search_param_names(
                config,
                optimizer,
                current_params,
                laya_shader_params,
                semantic_graph,
            ),
            structured_fish_config=(
                config.get("structured_fish")
                if isinstance(config.get("structured_fish"), dict)
                else None
            ),
            fish_spsa_config=(
                config.get("fish_spsa")
                if isinstance(config.get("fish_spsa"), dict)
                else None
            ),
            material_block_hybrid_config=(
                config.get("material_block_hybrid")
                if isinstance(config.get("material_block_hybrid"), dict)
                else None
            ),
            material_stage1_hybrid_config=(
                config.get("material_stage1_hybrid")
                if isinstance(config.get("material_stage1_hybrid"), dict)
                else None
            ),
            material_discrete_joint_config=(
                config.get("material_discrete_joint")
                if isinstance(config.get("material_discrete_joint"), dict)
                else None
            ),
            material_jacobian_trust_region_config=(
                config.get("material_jacobian_trust_region")
                if isinstance(config.get("material_jacobian_trust_region"), dict)
                else None
            ),
            material_block_trust_region_config=(
                config.get("material_block_trust_region")
                if isinstance(config.get("material_block_trust_region"), dict)
                else None
            ),
            material_coordinate_pattern_config=(
                config.get("material_coordinate_pattern")
                if isinstance(config.get("material_coordinate_pattern"), dict)
                else None
            ),
            material_secant_trust_region_config=(
                config.get("material_secant_trust_region")
                if isinstance(config.get("material_secant_trust_region"), dict)
                else None
            ),
            material_inverse_surrogate_config=(
                config.get("material_inverse_surrogate")
                if isinstance(config.get("material_inverse_surrogate"), dict)
                else None
            ),
        )
    except (OptimizerUnavailableError, ValueError) as exc:
        payload = {
            "status": "configuration_error",
            "reason": str(exc),
            "optimizer": optimizer,
            "target_score": target_score,
            "iterations": [],
        }
        _write_json(auto_dir / "auto_adjust_result.json", payload)
        return payload
    optimizer_checkpoint_path = auto_dir / "optimizer_checkpoint.pkl"
    if resume_requested and optimizer_checkpoint_path.exists() and hasattr(strategy, "load_checkpoint"):
        try:
            strategy.load_checkpoint(optimizer_checkpoint_path)
        except (OSError, EOFError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            payload = {
                "status": "configuration_error",
                "reason": str(exc),
                "optimizer": optimizer,
                "target_score": target_score,
                "iterations": resume_iteration_series,
                "state_path": str(auto_dir / "state.json"),
                "optimizer_checkpoint_path": str(optimizer_checkpoint_path),
            }
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

    oracle_stabilization = _prepare_render_oracle(
        config=config,
        auto_dir=auto_dir,
        driver=driver,
        params=current_params,
        resume_iteration=int(state.iteration),
    )
    score_ceiling = _resolve_score_ceiling(
        config,
        target_score=target_score,
        oracle_stabilization=oracle_stabilization,
    )
    effective_target_score = _effective_target_score(target_score, score_ceiling)

    analysis_performance = _resolve_analysis_performance(config)
    snapshot_interval = int(analysis_performance["snapshot_interval"])
    keep_last_n_artifacts = int(analysis_performance["keep_last_n_artifacts"])
    multiview_workers = analysis_performance["multiview_workers"]
    evaluation_batch_size = int(analysis_performance["evaluation_batch_size"])
    evaluation_workers = int(analysis_performance["evaluation_workers"])
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
    stability_canonical_foreground_signature = _oracle_stabilization_foreground_signature(
        oracle_stabilization,
    )
    if stability_canonical_foreground_signature is not None:
        analysis_performance["stability_canonical_foreground_signature"] = copy.deepcopy(
            stability_canonical_foreground_signature
        )
    fast_score_only_allowed = (
        bool(analysis_performance["fast_score_only"])
        and optimizer in (
            "cma_cold",
            "cma_warm",
            "cold_start_hybrid",
            "pattern16",
            "cross_engine_hybrid",
            "structured_fish",
            "fish_spsa",
            "material_block_hybrid",
            "material_stage1_hybrid",
            "material_discrete_joint",
            "material_jacobian_trust_region",
            "material_block_trust_region",
            "material_coordinate_pattern",
            "material_secant_trust_region",
            "material_inverse_surrogate",
        )
        and fit_score_mode in ("research", "perceptual")
    )
    if optimizer in ("cma_cold", "cma_warm", "cold_start_hybrid") and evaluation_batch_size > 1:
        batch_payload = _run_cma_batch_auto_adjustment(
            config=config,
            project_root=project_root,
            output_dir=output_dir,
            laya_material_path=laya_material_path,
            laya_shader_params=laya_shader_params,
            driver=driver,
            iterations=iterations,
            target_score=target_score,
            use_capture=use_capture,
            write_candidate_lmat=write_candidate_lmat,
            apply_lmat=apply_lmat,
            capture_screen_after_apply=capture_screen_after_apply,
            rerender_wait_ms=rerender_wait_ms,
            screen_capture_region=screen_capture_region,
            screen_capture_max_keep=screen_capture_max_keep,
            fit_score_mode=fit_score_mode,
            optimizer=optimizer,
            cma_es_config=cma_es_config,
            focus_callback=focus_callback,
            auto_dir=auto_dir,
            external_backup_dir=external_backup_dir,
            state=state,
            current_params=current_params,
            strategy=strategy,
            analysis_performance=analysis_performance,
            warm_history=warm_history,
            warm_start_sources=warm_start_sources,
            semantic_graph=semantic_graph,
            resume_iteration_series=resume_iteration_series,
            score_ceiling=score_ceiling,
            effective_target_score=effective_target_score,
        )
        if oracle_stabilization is not None:
            batch_payload["oracle_stabilization"] = oracle_stabilization
            _write_json(auto_dir / "auto_adjust_result.json", batch_payload)
        return batch_payload
    for local_index in range(iterations):
        iteration_started = time.perf_counter()
        iteration = state.iteration
        is_snapshot_iteration = _is_snapshot_iteration(iteration, snapshot_interval)
        research_metrics_profile = _research_metrics_profile_for_iteration(
            research_metrics_profile_setting,
            is_snapshot=is_snapshot_iteration,
        )
        timing: dict[str, Any] = {
            "snapshot_interval": snapshot_interval,
            "is_snapshot": is_snapshot_iteration,
            "perceptual_optional_enabled": is_snapshot_iteration,
            "diff_visual_enabled": is_snapshot_iteration,
            "keep_last_n_artifacts": keep_last_n_artifacts,
            "multiview_workers": multiview_workers,
            "evaluation_batch_size": evaluation_batch_size,
            "evaluation_workers": evaluation_workers,
            "research_metrics_profile": research_metrics_profile,
            "fast_score_only_enabled": fast_score_only_allowed and research_metrics_profile == "fast",
        }
        iteration_dir = auto_dir / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        initial_editor_capture_result: dict[str, Any] | None = None
        if candidate_override is None and candidate_browser_score_result is None:
            timing_step = time.perf_counter()
            try:
                initial_editor_capture_result = trigger_editor_multiview_capture(
                    config=config,
                    project_root=project_root,
                    iteration_dir=iteration_dir / "current",
                    iteration=iteration,
                    laya_material_path=laya_material_path,
                )
            except LayaEditorCaptureError as exc:
                initial_editor_capture_result = {
                    "status": "failed",
                    "error": str(exc),
                    "screenshots": [],
                }
            timing["initial_editor_capture_ms"] = _elapsed_ms(timing_step)
            if initial_editor_capture_result is not None:
                candidate_overrides = initial_editor_capture_result.get("candidate_overrides")
                if isinstance(candidate_overrides, dict) and candidate_overrides:
                    candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}

        if (
            candidate_override is None
            and candidate_browser_score_result is None
            and _browser_score_context_render_enabled(config)
        ):
            context_iteration = _context_render_iteration(iteration)
            timing_step = time.perf_counter()
            try:
                context_render_result = driver.render_candidate(context_iteration, current_params)
            except Exception as exc:  # noqa: BLE001
                context_render_result = {"status": "failed", "error": str(exc), "screenshots": []}
            timing["initial_context_render_ms"] = _elapsed_ms(timing_step)
            timing["initial_context_render_iteration"] = context_iteration
            if isinstance(context_render_result, dict):
                timing["initial_context_render_status"] = context_render_result.get("status")
            if _extract_browser_score_payload(context_render_result if isinstance(context_render_result, dict) else None) is not None:
                candidate_browser_score_result = copy.deepcopy(context_render_result)
                timing["initial_context_browser_score_used"] = True
            else:
                timing["initial_context_browser_score_used"] = False
                screenshots = context_render_result.get("screenshots", []) if isinstance(context_render_result, dict) else []
                candidate_overrides = (
                    context_render_result.get("candidate_overrides")
                    if isinstance(context_render_result, dict)
                    else None
                )
                if isinstance(candidate_overrides, dict) and candidate_overrides:
                    candidate_override = {str(key): str(value) for key, value in candidate_overrides.items()}
                elif screenshots:
                    candidate_override = str(screenshots[0])

        if candidate_browser_score_result is not None:
            score_payload = _browser_score_analysis_payload(candidate_browser_score_result, config=config)
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
            candidate_browser_score_result = None
        else:
            try:
                timing_step = time.perf_counter()
                image_pairs = _collect_image_pairs(config, project_root, output_dir, candidate_override=candidate_override)
                timing["collect_image_pairs_ms"] = _elapsed_ms(timing_step)
            except ImagePairCollectionError as exc:
                payload = {
                    "status": "failed",
                    "reason": str(exc),
                    "target_score": target_score,
                    "iterations": result_iterations,
                }
                _write_json(auto_dir / "auto_adjust_result.json", payload)
                return payload
            if not image_pairs:
                payload = {
                    "status": "pending",
                    "reason": "No image_pairs/reference_images configured and no auto reference/candidate pair found.",
                    "target_score": target_score,
                    "iterations": result_iterations,
                }
                _write_json(auto_dir / "auto_adjust_result.json", payload)
                return payload

            pair = image_pairs[0]
            timing_step = time.perf_counter()
            multiview_result = analyze_multiview_pairs(
                image_pairs,
                iteration_dir / "image_analysis",
                fit_score_mode=fit_score_mode,
                aggregation_config=config.get("multiview_scoring") if isinstance(config.get("multiview_scoring"), dict) else None,
                compute_perceptual_optional=bool(timing["perceptual_optional_enabled"]),
                generate_diff_image=bool(timing["diff_visual_enabled"]),
                research_metrics_profile=research_metrics_profile,
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
        is_new_best = fit_score > best_fit_score
        if is_new_best:
            best_fit_score = fit_score
        if fit_score > state.best_fit_score:
            state.best_fit_score = fit_score
            state.best_fit_params = dict(current_params)
        if diff_score < state.best_score:
            state.best_score = diff_score
            state.best_params = dict(current_params)
        scored_params = copy.deepcopy(current_params)

        target_stop_reason = _target_stop_reason(
            fit_score,
            target_score=target_score,
            score_ceiling=score_ceiling,
        )
        if target_stop_reason and not (require_real_closed_loop and not result_iterations):
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
                "target_score": target_score,
                "effective_target_score": effective_target_score,
                "score_ceiling": copy.deepcopy(score_ceiling),
                "selected_stage": target_stop_reason,
                "decision": {"stop_reason": target_stop_reason},
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = target_stop_reason
            break

        # E-010: stochastic strategies (CMA-ES) opt out of this check
        # because individual proposals are *expected* to be worse than
        # the running best in the early generations of a 49-dim run.
        # ``HeuristicStrategy.wants_global_no_improve_check()``
        # still returns True so legacy behaviour is preserved.
        if strategy.wants_global_no_improve_check() and should_abort_global(state):
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
                "target_score": target_score,
                "selected_stage": "global_no_improvement",
                "decision": {
                    "stop_reason": "global_no_improvement",
                    "global_no_improve": state.global_no_improve,
                },
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = "global_no_improvement"
            break

        if optimizer == "heuristic" and not policies:
            payload = {"status": "pending", "reason": "No adjustable shader parameters available.", "target_score": target_score, "best_fit_score": best_fit_score, "iterations": result_iterations}
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload

        timing_step = time.perf_counter()
        next_params, decision = strategy.propose(
            StrategyContext(
                iteration=iteration,
                current_params=current_params,
                analysis=analysis,
                diff_score=diff_score,
                fit_score=fit_score,
                state=state,
            )
        )
        effective_proposal_quantization_step = (
            _proposal_quantization_step_for_decision(
                decision,
                proposal_quantization_step,
            )
        )
        next_params, proposal_quantization = _quantize_searchable_proposal(
            next_params,
            coordinates=proposal_quantization_coordinates,
            normalized_step=effective_proposal_quantization_step,
        )
        if proposal_quantization["enabled"]:
            decision["proposal_quantization"] = proposal_quantization
        if decision.get("reset_global_score_domain"):
            best_fit_score = -math.inf
        timing["strategy_propose_ms"] = _elapsed_ms(timing_step)
        if decision.get("stop_reason") == "no_policies":
            payload = {"status": "pending", "reason": "No adjustable shader parameters available.", "target_score": target_score, "best_fit_score": best_fit_score, "iterations": result_iterations}
            _write_json(auto_dir / "auto_adjust_result.json", payload)
            return payload
        # Phase-summary 2026-05-08 follow-up: if SemanticGroupStrategy
        # has marked every group exhausted there is *nothing* worth
        # writing — re-applying the unchanged base params would just
        # waste a full Laya re-render + screenshot cycle and produce a
        # phantom iteration with stage=None that historically crashed
        # the iteration_payload builder. Bail out here with the
        # current best params intact and let the outer "completed"
        # block summarise normally.
        early_stop_reasons = {
            "all_semantic_groups_exhausted",
            "no_semantic_groups",
            "semantic_groups_exhausted",
            "pattern16_no_searchable_params",
            "pattern16_step_limit",
            "cross_engine_hybrid_no_searchable_params",
            "cross_engine_hybrid_step_limit",
            "structured_fish_no_searchable_coordinates",
            "structured_fish_step_limit",
        }
        if decision.get("stop_reason") in early_stop_reasons:
            print(
                f"[strategy] {decision.get('stop_reason')} at iter {iteration} — "
                f"breaking out of auto_adjust loop early.",
                flush=True,
            )
            iteration_payload = {
                "iteration": iteration,
                "input_pair": pair,
                "input_pairs": image_pairs,
                "diff_score_before": diff_score,
                "fit_score_before": fit_score,
                "scored_params": copy.deepcopy(scored_params),
                "score_params_role": "current_params",
                "target_score": target_score,
                "selected_stage": None,
                "decision": decision,
                "perceptual_signals": _extract_perceptual_signals(analysis),
                "multiview_analysis": multiview_analysis,
                "initial_editor_capture_result": initial_editor_capture_result,
                "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
            }
            _record_iteration_outputs(
                auto_dir=auto_dir,
                iteration_payload=iteration_payload,
                result_iterations=result_iterations,
                iteration_series=iteration_series,
                snapshot_iterations=snapshot_iterations,
                full_payloads=full_payloads,
            is_snapshot=True,
                is_best=is_new_best,
            )
            terminal_reason = str(decision.get("stop_reason") or "strategy_stopped")
            break
        if diff_score < state.best_score - 1e-6:
            state.global_no_improve = 0
        else:
            state.global_no_improve += 1
        decision["global_no_improve"] = state.global_no_improve

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
            # Focus Laya BEFORE the .lmat write so its file watcher
            # actually fires and re-renders. Background Laya silently
            # queues file events but does not redraw — see E-007.
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
        candidate_override = None
        candidate_browser_score_result = None
        screenshots = render_result.get("screenshots", []) if isinstance(render_result, dict) else []
        candidate_overrides = render_result.get("candidate_overrides") if isinstance(render_result, dict) else None
        if _extract_browser_score_payload(render_result if isinstance(render_result, dict) else None) is not None:
            candidate_browser_score_result = copy.deepcopy(render_result)
        elif isinstance(candidate_overrides, dict) and candidate_overrides:
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
                        previous_candidate_path=pair.get("candidate"),
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
                # Focus Laya again right before the screenshot. The
                # rerender_wait_ms sleep above can give other windows
                # time to steal focus (e.g., notifications), so we
                # re-assert focus to guarantee a fresh frame is on
                # screen when GDI grabs the pixels.
                if focus_callback is not None:
                    focus_log.append(focus_callback(f"iter_{iteration:04d}_before_capture"))
                # E-012: cap the rolling ``prefix_NN.png`` pool. CLI
                # override > config > default 30. Set <= 0 to disable
                # pruning entirely (matches legacy behavior).
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
        # P0 phase-summary 2026-05-08 follow-up: SemanticGroupStrategy
        # legitimately returns ``decision = {"stage": None,
        # "stop_reason": "all_semantic_groups_exhausted"}`` when every
        # group has either probed-out or run out of axes. The previous
        # ``decision.get("stage", {}).get("name")`` call assumed the
        # ``stage`` slot was always at least an empty dict; with the new
        # strategies that's no longer true and the run died at iter_30
        # with ``AttributeError: 'NoneType' object has no attribute
        # 'get'``. Treat any falsy stage payload as "no stage selected"
        # rather than crashing — and let the strategy_stop_reason path
        # below break out of the loop cleanly.
        decision_stage = decision.get("stage")
        if isinstance(decision_stage, dict):
            selected_stage_name = decision_stage.get("name")
        else:
            selected_stage_name = None
        iteration_payload = {
            "iteration": iteration,
            "input_pair": pair,
            "input_pairs": image_pairs,
            "diff_score_before": diff_score,
            "fit_score_before": fit_score,
            "scored_params": copy.deepcopy(scored_params),
            "score_params_role": "current_params",
            "target_score": target_score,
            "selected_stage": selected_stage_name,
            "decision": decision,
            "params_path": str(params_path),
            "candidate_params": copy.deepcopy(next_params),
            "candidate_lmat_path": candidate_lmat_path,
            "render_result": render_result,
            "initial_editor_capture_result": initial_editor_capture_result,
            "screen_capture_after_apply": screen_capture_result,
            # Keep both strict and tolerant signals next to the headline
            # fit_score so post-mortems can tell whether a regression came
            # from MAE drift, SSIM drift, auto-mask coverage, or human-score
            # component drift.
            "perceptual_signals": _extract_perceptual_signals(analysis),
            "multiview_analysis": multiview_analysis,
            "timing": {**timing, "iteration_total_ms": _elapsed_ms(iteration_started)},
        }
        strategy_stop = strategy.stop_reason()
        if strategy_stop:
            iteration_payload["decision"]["strategy_stop_reason"] = strategy_stop
        is_best_iteration = is_new_best
        _record_iteration_outputs(
            auto_dir=auto_dir,
            iteration_payload=iteration_payload,
            result_iterations=result_iterations,
            iteration_series=iteration_series,
            snapshot_iterations=snapshot_iterations,
            full_payloads=full_payloads,
            is_snapshot=bool(timing["is_snapshot"]),
            is_best=is_best_iteration,
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
        current_params = next_params
        state.iteration += 1
        if strategy_stop:
            terminal_reason = strategy_stop
            break

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

    # The historical full state duplicated every iteration payload and made
    # long runs huge. Persist only the resumable/high-level state plus a compact
    # series file for UI timelines.
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
        effective_target_score=effective_target_score,
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
        batch_execution=None,
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
    if oracle_stabilization is not None:
        payload["oracle_stabilization"] = oracle_stabilization
    _write_json(auto_dir / "auto_adjust_result.json", payload)
    return payload
