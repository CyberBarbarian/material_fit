"""Sequential asset-independent portfolio over local material optimizers."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .material_coordinate_pattern_strategy import MaterialCoordinatePatternStrategy
from .material_jacobian_trust_region_strategy import (
    MaterialJacobianTrustRegionStrategy,
)
from .material_secant_trust_region_strategy import (
    MaterialSecantTrustRegionStrategy,
)
from .strategy_core import OptimizerStrategy, StrategyContext


class MaterialOptimizerPortfolioStrategy(OptimizerStrategy):
    """Evaluate several target-independent local policies and retain the best."""

    name = "material_optimizer_portfolio"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        raw_branches = cfg.get("branches")
        if not isinstance(raw_branches, list) or not raw_branches:
            raise ValueError("material_optimizer_portfolio requires branches")
        self._profile = str(cfg.get("profile") or "material_optimizer_portfolio_v1")
        self._branches = [
            self._normalize_branch(raw, index)
            for index, raw in enumerate(raw_branches)
        ]
        self._shader_params = list(shader_params)
        self._search_param_names = list(search_param_names or initial_params)
        self._shared_seed_params = copy.deepcopy(initial_params)
        self._shared_seed_score: float | None = None
        self._shared_seed_analysis: dict[str, Any] = {}
        self._best_params = copy.deepcopy(initial_params)
        self._best_score: float | None = None
        self._best_analysis: dict[str, Any] = {}
        self._branch_index = 0
        self._branch_proposals = 0
        self._total_proposals = 0
        self._branch_summaries: list[dict[str, Any]] = []
        self._branch_best_params = copy.deepcopy(initial_params)
        self._branch_best_score: float | None = None
        self._branch_best_analysis: dict[str, Any] = {}
        self._optimizer = self._build_optimizer(
            self._branches[0],
            initial_params=self._shared_seed_params,
        )
        self._branch_start_context_pending = True
        self._finished = False

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return "material_optimizer_portfolio_complete" if self._finished else None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        while self._branch_complete():
            self._finish_branch()
            if not self._advance_branch():
                self._finished = True
                return copy.deepcopy(self._best_params), self._decision(
                    nested={},
                    stop=True,
                )

        branch_ctx = (
            self._branch_start_context(ctx)
            if self._branch_start_context_pending
            else ctx
        )
        self._branch_start_context_pending = False
        candidate, nested = self._optimizer.propose(branch_ctx)
        self._branch_proposals += 1
        self._total_proposals += 1
        return candidate, self._decision(nested=nested, stop=False)

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": self._profile,
            "asset_independent": True,
            "feedback_source": "online_target_png_score_and_signed_residuals_only",
            "target_params_visible": False,
            "branch_index": self._branch_index,
            "branch_name": self._branches[self._branch_index]["name"],
            "branch_proposals": self._branch_proposals,
            "total_proposals": self._total_proposals,
            "best_fit_score": self._best_score,
            "branch_summaries": copy.deepcopy(self._branch_summaries),
            "active_branch": self._optimizer.research_summary(),
            "stop_reason": self.stop_reason(),
        }

    @staticmethod
    def _normalize_branch(raw: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("material_optimizer_portfolio branches must be objects")
        optimizer = str(raw.get("optimizer") or "jacobian")
        if optimizer not in {"jacobian", "secant", "pattern"}:
            raise ValueError(
                "material_optimizer_portfolio optimizer must be "
                "'jacobian', 'secant', or 'pattern'"
            )
        optimizer_config = raw.get(optimizer)
        if not isinstance(optimizer_config, dict):
            raise ValueError(
                "material_optimizer_portfolio branch requires "
                f"{optimizer} config"
            )
        start_from = str(raw.get("start_from") or "shared_seed")
        if start_from not in {"shared_seed", "global_best"}:
            raise ValueError(
                "material_optimizer_portfolio start_from must be "
                "'shared_seed' or 'global_best'"
            )
        return {
            "name": str(raw.get("name") or f"branch_{index}"),
            "optimizer": optimizer,
            "optimizer_config": copy.deepcopy(optimizer_config),
            "max_proposals": max(int(raw.get("max_proposals", 1)), 1),
            "start_from": start_from,
        }

    def _build_optimizer(
        self,
        branch: dict[str, Any],
        *,
        initial_params: dict[str, Any],
    ) -> OptimizerStrategy:
        strategy_type = {
            "jacobian": MaterialJacobianTrustRegionStrategy,
            "secant": MaterialSecantTrustRegionStrategy,
            "pattern": MaterialCoordinatePatternStrategy,
        }[branch["optimizer"]]
        return strategy_type(
            initial_params=copy.deepcopy(initial_params),
            shader_params=self._shader_params,
            search_param_names=self._search_param_names,
            config=branch["optimizer_config"],
        )

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if not math.isfinite(score):
            return
        if self._shared_seed_score is None:
            self._shared_seed_score = score
            self._shared_seed_analysis = copy.deepcopy(ctx.analysis)
        if self._branch_best_score is None or score > self._branch_best_score:
            self._branch_best_score = score
            self._branch_best_params = copy.deepcopy(ctx.current_params)
            self._branch_best_analysis = copy.deepcopy(ctx.analysis)
        if self._best_score is None or score > self._best_score:
            self._best_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_analysis = copy.deepcopy(ctx.analysis)

    def _branch_complete(self) -> bool:
        branch = self._branches[self._branch_index]
        return (
            self._branch_proposals >= branch["max_proposals"]
            or self._optimizer.stop_reason() is not None
        )

    def _finish_branch(self) -> None:
        branch = self._branches[self._branch_index]
        self._branch_summaries.append(
            {
                "branch_index": self._branch_index,
                "branch_name": branch["name"],
                "optimizer": branch["optimizer"],
                "start_from": branch["start_from"],
                "proposals": self._branch_proposals,
                "best_fit_score": self._branch_best_score,
                "optimizer_summary": self._optimizer.research_summary(),
            }
        )

    def _advance_branch(self) -> bool:
        next_index = self._branch_index + 1
        if next_index >= len(self._branches):
            return False
        self._branch_index = next_index
        branch = self._branches[self._branch_index]
        initial_params = (
            self._best_params
            if branch["start_from"] == "global_best"
            else self._shared_seed_params
        )
        self._optimizer = self._build_optimizer(
            branch,
            initial_params=initial_params,
        )
        self._branch_proposals = 0
        self._branch_best_params = copy.deepcopy(initial_params)
        self._branch_best_score = None
        self._branch_best_analysis = {}
        self._branch_start_context_pending = True
        return True

    def _branch_start_context(self, fallback: StrategyContext) -> StrategyContext:
        branch = self._branches[self._branch_index]
        if branch["start_from"] == "global_best":
            params = self._best_params
            score = self._best_score
            analysis = self._best_analysis
        else:
            params = self._shared_seed_params
            score = self._shared_seed_score
            analysis = self._shared_seed_analysis
        return StrategyContext(
            iteration=fallback.iteration,
            current_params=copy.deepcopy(params),
            analysis=copy.deepcopy(analysis),
            diff_score=max(
                0.0,
                1.0 - float(fallback.fit_score if score is None else score),
            ),
            fit_score=float(fallback.fit_score if score is None else score),
            state=fallback.state,
        )

    def _decision(self, *, nested: dict[str, Any], stop: bool) -> dict[str, Any]:
        branch = self._branches[self._branch_index]
        return {
            "optimizer": self.name,
            "stage": {
                "name": "material_optimizer_portfolio",
                "description": "Target-independent local optimizer portfolio",
            },
            "material_optimizer_portfolio": {
                "profile": self._profile,
                "branch_index": self._branch_index,
                "branch_name": branch["name"],
                "branch_proposals": self._branch_proposals,
                "branch_max_proposals": branch["max_proposals"],
                "total_proposals": self._total_proposals,
                "best_fit_score": self._best_score,
                "feedback_source": (
                    "online_target_png_score_and_signed_residuals_only"
                ),
                "target_params_visible": False,
                "nested": copy.deepcopy(nested),
            },
            "changes": copy.deepcopy(nested.get("changes", [])),
            "stop_reason": (
                "material_optimizer_portfolio_complete" if stop else "continue"
            ),
        }
