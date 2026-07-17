"""Score-routed cascade of target-independent local-response optimizers."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .material_coordinate_pattern_strategy import MaterialCoordinatePatternStrategy
from .material_scene_grid_strategy import MaterialSceneGridStrategy
from .material_jacobian_trust_region_strategy import (
    MaterialJacobianTrustRegionStrategy,
)
from .material_optimizer_portfolio_strategy import (
    MaterialOptimizerPortfolioStrategy,
)
from .material_secant_trust_region_strategy import MaterialSecantTrustRegionStrategy
from .strategy_core import OptimizerStrategy, StrategyContext


class MaterialJacobianCascadeStrategy(OptimizerStrategy):
    """Switch between Jacobian policies using only online score and budget."""

    name = "material_jacobian_cascade"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        raw_stages = cfg.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise ValueError("material_jacobian_cascade requires at least one stage")
        self._profile = str(cfg.get("profile") or "material_jacobian_cascade_v1")
        self._total_max_proposals = max(
            int(cfg.get("total_max_proposals", 0)),
            1,
        )
        self._stages = [
            self._normalize_stage(row, index)
            for index, row in enumerate(raw_stages)
        ]
        self._shader_params = list(shader_params)
        self._search_param_names = list(search_param_names or initial_params)
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._best_analysis: dict[str, Any] = {}
        self._stage_index = 0
        self._stage_proposals = 0
        self._total_proposals = 0
        self._stage_summaries: list[dict[str, Any]] = []
        self._last_switch_reason: str | None = None
        self._optimizer = self._build_optimizer(self._stages[0])

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        if self._total_proposals >= self._total_max_proposals:
            return "material_jacobian_cascade_budget_complete"
        return None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        while self._should_advance_stage():
            if not self._advance_stage():
                return copy.deepcopy(self._best_params), self._decision(
                    nested={},
                    stop=True,
                )
        stage_ctx = (
            StrategyContext(
                iteration=ctx.iteration,
                current_params=copy.deepcopy(self._best_params),
                analysis=copy.deepcopy(self._best_analysis),
                diff_score=max(0.0, 1.0 - float(self._best_fit_score or 0.0)),
                fit_score=float(self._best_fit_score or ctx.fit_score),
                state=ctx.state,
            )
            if self._last_switch_reason is not None
            else ctx
        )
        self._last_switch_reason = None
        candidate, nested = self._optimizer.propose(stage_ctx)
        self._stage_proposals += 1
        self._total_proposals += 1
        return candidate, self._decision(nested=nested, stop=False)

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": self._profile,
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
            "stage_index": self._stage_index,
            "stage_name": self._stages[self._stage_index]["name"],
            "stage_proposals": self._stage_proposals,
            "total_proposals": self._total_proposals,
            "total_max_proposals": self._total_max_proposals,
            "best_fit_score": self._best_fit_score,
            "stage_summaries": copy.deepcopy(self._stage_summaries),
            "active_stage": self._optimizer.research_summary(),
            "stop_reason": self.stop_reason(),
        }

    @staticmethod
    def _normalize_stage(raw: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("material_jacobian_cascade stages must be objects")
        max_proposals = max(int(raw.get("max_proposals", 0)), 1)
        minimum_proposals = min(
            max(int(raw.get("minimum_proposals", 0)), 0),
            max_proposals,
        )
        switch_score_raw = raw.get("switch_score")
        switch_score = (
            float(switch_score_raw) if switch_score_raw is not None else None
        )
        if switch_score is not None and not math.isfinite(switch_score):
            raise ValueError("material_jacobian_cascade switch_score must be finite")
        optimizer = str(raw.get("optimizer") or "jacobian")
        if optimizer not in {
            "jacobian",
            "secant",
            "pattern",
            "scene_grid",
            "portfolio",
        }:
            raise ValueError(
                "material_jacobian_cascade stage optimizer must be "
                "'jacobian', 'secant', 'pattern', 'scene_grid', or 'portfolio'"
            )
        optimizer_config = raw.get(optimizer)
        if not isinstance(optimizer_config, dict):
            raise ValueError(
                "material_jacobian_cascade stage requires "
                f"{optimizer} config"
            )
        raw_frozen_names = raw.get("frozen_param_names", ())
        if not isinstance(raw_frozen_names, (list, tuple)):
            raise ValueError(
                "material_jacobian_cascade frozen_param_names must be a list"
            )
        return {
            "name": str(raw.get("name") or f"stage_{index}"),
            "max_proposals": max_proposals,
            "minimum_proposals": minimum_proposals,
            "switch_score": switch_score,
            "optimizer": optimizer,
            "optimizer_config": copy.deepcopy(optimizer_config),
            "frozen_param_names": [str(name) for name in raw_frozen_names],
        }

    def _build_optimizer(self, stage: dict[str, Any]) -> OptimizerStrategy:
        frozen_names = set(stage["frozen_param_names"])
        search_param_names = [
            name for name in self._search_param_names if name not in frozen_names
        ]
        if not search_param_names:
            raise ValueError(
                f"material_jacobian_cascade stage {stage['name']!r} has no "
                "searchable parameters"
            )
        strategy_type = {
            "jacobian": MaterialJacobianTrustRegionStrategy,
            "secant": MaterialSecantTrustRegionStrategy,
            "pattern": MaterialCoordinatePatternStrategy,
            "scene_grid": MaterialSceneGridStrategy,
            "portfolio": MaterialOptimizerPortfolioStrategy,
        }[stage["optimizer"]]
        return strategy_type(
            initial_params=copy.deepcopy(self._best_params),
            shader_params=self._shader_params,
            search_param_names=search_param_names,
            config=stage["optimizer_config"],
        )

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if not math.isfinite(score):
            return
        if self._best_fit_score is None or score > self._best_fit_score:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_analysis = copy.deepcopy(ctx.analysis)

    def _should_advance_stage(self) -> bool:
        if self._stage_index + 1 >= len(self._stages):
            return False
        stage = self._stages[self._stage_index]
        if self._stage_proposals >= stage["max_proposals"]:
            self._last_switch_reason = "stage_budget"
            return True
        switch_score = stage["switch_score"]
        if (
            switch_score is not None
            and self._stage_proposals >= stage["minimum_proposals"]
            and self._best_fit_score is not None
            and self._best_fit_score >= switch_score
        ):
            self._last_switch_reason = "online_score"
            return True
        if self._optimizer.stop_reason() is not None:
            self._last_switch_reason = "inner_stop"
            return True
        return False

    def _advance_stage(self) -> bool:
        stage = self._stages[self._stage_index]
        self._stage_summaries.append(
            {
                "stage_index": self._stage_index,
                "stage_name": stage["name"],
                "proposals": self._stage_proposals,
                "best_fit_score": self._best_fit_score,
                "switch_reason": self._last_switch_reason,
                "optimizer_type": stage["optimizer"],
                "frozen_param_names": copy.deepcopy(stage["frozen_param_names"]),
                "optimizer": self._optimizer.research_summary(),
            }
        )
        self._stage_index += 1
        if self._stage_index >= len(self._stages):
            return False
        self._stage_proposals = 0
        self._optimizer = self._build_optimizer(self._stages[self._stage_index])
        return True

    def _decision(self, *, nested: dict[str, Any], stop: bool) -> dict[str, Any]:
        stage = self._stages[self._stage_index]
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"material_jacobian_cascade_{stage['name']}",
                "description": "Score-routed asset-independent material refinement",
            },
            "material_jacobian_cascade": {
                "profile": self._profile,
                "stage_index": self._stage_index,
                "stage_name": stage["name"],
                "stage_proposals": self._stage_proposals,
                "total_proposals": self._total_proposals,
                "total_max_proposals": self._total_max_proposals,
                "best_fit_score": self._best_fit_score,
                "optimizer": stage["optimizer"],
                "frozen_param_names": copy.deepcopy(stage["frozen_param_names"]),
                "feedback_source": "online_target_png_score_and_signed_residuals_only",
                "target_params_visible": False,
                "nested": copy.deepcopy(nested),
            },
            "changes": copy.deepcopy(nested.get("changes", [])),
            "stop_reason": "material_jacobian_cascade_complete" if stop else "continue",
        }


__all__ = ["MaterialJacobianCascadeStrategy"]
