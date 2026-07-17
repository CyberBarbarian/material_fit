"""Public optimizer strategy factory and compatibility exports."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .adjustment_algorithm import AdjustmentStagePolicy
from .cmaes_strategy import CmaesStrategy
from .cold_start_hybrid_strategy import ColdStartHybridStrategy
from .cross_engine_hybrid_strategy import CrossEngineHybridStrategy
from .fish_spsa_strategy import FishSpsaStrategy
from .material_block_hybrid_strategy import MaterialBlockHybridStrategy
from .material_block_trust_region_strategy import MaterialBlockTrustRegionStrategy
from .material_coordinate_pattern_strategy import MaterialCoordinatePatternStrategy
from .material_discrete_joint_strategy import MaterialDiscreteJointStrategy
from .material_jacobian_trust_region_strategy import MaterialJacobianTrustRegionStrategy
from .material_inverse_surrogate_strategy import MaterialInverseSurrogateStrategy
from .material_secant_trust_region_strategy import MaterialSecantTrustRegionStrategy
from .material_stage1_hybrid_strategy import MaterialStage1HybridStrategy
from .pattern16_strategy import Pattern16Strategy
from .response_driven_strategy import ResponseDrivenSemanticStrategy
from .semantic_graph import ShaderEffectGraph, graph_from_dict
from .structured_fish_strategy import StructuredFishStrategy
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
    structured_fish_config: dict[str, Any] | None = None,
    fish_spsa_config: dict[str, Any] | None = None,
    material_block_hybrid_config: dict[str, Any] | None = None,
    material_stage1_hybrid_config: dict[str, Any] | None = None,
    material_discrete_joint_config: dict[str, Any] | None = None,
    material_jacobian_trust_region_config: dict[str, Any] | None = None,
    material_block_trust_region_config: dict[str, Any] | None = None,
    material_coordinate_pattern_config: dict[str, Any] | None = None,
    material_secant_trust_region_config: dict[str, Any] | None = None,
    material_inverse_surrogate_config: dict[str, Any] | None = None,
) -> OptimizerStrategy:
    """Construct the requested strategy.

    ``optimizer`` is one of:

    * ``"heuristic"`` — current production path (E-002 stage-aware).
    * ``"cma_cold"`` — vanilla CMA-ES.
    * ``"cma_warm"`` — Warm-Started CMA-ES (E-006).
    * ``"semantic_group"`` — response-driven semantic scheduler.
    * ``"adaptive_response_search"`` — global-best response search.
    * ``"pattern16"`` — validated 16D coordinate pattern search.
    * ``"cross_engine_hybrid"`` — response-ranked black-box cross-engine search.
    * ``"structured_fish"`` — staged scene/material coordinate search.
    * ``"fish_spsa"`` — coupled SPSA gradient estimates with Adam updates.
    * ``"material_block_hybrid"`` — semantic-block CMA plus joint refinement.
    * ``"material_stage1_hybrid"`` — structured warmup, semantic CMA, and material refine.
    * ``"material_discrete_joint"`` — successive-halving hard-state and continuous search.
    * ``"material_jacobian_trust_region"`` — full residual Jacobian plus trust-region updates.
    * ``"material_block_trust_region"`` — semantic-block Jacobians plus full refinement.
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
    if optimizer == "cross_engine_hybrid":
        return CrossEngineHybridStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
    if optimizer == "structured_fish":
        structured_config = structured_fish_config if isinstance(structured_fish_config, dict) else {}
        basin_escape_config = structured_config.get("basin_escape")
        if not isinstance(basin_escape_config, dict):
            basin_escape_config = {}
        return StructuredFishStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            regularization_weight=float(structured_config.get("regularization_weight", 0.0) or 0.0),
            regularization_final_weight=float(
                structured_config.get("regularization_final_weight", 0.0) or 0.0
            ),
            regularization_decay=float(structured_config.get("regularization_decay", 0.5)),
            regularization_disable_score=structured_config.get(
                "regularization_disable_score"
            ),
            pattern_move_scale=float(structured_config.get("pattern_move_scale", 0.5) or 0.5),
            gauss_newton_damping=float(structured_config.get("gauss_newton_damping", 0.75) or 0.75),
            gauss_newton_ridge=float(structured_config.get("gauss_newton_ridge", 0.001) or 0.001),
            gauss_newton_max_repeats=int(structured_config.get("gauss_newton_max_repeats", 2)),
            gauss_newton_interval=int(structured_config.get("gauss_newton_interval", 16)),
            gauss_newton_high_score_threshold=float(
                structured_config.get("gauss_newton_high_score_threshold", 1.0)
            ),
            gauss_newton_high_score_interval=structured_config.get(
                "gauss_newton_high_score_interval"
            ),
            gauss_newton_high_score_max_repeats=structured_config.get(
                "gauss_newton_high_score_max_repeats"
            ),
            broad_coordinate_max_repeats=int(
                structured_config.get("broad_coordinate_max_repeats", 0)
            ),
            scene_alignment_rounds=int(
                structured_config.get("scene_alignment_rounds", 1)
            ),
            freeze_scene_after_alignment=bool(
                structured_config.get("freeze_scene_after_alignment", False)
            ),
            basin_escape_enabled=bool(basin_escape_config.get("enabled", False)),
            basin_escape_pair_count=int(basin_escape_config.get("pair_count", 40)),
            basin_escape_round_pair_counts=basin_escape_config.get("round_pair_counts"),
            basin_escape_radii=basin_escape_config.get("radii", (2.5, 1.0)),
            basin_escape_damping=float(basin_escape_config.get("damping", 0.80)),
            basin_escape_ridge=float(basin_escape_config.get("ridge", 0.01)),
            basin_escape_seed=int(basin_escape_config.get("seed", 1701)),
            basin_escape_activation_min_fit_score=float(
                basin_escape_config.get("activation_min_fit_score", 0.0)
            ),
            basin_escape_activation_mode=str(
                basin_escape_config.get("activation_mode", "initial")
            ),
            basin_escape_disable_opportunistic_when_skipped=bool(
                basin_escape_config.get(
                    "disable_opportunistic_when_skipped",
                    False,
                )
            ),
            basin_escape_response_methods=basin_escape_config.get(
                "response_methods",
                ("residual_block_secant", "scalar_score_response"),
            ),
            basin_escape_direction_design=str(
                basin_escape_config.get("direction_design", "full_rank_hadamard_v1")
            ),
            basin_escape_response_trust_radius=basin_escape_config.get(
                "response_trust_radius"
            ),
            basin_escape_response_line_search_scales=basin_escape_config.get(
                "response_line_search_scales",
                (1.0,),
            ),
            opportunistic_ranked_accept=bool(
                structured_config.get("opportunistic_ranked_accept", False)
            ),
        )
    if optimizer == "fish_spsa":
        return FishSpsaStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=fish_spsa_config,
        )
    if optimizer == "material_block_hybrid":
        return MaterialBlockHybridStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_block_hybrid_config,
        )
    if optimizer == "material_stage1_hybrid":
        return MaterialStage1HybridStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_stage1_hybrid_config,
        )
    if optimizer == "material_discrete_joint":
        return MaterialDiscreteJointStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_discrete_joint_config,
        )
    if optimizer == "material_jacobian_trust_region":
        return MaterialJacobianTrustRegionStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_jacobian_trust_region_config,
        )
    if optimizer == "material_block_trust_region":
        return MaterialBlockTrustRegionStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_block_trust_region_config,
        )
    if optimizer == "material_coordinate_pattern":
        return MaterialCoordinatePatternStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_coordinate_pattern_config,
        )
    if optimizer == "material_secant_trust_region":
        return MaterialSecantTrustRegionStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_secant_trust_region_config,
        )
    if optimizer == "material_inverse_surrogate":
        return MaterialInverseSurrogateStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
            config=material_inverse_surrogate_config,
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
            allow_scene_lighting=config.allow_scene_lighting,
        )
        return CmaesStrategy(
            initial_params=initial_params,
            shader_params=shader_params,
            config=config,
            warm_start_history=warm_start_history if optimizer == "cma_warm" else (),
            semantic_graph=graph,
            param_whitelist=(
                list(search_param_names)
                if search_param_names is not None
                else (graph.active_search_params() if graph else None)
            ),
        )
    raise ValueError(
        f"unknown optimizer: {optimizer!r} "
        "(expected 'heuristic', 'cma_cold', 'cma_warm', 'semantic_group', "
        "'adaptive_response_search', "
        "'pattern16', 'cross_engine_hybrid', 'structured_fish', 'fish_spsa', "
        "'material_coordinate_pattern', "
        "'material_secant_trust_region', "
        "'material_inverse_surrogate', "
        "'material_block_hybrid', 'material_stage1_hybrid', 'material_discrete_joint', "
        "'semantic_group_legacy_081', 'subspace_cma_es', "
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
        allow_scene_lighting=bool(data.get("allow_scene_lighting", False)),
    )


def cmaes_strategy_config_to_dict(config: CmaesStrategyConfig) -> dict[str, Any]:
    return asdict(config)



__all__ = [
    "CmaesStrategy",
    "CmaesStrategyConfig",
    "ColdStartHybridStrategy",
    "CrossEngineHybridStrategy",
    "HeuristicStrategy",
    "OptimizerStrategy",
    "OptimizerUnavailableError",
    "Pattern16Strategy",
    "SemanticGroupStrategy",
    "StructuredFishStrategy",
    "StrategyContext",
    "build_strategy",
    "cmaes_strategy_config_from_dict",
    "cmaes_strategy_config_to_dict",
]
