"""Shared semantic-block CMA search followed by structured refinement."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .cmaes_strategy import CmaesStrategy
from .material_semantic_blocks import MATERIAL_SEMANTIC_BLOCK_BY_NAME
from .strategy_core import CmaesStrategyConfig, OptimizerStrategy, StrategyContext
from .structured_fish_strategy import StructuredFishStrategy
from .structured_fish_space import structured_fish_coordinates


DEFAULT_BLOCK_ORDER = ("tone_shadow", "base_surface", "specular", "rim")


class MaterialBlockHybridStrategy(OptimizerStrategy):
    """Optimize low-dimensional shader-effect blocks before joint refinement.

    The strategy is asset-independent. It receives an explicit parameter
    whitelist and uses only online image scores while preserving every
    parameter outside the active semantic block.
    """

    name = "material_block_hybrid"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        allowed = set(search_param_names or initial_params)
        configured_order = cfg.get("block_order", DEFAULT_BLOCK_ORDER)
        order = tuple(str(name) for name in configured_order)
        unknown = [name for name in order if name not in MATERIAL_SEMANTIC_BLOCK_BY_NAME]
        if unknown:
            raise ValueError(f"unknown material semantic blocks: {unknown}")

        self._initial_params = copy.deepcopy(initial_params)
        self._shader_params = list(shader_params)
        self._search_param_names = [
            name for name in dict.fromkeys(search_param_names or initial_params) if name in initial_params
        ]
        self._blocks: list[tuple[str, list[str], float]] = []
        sigma_scale = _positive_float(cfg.get("sigma_scale"), 1.0)
        for name in order:
            block_names, default_sigma = MATERIAL_SEMANTIC_BLOCK_BY_NAME[name]
            names = [param_name for param_name in block_names if param_name in allowed and param_name in initial_params]
            if names:
                self._blocks.append((name, names, min(default_sigma * sigma_scale, 1.0)))
        if not self._blocks:
            raise ValueError("material_block_hybrid has no searchable semantic blocks")

        self._block_iterations = max(int(cfg.get("block_iterations", 100)), 1)
        self._population_size = max(int(cfg.get("population_size", 10)), 2)
        self._seed = int(cfg.get("seed", 20260714))
        self._refine_enabled = bool(cfg.get("refine_enabled", True))
        self._refine_regularization_weight = max(
            float(cfg.get("refine_regularization_weight", 0.02)),
            0.0,
        )
        self._refine_scene_alignment_rounds = max(
            int(cfg.get("refine_scene_alignment_rounds", 4)),
            0,
        )

        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score = -math.inf
        self._best_analysis: dict[str, Any] = {}
        self._active: OptimizerStrategy | None = None
        self._active_kind: str | None = None
        self._active_name: str | None = None
        self._active_fresh = False
        self._block_index = 0
        self._stage_proposals = 0
        self._stage_start_score = -math.inf
        self._stage_summaries: list[dict[str, Any]] = []
        self._finished = False

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        if self._finished:
            return "material_block_hybrid_complete"
        if self._active_kind == "structured_refine" and self._active is not None:
            return self._active.stop_reason()
        return None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        if self._active is None:
            self._start_next_stage()
        elif self._active_kind == "cma" and self._stage_proposals >= self._block_iterations:
            self._finish_active_stage()
            self._start_next_stage()

        if self._finished or self._active is None:
            return copy.deepcopy(self._best_params), self._decision(None, {}, stop=True)

        active_ctx = self._best_context(ctx) if self._active_fresh else ctx
        self._active_fresh = False
        candidate, nested = self._active.propose(active_ctx)
        self._stage_proposals += 1
        return candidate, self._decision(candidate, nested, stop=False)

    def research_summary(self) -> dict[str, Any]:
        nested = self._active.research_summary() if self._active is not None else {}
        return {
            "profile": "material_block_hybrid_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_residuals_only",
            "target_params_visible": False,
            "block_order": [name for name, _params, _sigma in self._blocks],
            "block_iterations": self._block_iterations,
            "population_size": self._population_size,
            "refine_scene_alignment_rounds": self._refine_scene_alignment_rounds,
            "active_kind": self._active_kind,
            "active_name": self._active_name,
            "active_stage_proposals": self._stage_proposals,
            "best_fit_score": self._best_fit_score,
            "completed_stages": copy.deepcopy(self._stage_summaries),
            "nested": nested,
            "stop_reason": self.stop_reason(),
        }

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if math.isfinite(score) and score > self._best_fit_score:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_analysis = copy.deepcopy(ctx.analysis)

    def _start_next_stage(self) -> None:
        self._stage_proposals = 0
        self._stage_start_score = self._best_fit_score
        if self._block_index < len(self._blocks):
            name, search_names, sigma = self._blocks[self._block_index]
            coordinates = structured_fish_coordinates(
                self._best_params,
                shader_params=self._shader_params,
                search_param_names=search_names,
            )
            axis_bounds = {
                coordinate.coordinate_id: (coordinate.low, coordinate.high)
                for coordinate in coordinates
            }
            self._active = CmaesStrategy(
                initial_params=self._best_params,
                shader_params=self._shader_params,
                config=CmaesStrategyConfig(
                    mode="cold",
                    population_size=self._population_size,
                    sigma=sigma,
                    seed=self._seed + self._block_index,
                    hint_bias_mix_ratio=0.0,
                ),
                param_whitelist=search_names,
                axis_bounds=axis_bounds,
            )
            self._active_kind = "cma"
            self._active_name = name
            self._block_index += 1
            self._active_fresh = True
            return
        if self._refine_enabled:
            self._active = StructuredFishStrategy(
                initial_params=self._best_params,
                shader_params=self._shader_params,
                search_param_names=self._search_param_names,
                regularization_weight=self._refine_regularization_weight,
                regularization_final_weight=0.0,
                regularization_decay=0.5,
                pattern_move_scale=0.5,
                gauss_newton_damping=0.75,
                gauss_newton_ridge=0.001,
                gauss_newton_max_repeats=2,
                gauss_newton_interval=16,
                broad_coordinate_max_repeats=0,
                scene_alignment_rounds=self._refine_scene_alignment_rounds,
                freeze_scene_after_alignment=True,
                basin_escape_enabled=False,
                opportunistic_ranked_accept=False,
            )
            self._active_kind = "structured_refine"
            self._active_name = "all_material_coordinates"
            self._active_fresh = True
            self._refine_enabled = False
            return
        self._active = None
        self._active_kind = None
        self._active_name = None
        self._finished = True

    def _finish_active_stage(self) -> None:
        self._stage_summaries.append(
            {
                "kind": self._active_kind,
                "name": self._active_name,
                "proposals": self._stage_proposals,
                "start_fit_score": self._stage_start_score,
                "best_fit_score": self._best_fit_score,
                "gain": self._best_fit_score - self._stage_start_score,
            }
        )
        self._active = None
        self._active_kind = None
        self._active_name = None

    def _best_context(self, ctx: StrategyContext) -> StrategyContext:
        return StrategyContext(
            iteration=ctx.iteration,
            current_params=copy.deepcopy(self._best_params),
            analysis=copy.deepcopy(self._best_analysis),
            diff_score=max(0.0, 1.0 - self._best_fit_score),
            fit_score=self._best_fit_score,
            state=ctx.state,
        )

    def _decision(
        self,
        candidate: dict[str, Any] | None,
        nested: dict[str, Any],
        *,
        stop: bool,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None if stop else {
                "name": f"material_block_hybrid_{self._active_name}",
                "description": "Asset-independent semantic block search",
            },
            "material_block_hybrid": {
                "profile": "material_block_hybrid_v1",
                "active_kind": self._active_kind,
                "active_name": self._active_name,
                "stage_proposal": self._stage_proposals,
                "stage_budget": self._block_iterations if self._active_kind == "cma" else None,
                "best_fit_score": self._best_fit_score,
                "feedback_source": "online_target_png_score_and_residuals_only",
                "target_params_visible": False,
                "nested": nested,
            },
            "changes": nested.get("changes", []) if isinstance(nested, dict) else [],
            "stop_reason": "material_block_hybrid_complete" if stop else "continue",
        }


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0.0 else default


__all__ = ["DEFAULT_BLOCK_ORDER", "MaterialBlockHybridStrategy"]
