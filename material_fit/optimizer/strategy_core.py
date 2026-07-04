"""Core optimizer strategy interfaces and lightweight implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .adjustment_algorithm import (
    STUCK_NO_IMPROVE_LIMIT,
    AdjustmentState,
    AdjustmentStagePolicy,
    choose_stage,
    propose_next_params,
    update_stage_progress,
)


class OptimizerUnavailableError(RuntimeError):
    """Raised when the requested optimizer's dependencies aren't installed."""


@dataclass
class StrategyContext:
    """Per-iteration context handed to the strategy.

    All fields are read-only from the strategy's perspective — the
    pipeline owns the global ``AdjustmentState`` and only mutates it
    based on the strategy's returned decision.
    """

    iteration: int
    current_params: dict[str, Any]
    analysis: dict[str, Any]
    diff_score: float
    fit_score: float
    state: AdjustmentState


class OptimizerStrategy(ABC):
    """Abstract base for parameter-proposing strategies."""

    name: str = "<unset>"

    @abstractmethod
    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        """Propose the next parameter set.

        Returns ``(next_params, decision)`` where:

        * ``next_params`` is the dict to be written into the candidate
          ``.lmat`` (or applied directly when ``--apply-lmat``).
        * ``decision`` is a JSON-serializable dict recording the
          rationale (which stage / which gen / what changed). The
          pipeline serializes it into ``decision.json`` verbatim under
          a ``decision`` key plus an ``optimizer`` field that this
          base class fills in.
        """

    def stop_reason(self) -> str | None:
        """Optional: return a strategy-emitted termination reason.

        The default implementation returns ``None`` (no opinion). The
        pipeline will still honour ``target_score`` and the global
        no-improve abort. CMA-ES uses this to surface
        ``cmaes.CMA.should_stop()`` once the population has converged.
        """
        return None

    def wants_global_no_improve_check(self) -> bool:
        """Return True if the pipeline's
        :func:`adjustment_algorithm.should_abort_global` rule should be
        applied to this strategy.

        ``HeuristicStrategy`` returns True (default) — its
        determinism means 4 consecutive non-improving moves really
        does mean it is stuck. ``CmaesStrategy`` returns False —
        CMA-ES is a stochastic sampler whose individual proposals
        are *expected* to be worse than the best-so-far, especially
        in the early generations of a 49-dim run. Letting
        ``GLOBAL_NO_IMPROVE_LIMIT=4`` abort it after 5 iterations
        crippled E-007's actual run (see [`Metric_Validation.md` § 5](../docs/Metric_Validation.md)
        for the diagnosis). E-010 routes around this by giving each
        strategy its own decision.
        """
        return True

    def research_summary(self) -> dict[str, Any]:
        """Optional optimizer-specific research diagnostics."""

        return {}


# ---------------------------------------------------------------------
# Heuristic strategy (existing stage-aware path)


class HeuristicStrategy(OptimizerStrategy):
    """Wraps :func:`adjustment_algorithm.propose_next_params` 1:1.

    This is the production strategy that has been driving the auto-adjust
    loop since E-002 ([`ExperimentLog.md`](../docs/ExperimentLog.md))
    fixed the stage-progression bug. It uses ``analysis.material_channels``
    feedback to pick a stage and propose channel-bias corrections
    inside that stage.
    """

    name = "heuristic"

    def __init__(
        self,
        policies: Sequence[AdjustmentStagePolicy],
        shader_params: Sequence[ShaderParam],
        unity_material_params: dict[str, Any] | None,
    ) -> None:
        self._policies = list(policies)
        self._shader_params = list(shader_params)
        self._unity_material_params = unity_material_params or {}

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self._policies:
            return ctx.current_params, {
                "stop_reason": "no_policies",
                "optimizer": self.name,
                "stage": None,
            }
        policy, stage_transition = choose_stage(self._policies, ctx.analysis, ctx.state)
        if policy is None:
            return ctx.current_params, {
                "stop_reason": "no_policies",
                "optimizer": self.name,
                "stage": None,
                "stage_transition": stage_transition,
            }
        next_params, decision = propose_next_params(
            ctx.current_params,
            self._shader_params,
            ctx.analysis,
            policy,
            iteration=ctx.iteration,
            unity_material_params=self._unity_material_params,
        )
        decision["optimizer"] = self.name
        decision["stage_transition"] = stage_transition
        progress = update_stage_progress(ctx.state, policy, ctx.analysis)
        decision["stage_progress"] = progress
        if decision.get("stop_reason") == "no_effective_change":
            # Force stuck-detection so the next call advances stage even
            # when the channel score didn't move (E-002 contract).
            ctx.state.stage_no_improve = max(
                ctx.state.stage_no_improve, STUCK_NO_IMPROVE_LIMIT
            )
        return next_params, decision


# ---------------------------------------------------------------------
# CMA-ES strategy (cold or warm-started)


@dataclass(frozen=True)
class CmaesStrategyConfig:
    """User-tunable knobs surfaced to the UI / fit_config.json.

    ``mode``:
      * ``"cold"``  — vanilla CMA-ES seeded at the project's initial
        ``.lmat`` parameters. No prior history used.
      * ``"warm"``  — Warm-Started CMA-ES (Nomura et al., AAAI 2021).
        The pipeline supplies up to ``warm_start_iters`` (params,
        fit_score) pairs from previous heuristic iterations as the
        prior. Falls back to ``cold`` automatically when the project
        has no prior iterations.

    ``hint_bias_mix_ratio`` (E-010): blend the channel-level
    ``adjustment_hints`` produced by :mod:`vision.diff_analysis`
    into each CMA-ES proposal. ``0.0`` disables the bias and gives
    the legacy behaviour. ``0.30`` is the recommended starting
    point for stylised PBR materials. Values > ~0.5 will dominate
    the CMA-ES exploration and effectively turn the algorithm into
    coordinate descent driven by the hints — useful as a fast
    sanity check, less useful for final convergence.

    The remaining fields map directly to ``CmaesConfig`` and are
    optional; ``None`` means "use library default".
    """

    mode: str = "warm"
    warm_start_iters: int = 12
    warm_start_source: str = "elite_archive_first"
    population_size: int | None = None
    sigma: float | None = None
    seed: int | None = None
    hint_bias_mix_ratio: float = 0.30
    stagnation_patience: int = 0
    stagnation_min_delta: float = 0.001
    stagnation_min_evaluations: int = 0
    stagnation_max_restarts: int = 0
    stagnation_stop_after_restarts: bool = True
    restart_center_mode: str = "best"
    restart_population_multiplier: float = 1.0
    restart_population_schedule: str = "ipop"
    restart_max_population_size: int | None = None
    initial_design_samples: int = 0
    initial_design_method: str = "latin_hypercube"
    initial_design_include_current: bool = True
    initial_design_local_step_ratio: float = 0.05
