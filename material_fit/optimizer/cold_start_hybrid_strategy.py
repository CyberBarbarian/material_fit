"""Cold-start hybrid material optimizer strategy."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .candidate_builder import diff_params
from .cmaes_strategy import CmaesStrategy
from .effective_bounds import effective_bounds_for_param
from .cold_start_hybrid_priors import (
    COLD_START_BOOTSTRAP_ANCHORS,
    REFINE_PARAM_PRIORITY,
    REFINE_VECTOR_PRIORITY,
)
from .strategy_core import (
    CmaesStrategyConfig,
    OptimizerStrategy,
    OptimizerUnavailableError,
    StrategyContext,
)
from .strategy_utils import _clone_params, _isclose, _params_key


class ColdStartHybridStrategy(OptimizerStrategy):
    """Deterministic cold-start recovery before local black-box refinement.

    The strategy is intended for the zero-parameter case where local coordinate
    moves are too small to recover visible material structure. It first tests a
    small semantic anchor design, then sweeps high-impact parameter groups
    around the best anchor, then switches to trust-region coordinate refinement.
    """

    name = "cold_start_hybrid"
    _CMA_FAST_TRACK_MIN_SCORE = 0.87
    _CMA_FAST_TRACK_MIN_ARCHIVE_RECORDS = 8
    _CMA_FAST_TRACK_MIN_NEAR_ELITES = 4
    _CMA_FAST_TRACK_ELITE_MARGIN = 0.012
    _CMA_FAST_TRACK_RECOMBINE_ROUNDS = 1
    _CMA_FAST_TRACK_RECOMBINE_CANDIDATES = 48
    _CMA_FAST_TRACK_RECOMBINE_TOTAL_CANDIDATES = 64

    _BOOTSTRAP_ANCHORS = COLD_START_BOOTSTRAP_ANCHORS
    _REFINE_PARAM_PRIORITY = REFINE_PARAM_PRIORITY
    _REFINE_VECTOR_PRIORITY = REFINE_VECTOR_PRIORITY

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        prior_anchors: Sequence[dict[str, Any]] = (),
    ) -> None:
        self._initial_params = _clone_params(initial_params)
        self._shader_params = list(shader_params)
        self._external_prior_anchors = self._normalize_prior_anchors(prior_anchors)
        self._bootstrap_anchors = self._external_prior_anchors + self._BOOTSTRAP_ANCHORS
        self._param_info = {param.name: param for param in self._shader_params}
        self._numeric_names = [
            name
            for name, value in self._initial_params.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        self._vector_names = [
            name
            for name, value in self._initial_params.items()
            if isinstance(value, list)
            and value
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ]

        self._phase = "bootstrap"
        self._pending: list[dict[str, Any]] = []
        self._archive: list[dict[str, Any]] = []
        self._best_params = _clone_params(initial_params)
        self._best_fit_score = -math.inf
        self._best_diff_score = math.inf
        self._last_batch_best_improved = False
        self._bootstrap_queue = self._build_bootstrap_queue()
        self._group_queue: list[dict[str, Any]] = []
        self._group_queue_built = False
        self._cma_refine_strategy: CmaesStrategy | None = None
        self._cma_refine_unavailable_reason: str | None = None
        self._refine_queue: list[dict[str, Any]] = []
        self._refine_step_ratio = 0.16
        self._refine_round = 0
        self._best_anchor_queue: list[dict[str, Any]] = []
        self._best_anchor_round = 0
        self._best_anchor_step_ratio = 0.012
        self._max_best_anchor_rounds = 64
        self._archive_recombine_queue: list[dict[str, Any]] = []
        self._archive_recombine_round = 0
        self._max_archive_recombine_rounds = 3
        self._max_archive_recombine_candidates = 96
        self._archive_recombine_next_phase = "refine"
        self._archive_recombine_fast_track = False
        self._archive_recombine_fast_track_evaluations = 0
        self._diversity_probe_queue: list[dict[str, Any]] = []
        self._diversity_probe_round = 0
        self._diversity_probe_step_ratio = 0.09
        self._max_diversity_probe_rounds = 1
        self._max_diversity_probe_candidates = 24
        self._diversity_probe_next_phase = "refine"
        self._correlated_queue: list[dict[str, Any]] = []
        self._correlated_round = 0
        self._correlated_step_ratio = 0.035
        self._max_correlated_rounds = 64
        self._seen_keys: set[tuple[Any, ...]] = set()

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        if self._phase == "exhausted" and not self._pending:
            return "cold_start_hybrid_exhausted"
        return None

    def research_summary(self) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "phase": self._phase,
            "archive_size": len(self._archive),
            "best_fit_score": self._best_fit_score if math.isfinite(self._best_fit_score) else None,
            "best_diff_score": self._best_diff_score if math.isfinite(self._best_diff_score) else None,
            "pending_count": len(self._pending),
            "bootstrap_remaining": len(self._bootstrap_queue),
            "group_remaining": len(self._group_queue),
            "group_queue_built": self._group_queue_built,
            "cma_refine_active": self._cma_refine_strategy is not None,
            "cma_refine_unavailable_reason": self._cma_refine_unavailable_reason,
            "refine_remaining": len(self._refine_queue),
            "refine_step_ratio": self._refine_step_ratio,
            "refine_round": self._refine_round,
            "best_anchor_remaining": len(self._best_anchor_queue),
            "best_anchor_round": self._best_anchor_round,
            "best_anchor_step_ratio": self._best_anchor_step_ratio,
            "max_best_anchor_rounds": self._max_best_anchor_rounds,
            "archive_recombine_remaining": len(self._archive_recombine_queue),
            "archive_recombine_round": self._archive_recombine_round,
            "max_archive_recombine_rounds": self._max_archive_recombine_rounds,
            "max_archive_recombine_candidates": self._max_archive_recombine_candidates,
            "archive_recombine_effective_max_rounds": self._archive_recombine_max_rounds(),
            "archive_recombine_effective_candidate_limit": self._archive_recombine_candidate_limit(),
            "archive_recombine_next_phase": self._archive_recombine_next_phase,
            "archive_recombine_fast_track": self._archive_recombine_fast_track,
            "archive_recombine_fast_track_evaluations": self._archive_recombine_fast_track_evaluations,
            "diversity_probe_remaining": len(self._diversity_probe_queue),
            "diversity_probe_round": self._diversity_probe_round,
            "diversity_probe_step_ratio": self._diversity_probe_step_ratio,
            "max_diversity_probe_rounds": self._max_diversity_probe_rounds,
            "max_diversity_probe_candidates": self._max_diversity_probe_candidates,
            "diversity_probe_next_phase": self._diversity_probe_next_phase,
            "cma_fast_track_ready": self._should_fast_track_cma_refine(),
            "correlated_remaining": len(self._correlated_queue),
            "correlated_round": self._correlated_round,
            "correlated_step_ratio": self._correlated_step_ratio,
            "max_correlated_rounds": self._max_correlated_rounds,
            "external_prior_anchor_count": len(self._external_prior_anchors),
        }

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._pending:
            self.tell_many_scores([(float(ctx.fit_score), float(ctx.diff_score))])
        proposals = self.propose_many(ctx, count=1)
        if not proposals:
            return ctx.current_params, {
                "optimizer": self.name,
                "stage": {"name": "cold_start_exhausted"},
                "changes": [],
                "score": ctx.diff_score,
                "stop_reason": self.stop_reason() or "no_candidate_proposals",
            }
        return proposals[0]

    def propose_many(
        self,
        ctx: StrategyContext,
        *,
        count: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        count = int(count)
        if count <= 0:
            raise ValueError("count must be positive")
        if self._pending:
            raise RuntimeError(
                "propose_many() cannot run while candidates are pending; "
                "call tell_many_scores() first"
            )
        self._observe_context(ctx)
        if self._phase == "cma_refine":
            cma = self._ensure_cma_refine_strategy()
            if cma is None:
                self._phase = "exhausted"
            else:
                cma_proposals = cma.propose_many(ctx, count=count)
                proposals: list[tuple[dict[str, Any], dict[str, Any]]] = []
                for batch_index, (params, cma_decision) in enumerate(cma_proposals):
                    cloned = _clone_params(params)
                    meta = {
                        "center": "cma",
                        "cma_stage": (cma_decision.get("stage") or {}).get("name"),
                    }
                    self._pending.append({"params": cloned, "phase": self._phase, "meta": meta})
                    decision = self._build_decision(
                        ctx,
                        cloned,
                        phase=self._phase,
                        meta=meta,
                        batch_index=batch_index,
                        batch_size=len(cma_proposals),
                    )
                    if "cma_es" in cma_decision:
                        decision["cma_es"] = copy.deepcopy(cma_decision["cma_es"])
                    proposals.append((cloned, decision))
                return proposals

        proposals: list[tuple[dict[str, Any], dict[str, Any]]] = []
        duplicate_skips = 0
        while len(proposals) < count and self._phase != "exhausted":
            phase_before_queue = self._phase
            queue = self._queue_for_phase()
            if not queue:
                if self._phase != phase_before_queue:
                    continue
                if self._phase == "cma_refine":
                    if proposals:
                        return proposals
                    return self.propose_many(ctx, count=count)
                self._advance_phase_after_queue_empty()
                continue
            candidate = queue.pop(0)
            key = _params_key(candidate.get("params", {}))
            if key in self._seen_keys:
                duplicate_skips += 1
                if duplicate_skips > max(64, count * 16):
                    self._clear_current_queue()
                    self._advance_phase_after_queue_empty()
                    duplicate_skips = 0
                continue
            self._seen_keys.add(key)
            duplicate_skips = 0
            params = _clone_params(candidate["params"])
            self._pending.append({"params": params, "phase": self._phase, "meta": dict(candidate.get("meta") or {})})
            proposals.append(
                (
                    params,
                    self._build_decision(
                        ctx,
                        params,
                        phase=self._phase,
                        meta=dict(candidate.get("meta") or {}),
                        batch_index=len(proposals),
                        batch_size=count,
                    ),
                )
            )
        return proposals

    def tell_many_scores(self, score_pairs: Sequence[tuple[float, float]]) -> None:
        pairs = list(score_pairs)
        if len(pairs) != len(self._pending):
            raise RuntimeError(
                f"tell_many_scores() expected {len(self._pending)} score pairs, got {len(pairs)}"
            )
        if not self._pending:
            return

        previous_best = self._best_fit_score
        completed = list(self._pending)
        self._pending = []
        for candidate, (fit_score, diff_score) in zip(completed, pairs):
            fit = float(fit_score)
            diff = float(diff_score)
            record = {
                "phase": candidate["phase"],
                "meta": dict(candidate.get("meta") or {}),
                "params": _clone_params(candidate["params"]),
                "fit_score": fit,
                "diff_score": diff,
            }
            self._archive.append(record)
            if fit > self._best_fit_score or (
                _isclose(fit, self._best_fit_score) and diff < self._best_diff_score
            ):
                self._best_fit_score = fit
                self._best_diff_score = diff
                self._best_params = _clone_params(candidate["params"])
        self._last_batch_best_improved = self._best_fit_score > previous_best + 1.0e-6

        phases = {str(candidate.get("phase") or "") for candidate in completed}
        if "bootstrap" in phases:
            self._phase = "group_sweep"
            self._bootstrap_queue = []
            self._group_queue = []
            self._group_queue_built = False
        elif "group_sweep" in phases:
            if not self._group_queue:
                if self._should_fast_track_cma_refine():
                    self._start_archive_recombine(next_phase="cma_refine", fast_track=True)
                else:
                    self._start_archive_recombine(next_phase="refine")
        elif "archive_recombine" in phases:
            if self._archive_recombine_fast_track:
                self._archive_recombine_fast_track_evaluations += len(completed)
                if (
                    self._archive_recombine_fast_track_evaluations
                    >= self._CMA_FAST_TRACK_RECOMBINE_TOTAL_CANDIDATES
                ):
                    self._finish_archive_recombine()
                    return
            if self._last_batch_best_improved:
                self._archive_recombine_queue = []
            elif not self._archive_recombine_queue:
                self._archive_recombine_round += 1
                if self._archive_recombine_round >= self._archive_recombine_max_rounds():
                    self._finish_archive_recombine()
        elif "diversity_probe" in phases:
            if self._last_batch_best_improved:
                self._diversity_probe_queue = []
            elif not self._diversity_probe_queue:
                self._diversity_probe_round += 1
                if self._diversity_probe_round >= self._max_diversity_probe_rounds:
                    self._finish_diversity_probe()
        elif "cma_refine" in phases:
            if self._cma_refine_strategy is not None:
                self._cma_refine_strategy.tell_many_scores(pairs)
                if self._cma_refine_strategy.stop_reason() is not None:
                    self._phase = "refine"
                    self._refine_queue = []
            else:
                self._phase = "refine"
                self._refine_queue = []
        elif "refine" in phases:
            if self._last_batch_best_improved:
                self._refine_queue = []
            elif not self._refine_queue:
                self._refine_step_ratio *= 0.75
                if self._refine_step_ratio < 0.0025:
                    self._phase = "best_anchor_refine"
                    self._best_anchor_queue = []
        elif "best_anchor_refine" in phases:
            if self._last_batch_best_improved:
                self._best_anchor_queue = []
            elif not self._best_anchor_queue:
                self._best_anchor_step_ratio *= 0.85
                self._best_anchor_round += 1
                if (
                    self._best_anchor_round >= self._max_best_anchor_rounds
                    or self._best_anchor_step_ratio < 0.0015
                ):
                    self._phase = "correlated_refine"
                    self._correlated_queue = []
        elif "correlated_refine" in phases:
            if self._last_batch_best_improved:
                self._correlated_queue = []
            elif not self._correlated_queue:
                self._correlated_step_ratio *= 0.82
                self._correlated_round += 1
                if (
                    self._correlated_round >= self._max_correlated_rounds
                    or self._correlated_step_ratio < 0.001
                ):
                    self._start_archive_recombine(next_phase="cma_refine")

    def _observe_context(self, ctx: StrategyContext) -> None:
        fit_score = float(ctx.fit_score)
        diff_score = float(ctx.diff_score)
        if not math.isfinite(fit_score):
            return
        if fit_score > self._best_fit_score or (
            _isclose(fit_score, self._best_fit_score) and diff_score < self._best_diff_score
        ):
            self._best_fit_score = fit_score
            self._best_diff_score = diff_score
            self._best_params = _clone_params(ctx.current_params)

    def _queue_for_phase(self) -> list[dict[str, Any]]:
        if self._phase == "bootstrap":
            return self._bootstrap_queue
        if self._phase == "group_sweep":
            if not self._group_queue and not self._group_queue_built:
                self._group_queue = self._build_group_queue()
                self._group_queue_built = True
            if not self._group_queue and self._group_queue_built:
                return []
            return self._group_queue
        if self._phase == "archive_recombine":
            if self._archive_recombine_round >= self._archive_recombine_max_rounds():
                self._finish_archive_recombine()
                return []
            if not self._archive_recombine_queue:
                self._archive_recombine_queue = self._build_archive_recombine_queue()
            if not self._archive_recombine_queue:
                self._finish_archive_recombine()
                return []
            return self._archive_recombine_queue
        if self._phase == "diversity_probe":
            if self._diversity_probe_round >= self._max_diversity_probe_rounds:
                self._finish_diversity_probe()
                return []
            if not self._diversity_probe_queue:
                self._diversity_probe_queue = self._build_diversity_probe_queue()
            if not self._diversity_probe_queue:
                self._finish_diversity_probe()
                return []
            return self._diversity_probe_queue
        if self._phase == "refine":
            if self._refine_step_ratio < 0.0025:
                self._phase = "best_anchor_refine"
                return []
            if not self._refine_queue:
                self._refine_queue = self._build_refine_queue()
            return self._refine_queue
        if self._phase == "best_anchor_refine":
            if (
                self._best_anchor_step_ratio < 0.0015
                or self._best_anchor_round >= self._max_best_anchor_rounds
            ):
                self._phase = "correlated_refine"
                return []
            if not self._best_anchor_queue:
                self._best_anchor_queue = self._build_best_anchor_refine_queue()
            return self._best_anchor_queue
        if self._phase == "correlated_refine":
            if (
                self._correlated_step_ratio < 0.001
                or self._correlated_round >= self._max_correlated_rounds
            ):
                return []
            if not self._correlated_queue:
                self._correlated_queue = self._build_correlated_refine_queue()
            return self._correlated_queue
        return []

    def _advance_phase_after_queue_empty(self) -> None:
        if self._phase == "bootstrap":
            self._phase = "group_sweep"
            return
        if self._phase == "group_sweep":
            if self._should_fast_track_cma_refine():
                self._start_archive_recombine(next_phase="cma_refine", fast_track=True)
            else:
                self._start_archive_recombine(next_phase="refine")
            return
        if self._phase == "archive_recombine":
            self._archive_recombine_round += 1
            self._archive_recombine_queue = []
            if self._archive_recombine_round >= self._archive_recombine_max_rounds():
                self._finish_archive_recombine()
            return
        if self._phase == "diversity_probe":
            self._diversity_probe_round += 1
            self._diversity_probe_queue = []
            if self._diversity_probe_round >= self._max_diversity_probe_rounds:
                self._finish_diversity_probe()
            return
        if self._phase == "refine":
            self._refine_step_ratio *= 0.65
            if self._refine_step_ratio < 0.0025:
                self._phase = "best_anchor_refine"
                self._best_anchor_queue = []
            else:
                self._refine_round += 1
            return
        if self._phase == "best_anchor_refine":
            self._best_anchor_round += 1
            self._best_anchor_queue = []
            if (
                self._best_anchor_round >= self._max_best_anchor_rounds
                or self._best_anchor_step_ratio < 0.0015
            ):
                self._phase = "correlated_refine"
                self._correlated_queue = []
            return
        if self._phase == "correlated_refine":
            self._correlated_round += 1
            self._correlated_queue = []
            self._correlated_step_ratio *= 0.82
            if (
                self._correlated_round >= self._max_correlated_rounds
                or self._correlated_step_ratio < 0.001
            ):
                self._start_archive_recombine(next_phase="cma_refine")
            return
        self._phase = "exhausted"

    def _clear_current_queue(self) -> None:
        if self._phase == "bootstrap":
            self._bootstrap_queue = []
        elif self._phase == "group_sweep":
            self._group_queue = []
        elif self._phase == "archive_recombine":
            self._archive_recombine_queue = []
        elif self._phase == "diversity_probe":
            self._diversity_probe_queue = []
        elif self._phase == "refine":
            self._refine_queue = []
        elif self._phase == "best_anchor_refine":
            self._best_anchor_queue = []
        elif self._phase == "correlated_refine":
            self._correlated_queue = []

    def _build_bootstrap_queue(self) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for anchor in self._bootstrap_anchors:
            candidate = _clone_params(self._initial_params)
            for name in self._numeric_names:
                target = self._semantic_anchor_value(name, anchor)
                if target is None:
                    continue
                candidate[name] = self._clamp_param_value(name, float(target))
            for name in self._vector_names:
                color = self._anchor_param_vector(name, anchor)
                if color is None:
                    color = self._semantic_anchor_color(name, anchor)
                if color is None:
                    continue
                old_value = candidate.get(name)
                alpha = old_value[3] if isinstance(old_value, list) and len(old_value) > 3 else color[3]
                candidate[name] = [float(color[0]), float(color[1]), float(color[2]), float(alpha)]
            if diff_params(self._initial_params, candidate):
                queue.append({"params": candidate, "meta": {"anchor": str(anchor.get("label", "anchor"))}})
        return queue

    def _build_group_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        queue: list[dict[str, Any]] = []
        specs = (
            ("specular", +1.0, ("specular", "smoothness")),
            ("specular", -1.0, ("specular", "smoothness")),
            ("rim", +1.0, ("fresnel", "rim")),
            ("rim", -1.0, ("fresnel", "rim")),
            ("shadow", +1.0, ("shadow", "diffuse", "occlusion")),
            ("shadow", -1.0, ("shadow", "diffuse", "occlusion")),
            ("texture", +1.0, ("tex", "texture", "normal", "saturation", "contrast")),
            ("texture", -1.0, ("tex", "texture", "normal", "saturation", "contrast")),
        )
        for label, direction, tokens in specs:
            candidate = _clone_params(base)
            changed: list[str] = []
            for name in self._numeric_names:
                lower = name.lower()
                if "gamma" in lower:
                    continue
                if not any(token in lower for token in tokens):
                    continue
                new_value = self._nudge_numeric(name, float(candidate[name]), direction, ratio=0.18)
                if not _isclose(new_value, float(candidate[name])):
                    candidate[name] = new_value
                    changed.append(name)
            if not changed:
                continue
            queue.append(
                {
                    "params": candidate,
                    "meta": {
                        "group": label,
                        "direction": direction,
                        "changed_params": changed,
                    },
                }
            )
        queue.extend(self._build_balanced_energy_lift_candidates(base))
        reset_specs = (
            ("reset_visibility", ("gamma", "ao", "occlusion", "indirect", "shadow")),
            ("reset_specular", ("specular",)),
            ("reset_rim", ("rim", "fresnel")),
        )
        for label, tokens in reset_specs:
            candidate = _clone_params(base)
            changed = []
            for name in self._numeric_names:
                lower = name.lower()
                if not any(token in lower for token in tokens):
                    continue
                low, _high = self._bounds_for_param(name, float(candidate[name]))
                reset_value = max(low, 0.0)
                if _isclose(float(candidate[name]), reset_value):
                    continue
                candidate[name] = reset_value
                changed.append(name)
            if changed:
                queue.append(
                    {
                        "params": candidate,
                        "meta": {
                            "group": label,
                            "direction": 0.0,
                            "changed_params": changed,
                        },
                    }
                )
        return queue

    def _build_balanced_energy_lift_candidates(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        names = [
            name
            for name in self._ordered_refine_names()
            if name in base and isinstance(base[name], (int, float)) and not isinstance(base[name], bool)
        ]
        adjustments = (
            (("indirect",), +1.0, 0.080),
            (("specular", "intensity"), +1.0, 0.020),
            (("specular", "threshold"), +1.0, 0.030),
            (("specular", "power"), -1.0, 0.040),
            (("rim", "intensity"), +1.0, 0.020),
            (("rim", "width"), +1.0, 0.040),
            (("normal", "scale"), +1.0, 0.006),
            (("ao",), +1.0, 0.006),
            (("shadow", "smooth"), +1.0, 0.020),
            (("saturation",), +1.0, 0.005),
        )
        queue: list[dict[str, Any]] = []
        for label, scale in (("balanced_energy_lift", 1.0), ("balanced_energy_lift_strong", 1.35)):
            candidate = _clone_params(base)
            changed: list[str] = []
            applied: dict[str, float] = {}
            for tokens, direction, ratio in adjustments:
                name = self._first_matching_param(names, tokens)
                if not name:
                    continue
                old_value = float(candidate[name])
                signed_ratio = ratio * scale * direction
                new_value = self._nudge_numeric(name, old_value, direction, ratio=ratio * scale)
                if _isclose(new_value, old_value):
                    continue
                candidate[name] = new_value
                changed.append(name)
                applied[name] = signed_ratio
            if not changed:
                continue
            queue.append(
                {
                    "params": candidate,
                    "meta": {
                        "group": label,
                        "direction": +1.0,
                        "changed_params": changed,
                        "ratios": applied,
                    },
                }
            )
        return queue

    def _ensure_cma_refine_strategy(self) -> CmaesStrategy | None:
        if self._cma_refine_strategy is not None:
            return self._cma_refine_strategy
        warm_history = self._cma_refine_warm_history()
        config = CmaesStrategyConfig(
            mode="warm",
            warm_start_iters=24,
            population_size=12,
            sigma=0.18,
            seed=20260703,
            hint_bias_mix_ratio=0.0,
            stagnation_patience=96,
            stagnation_min_delta=0.0002,
            stagnation_min_evaluations=96,
            stagnation_max_restarts=2,
            stagnation_stop_after_restarts=False,
            restart_center_mode="alternate",
            restart_population_multiplier=1.5,
            restart_population_schedule="bipop",
            initial_design_samples=0,
        )
        try:
            self._cma_refine_strategy = CmaesStrategy(
                initial_params=_clone_params(self._best_params),
                shader_params=self._shader_params,
                config=config,
                warm_start_history=warm_history,
                param_whitelist=self._cma_refine_param_whitelist(),
            )
        except OptimizerUnavailableError as exc:
            self._cma_refine_unavailable_reason = str(exc)
            return None
        return self._cma_refine_strategy

    def _cma_refine_param_whitelist(self) -> list[str]:
        names = list(self._numeric_names)
        for name in self._ordered_refine_vector_names():
            if name not in names:
                names.append(name)
        return names

    def _cma_refine_warm_history(self) -> list[tuple[dict[str, Any], float]]:
        records = [
            record
            for record in self._archive
            if isinstance(record.get("fit_score"), (int, float)) and isinstance(record.get("params"), dict)
        ]
        records.sort(key=lambda item: (float(item["fit_score"]), -float(item.get("diff_score", math.inf))), reverse=True)
        warm: list[tuple[dict[str, Any], float]] = []
        seen: set[tuple[Any, ...]] = set()
        best_key = _params_key(self._best_params)
        warm.append((_clone_params(self._best_params), float(self._best_fit_score)))
        seen.add(best_key)
        for record in records:
            params = _clone_params(record["params"])
            key = _params_key(params)
            if key in seen:
                continue
            seen.add(key)
            warm.append((params, float(record["fit_score"])))
            if len(warm) >= 24:
                break
        return warm

    def _should_fast_track_cma_refine(self) -> bool:
        if not self._external_prior_anchors:
            return False
        if not math.isfinite(self._best_fit_score):
            return False
        if self._best_fit_score < self._CMA_FAST_TRACK_MIN_SCORE:
            return False
        records = self._ranked_archive_records()
        if len(records) < self._CMA_FAST_TRACK_MIN_ARCHIVE_RECORDS:
            return False
        min_elite_fit = self._best_fit_score - self._CMA_FAST_TRACK_ELITE_MARGIN
        near_elite_count = sum(1 for record in records if float(record["fit_score"]) >= min_elite_fit)
        return near_elite_count >= self._CMA_FAST_TRACK_MIN_NEAR_ELITES

    def _start_cma_refine(self) -> None:
        self._phase = "cma_refine"
        self._cma_refine_strategy = None
        self._cma_refine_unavailable_reason = None

    def _archive_recombine_max_rounds(self) -> int:
        if self._archive_recombine_fast_track:
            return self._CMA_FAST_TRACK_RECOMBINE_ROUNDS
        return self._max_archive_recombine_rounds

    def _archive_recombine_candidate_limit(self) -> int:
        if self._archive_recombine_fast_track:
            remaining_total = max(
                0,
                self._CMA_FAST_TRACK_RECOMBINE_TOTAL_CANDIDATES
                - self._archive_recombine_fast_track_evaluations,
            )
            return min(self._CMA_FAST_TRACK_RECOMBINE_CANDIDATES, remaining_total)
        return self._max_archive_recombine_candidates

    def _start_archive_recombine(self, *, next_phase: str, fast_track: bool = False) -> None:
        self._phase = "archive_recombine"
        self._archive_recombine_next_phase = next_phase
        self._archive_recombine_fast_track = bool(fast_track)
        self._archive_recombine_fast_track_evaluations = 0
        self._archive_recombine_queue = []
        self._archive_recombine_round = 0

    def _finish_archive_recombine(self) -> None:
        next_phase = self._archive_recombine_next_phase
        fast_track = self._archive_recombine_fast_track
        self._archive_recombine_queue = []
        self._archive_recombine_fast_track = False
        if fast_track and next_phase == "cma_refine":
            self._start_cma_refine()
            return
        if next_phase in {"refine", "cma_refine"}:
            self._start_diversity_probe(next_phase=next_phase)
            return
        if next_phase == "diversity_probe":
            self._start_diversity_probe(next_phase="cma_refine")
            return
        if next_phase == "cma_refine":
            self._start_cma_refine()
            return
        if next_phase == "refine":
            self._phase = "refine"
            self._refine_queue = []
            return
        self._phase = next_phase

    def _start_diversity_probe(self, *, next_phase: str) -> None:
        self._phase = "diversity_probe"
        self._diversity_probe_next_phase = next_phase
        self._diversity_probe_queue = []
        self._diversity_probe_round = 0

    def _finish_diversity_probe(self) -> None:
        next_phase = self._diversity_probe_next_phase
        self._diversity_probe_queue = []
        if next_phase == "cma_refine":
            self._phase = "cma_refine"
            self._cma_refine_strategy = None
            return
        if next_phase == "refine":
            self._phase = "refine"
            self._refine_queue = []
            return
        self._phase = next_phase

    def _build_archive_recombine_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        base_key = _params_key(base)
        records = self._ranked_archive_records()
        donors: list[dict[str, Any]] = []
        seen_donor_keys = {base_key}
        for record in records:
            params = _clone_params(record["params"])
            key = _params_key(params)
            if key in seen_donor_keys:
                continue
            seen_donor_keys.add(key)
            donors.append({**record, "params": params})
            if len(donors) >= 6:
                break
        if not donors:
            return []

        numeric_names = [
            name
            for name in self._ordered_refine_names()
            if name in base and isinstance(base[name], (int, float)) and not isinstance(base[name], bool)
        ]
        vector_names = [
            name
            for name in self._ordered_refine_vector_names()
            if name in base and isinstance(base[name], list)
        ]
        if not numeric_names and not vector_names:
            return []

        queue: list[dict[str, Any]] = []
        local_seen: set[tuple[Any, ...]] = set()
        candidate_limit = self._archive_recombine_candidate_limit()

        def append_candidate(candidate: dict[str, Any], meta: dict[str, Any], changed: list[str]) -> None:
            if len(queue) >= candidate_limit:
                return
            if not changed:
                return
            key = _params_key(candidate)
            if key == base_key or key in local_seen or key in self._seen_keys:
                return
            local_seen.add(key)
            queue.append({"params": candidate, "meta": {**meta, "changed_params": changed}})

        for donor_rank, donor_record in enumerate(donors):
            if len(queue) >= candidate_limit:
                break
            donor_params = donor_record["params"]
            donor_meta = {
                "center": "archive",
                "donor_rank": donor_rank,
                "donor_phase": donor_record.get("phase"),
                "donor_fit_score": float(donor_record.get("fit_score", 0.0)),
                "archive_recombine_round": self._archive_recombine_round,
                "next_phase": self._archive_recombine_next_phase,
            }

            for group_label, names in self._archive_recombine_numeric_groups(numeric_names):
                if len(queue) >= candidate_limit:
                    break
                candidate, changed = self._copy_donor_values(base, donor_params, names)
                append_candidate(
                    candidate,
                    {
                        **donor_meta,
                        "mode": "group_transfer",
                        "group": group_label,
                    },
                    changed,
                )

            if vector_names:
                candidate, changed = self._copy_donor_values(base, donor_params, vector_names[:4])
                append_candidate(
                    candidate,
                    {
                        **donor_meta,
                        "mode": "group_transfer",
                        "group": "color_vectors",
                    },
                    changed,
                )

            for name in numeric_names[:10]:
                if len(queue) >= candidate_limit:
                    break
                candidate, changed = self._copy_donor_values(base, donor_params, [name])
                append_candidate(
                    candidate,
                    {
                        **donor_meta,
                        "mode": "single_transfer",
                        "param": name,
                    },
                    changed,
                )

            for name in vector_names[:4]:
                if len(queue) >= candidate_limit:
                    break
                candidate, changed = self._copy_donor_values(base, donor_params, [name])
                append_candidate(
                    candidate,
                    {
                        **donor_meta,
                        "mode": "single_transfer",
                        "param": name,
                    },
                    changed,
                )

            blend_names = numeric_names[:12] + vector_names[:4]
            for ratio in self._archive_recombine_mix_ratios():
                if len(queue) >= candidate_limit:
                    break
                candidate, changed = self._blend_donor_values(base, donor_params, blend_names, ratio=ratio)
                append_candidate(
                    candidate,
                    {
                        **donor_meta,
                        "mode": "blend",
                        "mix_ratio": ratio,
                    },
                    changed,
                )

        return queue

    def _ranked_archive_records(self) -> list[dict[str, Any]]:
        records = [
            record
            for record in self._archive
            if isinstance(record.get("fit_score"), (int, float)) and isinstance(record.get("params"), dict)
        ]
        records.sort(key=lambda item: (float(item["fit_score"]), -float(item.get("diff_score", math.inf))), reverse=True)
        return records

    def _archive_recombine_numeric_groups(self, names: Sequence[str]) -> list[tuple[str, list[str]]]:
        groups = (
            (
                "visibility_texture",
                ("gamma", "tex", "texture", "saturation", "contrast", "occlusion", "ao", "indirect", "normal"),
            ),
            ("specular_rim", ("specular", "rim", "fresnel", "smoothness")),
            ("shadow_shape", ("shadow", "diffuse", "threshold", "smooth")),
        )
        out: list[tuple[str, list[str]]] = []
        for label, tokens in groups:
            selected = [name for name in names if any(token in name.lower() for token in tokens)]
            if selected:
                out.append((label, selected[:10]))
        return out

    def _archive_recombine_mix_ratios(self) -> tuple[float, ...]:
        if self._archive_recombine_round <= 0:
            return (0.35, 0.50, 0.65)
        if self._archive_recombine_round == 1:
            return (0.20, 0.80)
        return (0.50,)

    def _build_diversity_probe_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        base_key = _params_key(base)
        records = self._ranked_archive_records()
        centers: list[tuple[str, int, dict[str, Any], float | None]] = [("best", 0, base, None)]
        seen_center_keys = {base_key}
        for record in records:
            params = _clone_params(record["params"])
            key = _params_key(params)
            if key in seen_center_keys:
                continue
            seen_center_keys.add(key)
            centers.append(("archive", len(centers), params, float(record.get("fit_score", 0.0))))
            if len(centers) >= 4:
                break

        numeric_names = [
            name
            for name in self._ordered_refine_names()
            if name in base and isinstance(base[name], (int, float)) and not isinstance(base[name], bool)
        ]
        vector_names = [
            name
            for name in self._ordered_refine_vector_names()
            if name in base and isinstance(base[name], list)
        ]
        if len(numeric_names) < 2 and not vector_names:
            return []

        elite_refs = [_clone_params(self._best_params)]
        for record in records[:12]:
            params = _clone_params(record["params"])
            if _params_key(params) != base_key:
                elite_refs.append(params)

        step_ratio = max(0.025, self._diversity_probe_step_ratio * (0.72 ** self._diversity_probe_round))
        min_distance = max(0.045, min(0.085, step_ratio * 0.5))
        pattern_count = min(18, max(10, len(numeric_names)))
        queue: list[dict[str, Any]] = []
        local_seen: set[tuple[Any, ...]] = set()

        def append_candidate(candidate: dict[str, Any], meta: dict[str, Any], changed: list[str]) -> None:
            if len(queue) >= self._max_diversity_probe_candidates:
                return
            if len(changed) < 2:
                return
            key = _params_key(candidate)
            if key == base_key or key in local_seen or key in self._seen_keys:
                return
            novelty_distance = self._min_normalized_distance(candidate, elite_refs)
            if novelty_distance < min_distance:
                return
            local_seen.add(key)
            queue.append(
                {
                    "params": candidate,
                    "meta": {
                        **meta,
                        "changed_params": changed,
                        "diversity_probe_round": self._diversity_probe_round,
                        "step_ratio": step_ratio,
                        "min_elite_distance": novelty_distance,
                        "required_min_elite_distance": min_distance,
                        "next_phase": self._diversity_probe_next_phase,
                    },
                }
            )

        for center_label, center_rank, center, center_fit_score in centers:
            if len(queue) >= self._max_diversity_probe_candidates:
                break
            for pattern_index in range(pattern_count):
                if len(queue) >= self._max_diversity_probe_candidates:
                    break
                candidate = _clone_params(center)
                changed: list[str] = []
                directions: dict[str, float] = {}
                for rank, name in enumerate(numeric_names[:18]):
                    direction = self._diversity_direction(pattern_index + center_rank * 13, rank)
                    rank_scale = 1.0 if rank < 12 else 0.7
                    old_value = float(candidate[name])
                    new_value = self._nudge_numeric(name, old_value, direction, ratio=step_ratio * rank_scale)
                    if _isclose(new_value, old_value):
                        continue
                    candidate[name] = new_value
                    changed.append(name)
                    directions[name] = direction
                for vector_rank, name in enumerate(vector_names[:4]):
                    value = candidate.get(name)
                    if not isinstance(value, list):
                        continue
                    next_value = list(value)
                    vector_changed = False
                    for component_index in range(min(3, len(next_value))):
                        item = next_value[component_index]
                        if isinstance(item, bool) or not isinstance(item, (int, float)):
                            continue
                        direction = self._diversity_direction(
                            pattern_index + center_rank * 13,
                            len(numeric_names) + vector_rank * 3 + component_index,
                        )
                        low, high = self._bounds_for_vector_component(name, component_index, float(item))
                        width = max(high - low, 1.0e-9)
                        next_item = max(low, min(high, float(item) + direction * step_ratio * 0.75 * width))
                        if _isclose(next_item, float(item)):
                            continue
                        next_value[component_index] = next_item
                        vector_changed = True
                    if vector_changed:
                        candidate[name] = next_value
                        changed.append(name)
                append_candidate(
                    candidate,
                    {
                        "center": center_label,
                        "center_rank": center_rank,
                        "center_fit_score": center_fit_score,
                        "mode": "novel_pattern",
                        "pattern_index": pattern_index,
                        "directions": directions,
                    },
                    changed,
                )

        for donor_rank, record in enumerate(records[:8]):
            if len(queue) >= self._max_diversity_probe_candidates:
                break
            donor = _clone_params(record["params"])
            if _params_key(donor) == base_key:
                continue
            for factor in (0.75, 1.25):
                if len(queue) >= self._max_diversity_probe_candidates:
                    break
                candidate, changed = self._extrapolate_away_from_donor(
                    base,
                    donor,
                    numeric_names[:18],
                    vector_names[:4],
                    factor=factor,
                )
                append_candidate(
                    candidate,
                    {
                        "center": "best",
                        "mode": "elite_extrapolation",
                        "donor_rank": donor_rank,
                        "donor_fit_score": float(record.get("fit_score", 0.0)),
                        "factor": factor,
                    },
                    changed,
                )

        return queue

    @staticmethod
    def _diversity_direction(pattern_index: int, rank: int) -> float:
        value = ((pattern_index + 5) * 1664525 + (rank + 23) * 1013904223) & 0xFFFFFFFF
        return 1.0 if (value.bit_count() % 2 == 0) else -1.0

    def _extrapolate_away_from_donor(
        self,
        base: dict[str, Any],
        donor: dict[str, Any],
        numeric_names: Sequence[str],
        vector_names: Sequence[str],
        *,
        factor: float,
    ) -> tuple[dict[str, Any], list[str]]:
        candidate = _clone_params(base)
        changed: list[str] = []
        for name in numeric_names:
            base_value = candidate.get(name)
            donor_value = donor.get(name)
            if (
                isinstance(base_value, bool)
                or isinstance(donor_value, bool)
                or not isinstance(base_value, (int, float))
                or not isinstance(donor_value, (int, float))
            ):
                continue
            next_value = float(base_value) + (float(base_value) - float(donor_value)) * float(factor)
            next_value = self._clamp_param_value(name, next_value)
            if _isclose(next_value, float(base_value)):
                continue
            candidate[name] = next_value
            changed.append(name)
        for name in vector_names:
            base_value = candidate.get(name)
            donor_value = donor.get(name)
            if not isinstance(base_value, list) or not isinstance(donor_value, list):
                continue
            next_vector = list(base_value)
            vector_changed = False
            for index in range(min(3, len(base_value), len(donor_value))):
                base_item = base_value[index]
                donor_item = donor_value[index]
                if (
                    isinstance(base_item, bool)
                    or isinstance(donor_item, bool)
                    or not isinstance(base_item, (int, float))
                    or not isinstance(donor_item, (int, float))
                ):
                    continue
                low, high = self._bounds_for_vector_component(name, index, float(base_item))
                next_item = float(base_item) + (float(base_item) - float(donor_item)) * float(factor)
                next_item = max(low, min(high, next_item))
                if _isclose(next_item, float(base_item)):
                    continue
                next_vector[index] = next_item
                vector_changed = True
            if vector_changed:
                candidate[name] = next_vector
                changed.append(name)
        return candidate, changed

    def _copy_donor_values(
        self,
        base: dict[str, Any],
        donor: dict[str, Any],
        names: Sequence[str],
    ) -> tuple[dict[str, Any], list[str]]:
        candidate = _clone_params(base)
        changed: list[str] = []
        for name in names:
            if name not in candidate or name not in donor:
                continue
            base_value = candidate[name]
            donor_value = donor[name]
            if isinstance(base_value, (int, float)) and not isinstance(base_value, bool):
                if not isinstance(donor_value, (int, float)) or isinstance(donor_value, bool):
                    continue
                new_value = self._clamp_param_value(name, float(donor_value))
                if _isclose(new_value, float(base_value)):
                    continue
                candidate[name] = new_value
                changed.append(name)
                continue
            if isinstance(base_value, list) and isinstance(donor_value, list):
                new_vector = self._copy_donor_vector(name, base_value, donor_value)
                if new_vector == base_value:
                    continue
                candidate[name] = new_vector
                changed.append(name)
        return candidate, changed

    def _blend_donor_values(
        self,
        base: dict[str, Any],
        donor: dict[str, Any],
        names: Sequence[str],
        *,
        ratio: float,
    ) -> tuple[dict[str, Any], list[str]]:
        candidate = _clone_params(base)
        changed: list[str] = []
        for name in names:
            if name not in candidate or name not in donor:
                continue
            base_value = candidate[name]
            donor_value = donor[name]
            if isinstance(base_value, (int, float)) and not isinstance(base_value, bool):
                if not isinstance(donor_value, (int, float)) or isinstance(donor_value, bool):
                    continue
                blended = float(base_value) + (float(donor_value) - float(base_value)) * float(ratio)
                new_value = self._clamp_param_value(name, blended)
                if _isclose(new_value, float(base_value)):
                    continue
                candidate[name] = new_value
                changed.append(name)
                continue
            if isinstance(base_value, list) and isinstance(donor_value, list):
                new_vector = self._blend_donor_vector(name, base_value, donor_value, ratio=ratio)
                if new_vector == base_value:
                    continue
                candidate[name] = new_vector
                changed.append(name)
        return candidate, changed

    def _copy_donor_vector(self, name: str, base_value: list[Any], donor_value: list[Any]) -> list[Any]:
        out = list(base_value)
        for index in range(min(3, len(out), len(donor_value))):
            item = donor_value[index]
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                continue
            low, high = self._bounds_for_vector_component(name, index, float(out[index]))
            out[index] = max(low, min(high, float(item)))
        return out

    def _blend_donor_vector(
        self,
        name: str,
        base_value: list[Any],
        donor_value: list[Any],
        *,
        ratio: float,
    ) -> list[Any]:
        out = list(base_value)
        for index in range(min(3, len(out), len(donor_value))):
            base_item = out[index]
            donor_item = donor_value[index]
            if (
                isinstance(base_item, bool)
                or isinstance(donor_item, bool)
                or not isinstance(base_item, (int, float))
                or not isinstance(donor_item, (int, float))
            ):
                continue
            low, high = self._bounds_for_vector_component(name, index, float(base_item))
            blended = float(base_item) + (float(donor_item) - float(base_item)) * float(ratio)
            out[index] = max(low, min(high, blended))
        return out

    def _build_refine_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        names = self._ordered_refine_names()
        queue: list[dict[str, Any]] = []
        for name in names:
            if name not in base or not isinstance(base[name], (int, float)) or isinstance(base[name], bool):
                continue
            for direction in (+1.0, -1.0):
                candidate = _clone_params(base)
                new_value = self._nudge_numeric(name, float(candidate[name]), direction, ratio=self._refine_step_ratio)
                if _isclose(new_value, float(candidate[name])):
                    continue
                candidate[name] = new_value
                queue.append(
                    {
                        "params": candidate,
                        "meta": {
                            "param": name,
                            "direction": direction,
                            "step_ratio": self._refine_step_ratio,
                            "refine_round": self._refine_round,
                            "changed_params": [name],
                        },
                    }
                )
        queue.extend(
            self._build_vector_refine_candidates(
                base,
                ratio=self._refine_step_ratio,
                meta={
                    "refine_round": self._refine_round,
                    "step_ratio": self._refine_step_ratio,
                },
            )
        )
        if queue:
            self._refine_round += 1
        return queue

    def _build_best_anchor_refine_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        queue: list[dict[str, Any]] = []
        ratio = self._best_anchor_step_ratio
        names = self._ordered_refine_names()

        for name in names:
            if name not in base or not isinstance(base[name], (int, float)) or isinstance(base[name], bool):
                continue
            for direction in (+1.0, -1.0):
                candidate = _clone_params(base)
                new_value = self._nudge_numeric(name, float(candidate[name]), direction, ratio=ratio)
                if _isclose(new_value, float(candidate[name])):
                    continue
                candidate[name] = new_value
                queue.append(
                    {
                        "params": candidate,
                        "meta": {
                            "center": "best",
                            "param": name,
                            "direction": direction,
                            "changed_params": [name],
                            "best_anchor_round": self._best_anchor_round,
                            "step_ratio": ratio,
                        },
                    }
                )

        for first, second in self._best_anchor_param_pairs(names):
            for direction in (+1.0, -1.0):
                candidate = _clone_params(base)
                changed: list[str] = []
                for name in (first, second):
                    if name not in candidate or not isinstance(candidate[name], (int, float)) or isinstance(candidate[name], bool):
                        continue
                    new_value = self._nudge_numeric(name, float(candidate[name]), direction, ratio=ratio * 0.75)
                    if _isclose(new_value, float(candidate[name])):
                        continue
                    candidate[name] = new_value
                    changed.append(name)
                if not changed:
                    continue
                queue.append(
                    {
                        "params": candidate,
                        "meta": {
                            "center": "best",
                            "pair": [first, second],
                            "direction": direction,
                            "changed_params": changed,
                            "best_anchor_round": self._best_anchor_round,
                            "step_ratio": ratio * 0.75,
                        },
                    }
                )

        queue.extend(
            self._build_vector_refine_candidates(
                base,
                ratio=ratio,
                meta={
                    "center": "best",
                    "best_anchor_round": self._best_anchor_round,
                    "step_ratio": ratio,
                },
            )
        )

        return queue

    def _build_vector_refine_candidates(
        self,
        base: dict[str, Any],
        *,
        ratio: float,
        meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        vector_names = self._ordered_refine_vector_names()
        if not vector_names:
            return []
        queue: list[dict[str, Any]] = []
        for component_index in range(3):
            for name in vector_names:
                value = base.get(name)
                if (
                    not isinstance(value, list)
                    or component_index >= len(value)
                    or isinstance(value[component_index], bool)
                    or not isinstance(value[component_index], (int, float))
                ):
                    continue
                for direction in (+1.0, -1.0):
                    candidate = _clone_params(base)
                    new_value = self._nudge_vector_component(
                        name,
                        value,
                        component_index,
                        direction,
                        ratio=ratio,
                    )
                    if new_value == value:
                        continue
                    candidate[name] = new_value
                    queue.append(
                        {
                            "params": candidate,
                            "meta": {
                                **meta,
                                "param": name,
                                "component_index": component_index,
                                "component": f"{name}[{component_index}]",
                                "direction": direction,
                                "changed_params": [name],
                            },
                        }
                    )
        return queue

    def _build_correlated_refine_queue(self) -> list[dict[str, Any]]:
        base = _clone_params(self._best_params)
        active_names = [
            name
            for name in self._ordered_refine_names()
            if name in base and isinstance(base[name], (int, float)) and not isinstance(base[name], bool)
        ]
        if len(active_names) < 2:
            return []

        queue: list[dict[str, Any]] = []
        names = active_names[: min(14, len(active_names))]
        pattern_count = min(32, max(12, len(names) * 2))
        for pattern_index in range(pattern_count):
            candidate = _clone_params(base)
            changed: list[str] = []
            directions: dict[str, float] = {}
            for rank, name in enumerate(names):
                direction = self._correlated_direction(pattern_index, rank)
                rank_scale = 1.0 if rank < 8 else 0.65
                local_ratio = self._correlated_step_ratio * rank_scale
                new_value = self._nudge_numeric(name, float(candidate[name]), direction, ratio=local_ratio)
                if _isclose(new_value, float(candidate[name])):
                    continue
                candidate[name] = new_value
                changed.append(name)
                directions[name] = direction
            if len(changed) < 2:
                continue
            queue.append(
                {
                    "params": candidate,
                    "meta": {
                        "center": "best",
                        "pattern_index": pattern_index,
                        "changed_params": changed,
                        "directions": directions,
                        "correlated_round": self._correlated_round,
                        "step_ratio": self._correlated_step_ratio,
                    },
                }
            )
        return queue

    @staticmethod
    def _correlated_direction(pattern_index: int, rank: int) -> float:
        value = ((pattern_index + 1) * 1103515245 + (rank + 17) * 12345) & 0x7FFFFFFF
        return 1.0 if (value.bit_count() % 2 == 0) else -1.0

    def _best_anchor_param_pairs(self, ordered_names: Sequence[str]) -> list[tuple[str, str]]:
        pair_specs = (
            (("gamma",), ("tex", "texture")),
            (("gamma",), ("saturation",)),
            (("specular", "intensity"), ("rim", "fresnel")),
            (("shadow", "threshold"), ("shadow", "smooth")),
            (("ao", "occlusion"), ("indirect", "emission")),
        )
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for first_tokens, second_tokens in pair_specs:
            first = self._first_matching_param(ordered_names, first_tokens)
            second = self._first_matching_param(ordered_names, second_tokens, exclude={first} if first else set())
            if not first or not second:
                continue
            key = (first, second)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
        return pairs

    @staticmethod
    def _first_matching_param(
        ordered_names: Sequence[str],
        tokens: Sequence[str],
        *,
        exclude: set[str] | None = None,
    ) -> str | None:
        excluded = exclude or set()
        for name in ordered_names:
            if name in excluded:
                continue
            lower = name.lower()
            if all(token in lower for token in tokens):
                return name
        return None

    def _ordered_refine_names(self) -> list[str]:
        available = set(self._numeric_names)
        ordered = [name for name in self._REFINE_PARAM_PRIORITY if name in available]
        ordered.extend(name for name in self._numeric_names if name not in ordered)
        return ordered

    def _ordered_refine_vector_names(self) -> list[str]:
        available = {
            name
            for name in self._vector_names
            if self._is_refinable_color_vector(name)
        }
        ordered = [name for name in self._REFINE_VECTOR_PRIORITY if name in available]
        ordered.extend(name for name in self._vector_names if name in available and name not in ordered)
        return ordered

    def _is_refinable_color_vector(self, name: str) -> bool:
        param = self._param_info.get(name)
        if param is not None and str(param.param_type).strip().lower() == "color":
            return True
        lower = name.lower()
        return any(token in lower for token in ("color", "tint", "albedo"))

    def _build_decision(
        self,
        ctx: StrategyContext,
        proposed: dict[str, Any],
        *,
        phase: str,
        meta: dict[str, Any],
        batch_index: int,
        batch_size: int,
    ) -> dict[str, Any]:
        stage_name = {
            "bootstrap": "cold_start_bootstrap",
            "group_sweep": "cold_start_group_sweep",
            "archive_recombine": "cold_start_archive_recombine",
            "diversity_probe": "cold_start_diversity_probe",
            "cma_refine": "cold_start_cma_refine",
            "refine": "cold_start_refine",
            "best_anchor_refine": "cold_start_best_anchor_refine",
            "correlated_refine": "cold_start_correlated_refine",
        }.get(phase, "cold_start_exhausted")
        changes = diff_params(ctx.current_params, proposed)
        return {
            "optimizer": self.name,
            "stage": {
                "name": stage_name,
                "description": (
                    "Cold-start trust-region refinement"
                    if phase == "refine"
                    else "Cold-start CMA-ES refinement"
                    if phase == "cma_refine"
                    else "Cold-start archive recombination"
                    if phase == "archive_recombine"
                    else "Cold-start diversity probe"
                    if phase == "diversity_probe"
                    else "Cold-start correlated refinement"
                    if phase == "correlated_refine"
                    else "Cold-start semantic search"
                ),
            },
            "score": ctx.diff_score,
            "iteration_gain": None,
            "changes": [
                {
                    "param": change["param"],
                    "old": change.get("before"),
                    "new": change.get("after"),
                    "reason": stage_name,
                }
                for change in changes
            ],
            "stop_reason": "continue" if changes else "no_effective_change",
            "cold_start_hybrid": {
                "phase": phase,
                "meta": meta,
                "best_fit_score": self._best_fit_score if math.isfinite(self._best_fit_score) else None,
                "best_diff_score": self._best_diff_score if math.isfinite(self._best_diff_score) else None,
                "archive_size": len(self._archive),
                "batch": {
                    "index": int(batch_index),
                    "size": int(batch_size),
                    "pending_count": len(self._pending),
                },
                "refine_step_ratio": self._refine_step_ratio,
            },
        }

    def _semantic_anchor_value(self, name: str, anchor: dict[str, Any]) -> float | None:
        param_values = anchor.get("param_values")
        if isinstance(param_values, dict) and name in param_values:
            return float(param_values[name])
        lower = name.lower()
        if "gamma" in lower:
            return self._anchor_float(anchor, "gamma")
        if "giintensity" in lower or lower.endswith("_gi") or lower.endswith("gi"):
            return self._anchor_float(anchor, "gi")
        if "occlusion" in lower or "aostrength" in lower or lower.startswith("u_ao") or "aopower" in lower:
            return self._anchor_float(anchor, "occlusion")
        if "indirect" in lower and ("strength" in lower or "intensity" in lower or "power" in lower):
            return self._anchor_float(anchor, "indirect")
        if "metallic" in lower:
            if "metallic" in anchor:
                return self._anchor_float(anchor, "metallic")
            if anchor.get("_external_prior"):
                return None
            return 0.0
        if "smoothness" in lower:
            return self._anchor_float(anchor, "smoothness")
        if ("diffuse" in lower or "shadow" in lower) and "threshold" in lower:
            return self._anchor_float(anchor, "threshold")
        if ("diffuse" in lower or "shadow" in lower) and "smooth" in lower:
            return self._anchor_float(anchor, "diffuse_smooth")
        if "specular" in lower and ("intensity" in lower or "strength" in lower):
            return self._anchor_float(anchor, "specular")
        if "specular" in lower and ("pow" in lower or "power" in lower):
            return self._anchor_float(anchor, "specular_power")
        if "specular" in lower and "threshold" in lower:
            return self._anchor_float(anchor, "specular_threshold")
        if ("fresnel" in lower or "rim" in lower) and ("intensity" in lower or "strength" in lower):
            return self._anchor_float(anchor, "fresnel")
        if ("fresnel" in lower or "rim" in lower) and ("width" in lower or "threshold" in lower):
            return self._anchor_float(anchor, "rim_width")
        if "normal" in lower and ("scale" in lower or "strength" in lower):
            return self._anchor_float(anchor, "normal")
        if "saturation" in lower:
            return self._anchor_float(anchor, "saturation")
        if "contrast" in lower:
            return self._anchor_float(anchor, "contrast")
        if "lightness" in lower or "brightness" in lower:
            return self._anchor_float(anchor, "lightness")
        if "hue" in lower:
            if "hue" in anchor:
                return self._anchor_float(anchor, "hue")
            if anchor.get("_external_prior"):
                return None
            return 0.0
        if "tex" in lower and ("power" in lower or "scale" in lower or "intensity" in lower):
            return self._anchor_float(anchor, "texture_power")
        if "texture" in lower and ("power" in lower or "scale" in lower or "intensity" in lower):
            return self._anchor_float(anchor, "texture_power")
        if "emission" in lower and ("scale" in lower or "intensity" in lower or "pow" in lower or "power" in lower):
            return self._anchor_float(anchor, "emission")
        if "intensity" in lower or "strength" in lower:
            specular = self._anchor_float(anchor, "specular")
            if specular is None:
                return None
            return min(specular, 1.0)
        return None

    def _semantic_anchor_color(self, name: str, anchor: dict[str, Any]) -> list[float] | None:
        lower = name.lower()
        if "specular" in lower and "color" in lower:
            return self._anchor_color(anchor, "specular_color")
        if ("fresnel" in lower or "rim" in lower) and "color" in lower:
            return self._anchor_color(anchor, "fresnel_color")
        if "shadow" in lower and "color" in lower:
            return self._anchor_color(anchor, "shadow_color")
        if "base" in lower and "color" in lower:
            return self._anchor_color(anchor, "base_color")
        if "albedo" in lower and "color" in lower:
            return self._anchor_color(anchor, "base_color")
        if lower in {"u_color", "color"} or lower.endswith("maincolor") or lower.endswith("tintcolor"):
            return self._anchor_color(anchor, "base_color")
        return None

    @staticmethod
    def _normalize_prior_anchors(anchors: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        normalized: list[dict[str, Any]] = []
        for index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict):
                continue
            item = copy.deepcopy(anchor)
            label = str(item.get("label") or f"external_prior_{index}")
            item["label"] = label
            item["_external_prior"] = True
            normalized.append(item)
        return tuple(normalized)

    @staticmethod
    def _anchor_float(anchor: dict[str, Any], key: str) -> float | None:
        value = anchor.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _anchor_color(anchor: dict[str, Any], key: str) -> list[float] | None:
        value = anchor.get(key)
        if (
            not isinstance(value, list)
            or len(value) < 3
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value[:4])
        ):
            return None
        color = [float(item) for item in value[:4]]
        if len(color) == 3:
            color.append(1.0)
        return color

    @staticmethod
    def _anchor_param_vector(name: str, anchor: dict[str, Any]) -> list[float] | None:
        param_values = anchor.get("param_values")
        if not isinstance(param_values, dict) or name not in param_values:
            return None
        value = param_values.get(name)
        if (
            not isinstance(value, list)
            or len(value) < 3
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value[:4])
        ):
            return None
        color = [float(item) for item in value[:4]]
        if len(color) == 3:
            color.append(1.0)
        return color

    def _nudge_numeric(self, name: str, value: float, direction: float, *, ratio: float) -> float:
        low, high = self._bounds_for_param(name, value)
        width = max(high - low, 1.0e-9)
        return max(low, min(high, value + float(direction) * float(ratio) * width))

    def _nudge_vector_component(
        self,
        name: str,
        value: list[Any],
        component_index: int,
        direction: float,
        *,
        ratio: float,
    ) -> list[Any]:
        out = list(value)
        current = float(out[component_index])
        low, high = self._bounds_for_vector_component(name, component_index, current)
        width = max(high - low, 1.0e-9)
        out[component_index] = max(low, min(high, current + float(direction) * float(ratio) * width))
        return out

    def _bounds_for_vector_component(self, name: str, component_index: int, value: float) -> tuple[float, float]:
        if self._is_refinable_color_vector(name) and component_index < 3:
            return 0.0, 1.0
        return self._bounds_for_param(name, value)

    def _clamp_param_value(self, name: str, value: float) -> float:
        low, high = self._bounds_for_param(name, value)
        return max(low, min(high, value))

    def _bounds_for_param(self, name: str, value: float) -> tuple[float, float]:
        bounds = effective_bounds_for_param(name)
        if bounds is not None and float(bounds[0]) < float(bounds[1]):
            return float(bounds[0]), float(bounds[1])
        param = self._param_info.get(name)
        if param is not None and param.range_min is not None and param.range_max is not None:
            low = float(param.range_min)
            high = float(param.range_max)
            if low < high:
                return low, high
        lower = name.lower()
        if "hue" in lower:
            return -180.0, 180.0
        if "saturation" in lower:
            return -1.0, 2.0
        if "lightness" in lower or "brightness" in lower:
            return -1.0, 1.0
        if "contrast" in lower:
            return -1.0, 2.0
        if "gamma" in lower:
            return 0.05, 10.0
        if "metallic" in lower:
            return 0.0, 2.0
        if "threshold" in lower or "smooth" in lower:
            return 0.0, 2.0
        if "pow" in lower or "power" in lower:
            return 0.1, 10.0
        if "intensity" in lower or "strength" in lower or "scale" in lower:
            return 0.0, 8.0
        return min(value - 1.0, 0.0), max(value + 1.0, 1.0)

    def _min_normalized_distance(self, candidate: dict[str, Any], references: Sequence[dict[str, Any]]) -> float:
        if not references:
            return math.inf
        return min(self._normalized_distance(candidate, reference) for reference in references)

    def _normalized_distance(self, left: dict[str, Any], right: dict[str, Any]) -> float:
        deltas: list[float] = []
        for name in self._numeric_names:
            left_value = left.get(name)
            right_value = right.get(name)
            if (
                isinstance(left_value, bool)
                or isinstance(right_value, bool)
                or not isinstance(left_value, (int, float))
                or not isinstance(right_value, (int, float))
            ):
                continue
            low, high = self._bounds_for_param(name, float(left_value))
            width = max(high - low, 1.0e-9)
            deltas.append((float(left_value) - float(right_value)) / width)
        for name in self._ordered_refine_vector_names():
            left_value = left.get(name)
            right_value = right.get(name)
            if not isinstance(left_value, list) or not isinstance(right_value, list):
                continue
            for index in range(min(3, len(left_value), len(right_value))):
                left_item = left_value[index]
                right_item = right_value[index]
                if (
                    isinstance(left_item, bool)
                    or isinstance(right_item, bool)
                    or not isinstance(left_item, (int, float))
                    or not isinstance(right_item, (int, float))
                ):
                    continue
                low, high = self._bounds_for_vector_component(name, index, float(left_item))
                width = max(high - low, 1.0e-9)
                deltas.append((float(left_item) - float(right_item)) / width)
        if not deltas:
            return 0.0
        return math.sqrt(sum(delta * delta for delta in deltas) / len(deltas))
