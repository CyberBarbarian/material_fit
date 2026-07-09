"""Public optimizer strategy factory and compatibility exports."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .adjustment_algorithm import AdjustmentStagePolicy
from .cmaes_strategy import CmaesStrategy
from .cold_start_hybrid_strategy import ColdStartHybridStrategy
from .pattern16_strategy import Pattern16Strategy
from .response_driven_strategy import ResponseDrivenSemanticStrategy
from .semantic_graph import ShaderEffectGraph, graph_from_dict
from .strategy_core import (
    CmaesStrategyConfig,
    HeuristicStrategy,
    OptimizerStrategy,
    OptimizerUnavailableError,
    StrategyContext,
)
from .strategy_utils import (
    _normalize_initial_design_local_step_ratio,
    _normalize_initial_design_method,
    _normalize_restart_center_mode,
    _normalize_restart_population_schedule,
    _normalize_warm_start_source,
    _optional_bool,
    _optional_float,
    _optional_int,
)


SemanticGroupStrategy = ResponseDrivenSemanticStrategy


def build_strategy(
    *,
    optimizer: str,
    initial_params: dict[str, Any],
    shader_params: Sequence[ShaderParam],
    policies: Sequence[AdjustmentStagePolicy],
    unity_material_params: dict[str, Any] | None,
    cma_es_config: CmaesStrategyConfig | None = None,
    warm_start_history: Sequence[tuple[dict[str, Any], float]] = (),
    semantic_graph: ShaderEffectGraph | dict[str, Any] | None = None,
    auto_adjust_mode: str = "fresh_fit",
    cold_start_prior_anchors: Sequence[dict[str, Any]] = (),
    search_param_names: Sequence[str] | None = None,
) -> OptimizerStrategy:
    """Construct the requested strategy.

    ``optimizer`` is one of:

    * ``"heuristic"`` — current production path (E-002 stage-aware).
    * ``"cma_cold"`` — vanilla CMA-ES.
    * ``"cma_warm"`` — Warm-Started CMA-ES (E-006).
    * ``"semantic_group"`` — response-driven semantic scheduler.
    * ``"adaptive_response_search"`` — global-best response search.
    * ``"pattern16"`` — validated 16D coordinate pattern search.
    * ``"semantic_group_legacy_081"`` — preserved pattern-search baseline.
    * ``"subspace_cma_es"`` — expensive CMA-ES inside a semantic subspace.

    Unknown optimizer names raise :class:`ValueError` rather than
    silently falling back to the heuristic — silent fallbacks here
    would confuse research-time experiment comparisons.
    """
    optimizer = (optimizer or "heuristic").strip().lower()
    graph = semantic_graph if isinstance(semantic_graph, ShaderEffectGraph) else graph_from_dict(semantic_graph)
    if optimizer == "heuristic":
        return HeuristicStrategy(policies, shader_params, unity_material_params)
    if optimizer == "semantic_group":
        if graph is None:
            raise ValueError("semantic_group optimizer requires a semantic effect graph")
        return SemanticGroupStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            graph=graph,
            auto_adjust_mode=auto_adjust_mode,
        )
    if optimizer == "adaptive_response_search":
        if graph is None:
            raise ValueError("adaptive_response_search optimizer requires a semantic effect graph")
        from .adaptive_response_strategy import AdaptiveResponseSearchStrategy

        return AdaptiveResponseSearchStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            graph=graph,
            auto_adjust_mode=auto_adjust_mode,
        )
    if optimizer == "semantic_group_legacy_081":
        if graph is None:
            raise ValueError("semantic_group_legacy_081 optimizer requires a semantic effect graph")
        from .legacy_semantic_strategy import LegacySemanticGroupStrategy

        return LegacySemanticGroupStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            graph=graph,
            auto_adjust_mode=auto_adjust_mode,
        )
    if optimizer == "subspace_cma_es":
        if graph is None:
            raise ValueError("subspace_cma_es optimizer requires a semantic effect graph")
        from .subspace_cma_strategy import SubspaceCmaEsStrategy

        config = cma_es_config or CmaesStrategyConfig()
        return SubspaceCmaEsStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            graph=graph,
            population_size=config.population_size,
            sigma=config.sigma,
            seed=config.seed,
        )
    if optimizer == "cold_start_hybrid":
        return ColdStartHybridStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            prior_anchors=cold_start_prior_anchors,
            search_param_names=search_param_names,
        )
    if optimizer == "pattern16":
        return Pattern16Strategy(
            initial_params=initial_params,
            shader_params=shader_params,
        )
    if optimizer in ("cma_cold", "cma_warm"):
        config = cma_es_config or CmaesStrategyConfig()
        config = CmaesStrategyConfig(
            mode="cold" if optimizer == "cma_cold" else "warm",
            warm_start_iters=config.warm_start_iters,
            warm_start_source=config.warm_start_source,
            population_size=config.population_size,
            sigma=config.sigma,
            seed=config.seed,
            hint_bias_mix_ratio=config.hint_bias_mix_ratio,
            stagnation_patience=config.stagnation_patience,
            stagnation_min_delta=config.stagnation_min_delta,
            stagnation_min_evaluations=config.stagnation_min_evaluations,
            stagnation_max_restarts=config.stagnation_max_restarts,
            stagnation_stop_after_restarts=config.stagnation_stop_after_restarts,
            restart_center_mode=config.restart_center_mode,
            restart_population_multiplier=config.restart_population_multiplier,
            restart_population_schedule=config.restart_population_schedule,
            restart_max_population_size=config.restart_max_population_size,
            initial_design_samples=config.initial_design_samples,
            initial_design_method=config.initial_design_method,
            initial_design_include_current=config.initial_design_include_current,
            initial_design_local_step_ratio=config.initial_design_local_step_ratio,
        )
        return CmaesStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            config=config,
            warm_start_history=warm_start_history if optimizer == "cma_warm" else (),
            semantic_graph=graph,
            param_whitelist=(graph.active_search_params() if graph else None),
        )
    raise ValueError(
        f"unknown optimizer: {optimizer!r} "
        "(expected 'heuristic', 'cma_cold', 'cma_warm', 'semantic_group', "
        "'adaptive_response_search', "
        "'pattern16', 'semantic_group_legacy_081', 'subspace_cma_es', "
        "or 'cold_start_hybrid')"
    )


def cmaes_strategy_config_from_dict(data: dict[str, Any] | None) -> CmaesStrategyConfig:
    """Lenient dict→config helper for fit_config.json / project.json."""
    if not isinstance(data, dict):
        return CmaesStrategyConfig()
    mode = data.get("mode")
    raw_mix = data.get("hint_bias_mix_ratio", 0.30)
    try:
        mix_ratio = float(raw_mix)
    except (TypeError, ValueError):
        mix_ratio = 0.30
    if not math.isfinite(mix_ratio) or mix_ratio < 0.0:
        mix_ratio = 0.0
    if mix_ratio > 1.0:
        mix_ratio = 1.0
    raw_stagnation_delta = _optional_float(data.get("stagnation_min_delta"))
    stagnation_min_delta = raw_stagnation_delta if raw_stagnation_delta is not None else 0.001
    raw_restart_multiplier = _optional_float(data.get("restart_population_multiplier"))
    restart_multiplier = raw_restart_multiplier if raw_restart_multiplier is not None else 1.0
    raw_stop_after_restarts = _optional_bool(data.get("stagnation_stop_after_restarts"))
    restart_center_mode = _normalize_restart_center_mode(data.get("restart_center_mode"))
    restart_population_schedule = _normalize_restart_population_schedule(
        data.get("restart_population_schedule")
    )
    return CmaesStrategyConfig(
        mode=str(mode).strip().lower() if isinstance(mode, str) and mode else "warm",
        warm_start_iters=int(data.get("warm_start_iters", 12)),
        warm_start_source=_normalize_warm_start_source(data.get("warm_start_source")),
        population_size=_optional_int(data.get("population_size")),
        sigma=_optional_float(data.get("sigma")),
        seed=_optional_int(data.get("seed")),
        hint_bias_mix_ratio=mix_ratio,
        stagnation_patience=max(_optional_int(data.get("stagnation_patience")) or 0, 0),
        stagnation_min_delta=max(stagnation_min_delta, 0.0),
        stagnation_min_evaluations=max(_optional_int(data.get("stagnation_min_evaluations")) or 0, 0),
        stagnation_max_restarts=max(_optional_int(data.get("stagnation_max_restarts")) or 0, 0),
        stagnation_stop_after_restarts=True if raw_stop_after_restarts is None else raw_stop_after_restarts,
        restart_center_mode=restart_center_mode,
        restart_population_multiplier=max(restart_multiplier, 1.0),
        restart_population_schedule=restart_population_schedule,
        restart_max_population_size=_optional_int(data.get("restart_max_population_size")),
        initial_design_samples=max(_optional_int(data.get("initial_design_samples")) or 0, 0),
        initial_design_method=_normalize_initial_design_method(data.get("initial_design_method")),
        initial_design_include_current=_optional_bool(data.get("initial_design_include_current")) is not False,
        initial_design_local_step_ratio=_normalize_initial_design_local_step_ratio(
            data.get("initial_design_local_step_ratio")
        ),
    )


def cmaes_strategy_config_to_dict(config: CmaesStrategyConfig) -> dict[str, Any]:
    return asdict(config)



__all__ = [
    "CmaesStrategy",
    "CmaesStrategyConfig",
    "ColdStartHybridStrategy",
    "HeuristicStrategy",
    "OptimizerStrategy",
    "OptimizerUnavailableError",
    "Pattern16Strategy",
    "SemanticGroupStrategy",
    "StrategyContext",
    "build_strategy",
    "cmaes_strategy_config_from_dict",
    "cmaes_strategy_config_to_dict",
]
