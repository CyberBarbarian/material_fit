"""Semantic-block trust-region optimizer for the shared material space."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .material_jacobian_trust_region_strategy import MaterialJacobianTrustRegionStrategy
from .material_semantic_blocks import MATERIAL_SEMANTIC_BLOCK_BY_NAME
from .strategy_core import OptimizerStrategy, StrategyContext


DEFAULT_BLOCK_ORDER = ("tone_shadow", "base_surface", "specular", "rim")


class MaterialBlockTrustRegionStrategy(OptimizerStrategy):
    """Run low-dimensional residual-Jacobian stages before a full refinement."""

    name = "material_block_trust_region"

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
        order = tuple(str(name) for name in cfg.get("block_order", DEFAULT_BLOCK_ORDER))
        unknown = [name for name in order if name not in MATERIAL_SEMANTIC_BLOCK_BY_NAME]
        if unknown:
            raise ValueError(f"unknown material semantic blocks: {unknown}")
        self._blocks: list[tuple[str, list[str]]] = []
        for name in order:
            block_names, _sigma = MATERIAL_SEMANTIC_BLOCK_BY_NAME[name]
            names = [param_name for param_name in block_names if param_name in allowed and param_name in initial_params]
            if names:
                self._blocks.append((name, names))
        if not self._blocks:
            raise ValueError("material_block_trust_region has no searchable semantic blocks")

        self._initial_params = copy.deepcopy(initial_params)
        self._shader_params = list(shader_params)
        self._search_param_names = [
            name for name in dict.fromkeys(search_param_names or initial_params) if name in initial_params
        ]
        self._block_iterations = max(int(cfg.get("block_iterations", 60)), 1)
        self._full_iterations = max(int(cfg.get("full_iterations", 360)), 1)
        self._jacobian_config = {
            "difference_mode": str(cfg.get("difference_mode", "forward")),
            "probe_step": float(cfg.get("probe_step", 0.025)),
            "minimum_probe_step": float(cfg.get("minimum_probe_step", 0.006)),
            "ridge": float(cfg.get("ridge", 0.10)),
            "trust_radius": float(cfg.get("trust_radius", 0.12)),
            "maximum_trust_radius": float(cfg.get("maximum_trust_radius", 0.24)),
            "max_axis_update": float(cfg.get("max_axis_update", 0.18)),
            "line_search_scales": cfg.get("line_search_scales", (1.0, 0.5, 0.25, 0.125)),
        }

        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score = -math.inf
        self._best_analysis: dict[str, Any] = {}
        self._block_index = 0
        self._full_started = False
        self._active: MaterialJacobianTrustRegionStrategy | None = None
        self._active_name: str | None = None
        self._active_budget = 0
        self._active_proposals = 0
        self._active_fresh = False
        self._stage_start_score = -math.inf
        self._stage_summaries: list[dict[str, Any]] = []
        self._finished = False

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return "material_block_trust_region_complete" if self._finished else None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        if self._active is None:
            self._start_next_stage()
        elif self._active_proposals >= self._active_budget or self._active.stop_reason() is not None:
            self._finish_active_stage()
            self._start_next_stage()
        if self._finished or self._active is None:
            return copy.deepcopy(self._best_params), self._decision({}, stop=True)

        active_ctx = self._best_context(ctx) if self._active_fresh else ctx
        self._active_fresh = False
        candidate, nested = self._active.propose(active_ctx)
        self._active_proposals += 1
        return candidate, self._decision(nested, stop=False)

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": "material_block_trust_region_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
            "block_order": [name for name, _names in self._blocks],
            "block_iterations": self._block_iterations,
            "full_iterations": self._full_iterations,
            "active_name": self._active_name,
            "active_proposals": self._active_proposals,
            "best_fit_score": self._best_fit_score,
            "completed_stages": copy.deepcopy(self._stage_summaries),
            "nested": self._active.research_summary() if self._active is not None else {},
            "stop_reason": self.stop_reason(),
        }

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if math.isfinite(score) and score > self._best_fit_score:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_analysis = copy.deepcopy(ctx.analysis)

    def _start_next_stage(self) -> None:
        if self._block_index < len(self._blocks):
            name, names = self._blocks[self._block_index]
            self._block_index += 1
            budget = self._block_iterations
        elif not self._full_started:
            name = "all_material_coordinates"
            names = self._search_param_names
            budget = self._full_iterations
            self._full_started = True
        else:
            self._finished = True
            return
        self._active = MaterialJacobianTrustRegionStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=names,
            config=self._jacobian_config,
        )
        self._active_name = name
        self._active_budget = budget
        self._active_proposals = 0
        self._active_fresh = True
        self._stage_start_score = self._best_fit_score

    def _finish_active_stage(self) -> None:
        self._stage_summaries.append(
            {
                "name": self._active_name,
                "proposals": self._active_proposals,
                "start_fit_score": self._stage_start_score,
                "best_fit_score": self._best_fit_score,
                "gain": self._best_fit_score - self._stage_start_score,
                "nested": self._active.research_summary() if self._active is not None else {},
            }
        )
        self._active = None
        self._active_name = None
        self._active_budget = 0
        self._active_proposals = 0

    def _best_context(self, ctx: StrategyContext) -> StrategyContext:
        return StrategyContext(
            iteration=ctx.iteration,
            current_params=copy.deepcopy(self._best_params),
            analysis=copy.deepcopy(self._best_analysis),
            diff_score=max(0.0, 1.0 - self._best_fit_score),
            fit_score=self._best_fit_score,
            state=ctx.state,
        )

    def _decision(self, nested: dict[str, Any], *, stop: bool) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None if stop else {
                "name": f"material_block_trust_region_{self._active_name}",
                "description": "Asset-independent semantic-block residual trust region",
            },
            "material_block_trust_region": {
                "profile": "material_block_trust_region_v1",
                "active_name": self._active_name,
                "stage_proposal": self._active_proposals,
                "stage_budget": self._active_budget,
                "best_fit_score": self._best_fit_score,
                "feedback_source": "online_target_png_score_and_signed_residuals_only",
                "target_params_visible": False,
                "nested": nested,
            },
            "changes": nested.get("changes", []) if isinstance(nested, dict) else [],
            "stop_reason": "material_block_trust_region_complete" if stop else "continue",
        }


__all__ = ["DEFAULT_BLOCK_ORDER", "MaterialBlockTrustRegionStrategy"]
