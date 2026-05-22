"""Pluggable optimization strategies for ``fit_material._run_auto_adjustment``.

This module isolates *which* algorithm proposes the next parameter set
from *how* the rest of the pipeline (image diff, ``.lmat`` writer,
screenshot capture) drives a single iteration. Without this split,
adding CMA-ES would mean sprinkling ``if optimizer == "..."`` across
the auto-adjust loop, which makes both branches harder to reason about
and makes future optimizers (BO, NSGA-II, ...) require touching
``fit_material.py`` again.

The contract is:

* The pipeline analyses the *current* candidate render and computes
  ``fit_score`` / ``diff_score``.
* It then calls :meth:`OptimizerStrategy.propose` with that signal and
  expects ``(next_params, decision_dict)`` back.
* The strategy is responsible for (a) advancing its own internal state
  (heuristic stage tracking, CMA-ES population/generation) and (b)
  emitting a JSON-friendly ``decision`` dict that records *why* the
  proposed change was made — this is what the UI shows and what
  research-time inspection relies on.

This file imports from both ``adjustment_algorithm`` (heuristic) and
``cma_es_optimizer`` (CMA-ES). The CMA-ES dependency is *lazy*
because ``cmaes`` is not in ``requirements.txt`` for production users
who only want the heuristic path — the strategy raises a clear
:class:`OptimizerUnavailableError` when CMA-ES is requested without
the library installed.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
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
from .acceptance_policy import AcceptancePolicy
from .branch_guard import BranchDriftGuard
from .breakthrough_candidates import BreakthroughCandidateQueue
from .effective_bounds import effective_bounds_for_param
from .search_evidence import InfluenceTracker, ParamInfluenceTracker, TopKArchive, metric_vector_from_analysis
from .semantic_graph import ShaderEffectGraph, graph_from_dict
from .trust_region import TrustRegionBranch


# ---------------------------------------------------------------------
# Strategy interface


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
    population_size: int | None = None
    sigma: float | None = None
    seed: int | None = None
    hint_bias_mix_ratio: float = 0.30


class CmaesStrategy(OptimizerStrategy):
    """Black-box CMA-ES optimizer over the project's parameter dict.

    Per iteration:

    1. If we have a *previous* iteration's fitness, ``tell()`` it back
       so CMA-ES updates its distribution.
    2. ``ask()`` for a new candidate.
    3. Return that candidate as ``next_params`` plus a ``decision``
       dict recording the population/generation index, the warm-start
       state, and which axes changed since ``ctx.current_params``.
    """

    name = "cma_es"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        config: CmaesStrategyConfig,
        warm_start_history: Sequence[tuple[dict[str, Any], float]] = (),
        semantic_graph: ShaderEffectGraph | None = None,
        param_whitelist: Sequence[str] | None = None,
    ) -> None:
        try:
            from .cma_es_optimizer import (  # noqa: WPS433 — lazy import
                CmaesConfig,
                CmaesOptimizer,
                ParameterEncoder,
            )
        except ImportError as exc:
            raise OptimizerUnavailableError(
                "CMA-ES optimizer requires the `cmaes` package. "
                "Install with: pip install cmaes"
            ) from exc

        self._config = config
        cma_config_kwargs: dict[str, Any] = {}
        if config.population_size is not None:
            cma_config_kwargs["population_size"] = int(config.population_size)
        if config.sigma is not None:
            cma_config_kwargs["sigma"] = float(config.sigma)
        if config.seed is not None:
            cma_config_kwargs["seed"] = int(config.seed)

        self._encoder = ParameterEncoder(
            initial_params,
            list(shader_params),
            param_whitelist=param_whitelist,
            semantics=semantic_graph,
        )
        if self._encoder.dim == 0:
            raise OptimizerUnavailableError(
                "CMA-ES has no trainable axes for this material — every "
                "parameter is either a texture binding, a tiling vector, "
                "or blacklisted. Switch to the heuristic optimizer."
            )

        warm_samples: list[tuple[dict[str, Any], float]] = []
        if config.mode == "warm" and warm_start_history:
            warm_samples = list(warm_start_history[: max(int(config.warm_start_iters), 0)])
        # WS-CMA-ES requires ≥2 samples to estimate covariance; fall
        # back to cold gracefully when we don't have enough.
        if len(warm_samples) < 2:
            warm_samples = []

        self._opt = CmaesOptimizer(
            self._encoder,
            config=CmaesConfig(**cma_config_kwargs),
            warm_start_samples=warm_samples or None,
            initial_mean=initial_params,
        )
        self._warm_started = self._opt.warm_started
        self._history_size_used = len(warm_samples)

        # CMA-ES runs in ask/tell pairs. We hold the *currently asked*
        # parameter set + the fitness from the *previous* completed
        # iteration so we can chain them on the next propose() call.
        self._pending_params: dict[str, Any] | None = None
        self._last_observed_fitness: float | None = None
        # Sample a first proposal eagerly so the caller doesn't have to
        # special-case "iter 0 has no previous fitness".
        self._asked_first = False

    @property
    def warm_started(self) -> bool:
        return self._warm_started

    @property
    def population_size(self) -> int:
        return self._opt.population_size

    @property
    def trainable_dim(self) -> int:
        return self._encoder.dim

    def stop_reason(self) -> str | None:
        if self._opt.should_stop():
            return "cmaes_should_stop"
        return None

    def wants_global_no_improve_check(self) -> bool:
        # E-010: CMA-ES is stochastic. A 4-consecutive-not-better
        # window is not evidence the run is stuck; it is the
        # *expected* behaviour for the first few generations.
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        import numpy as np  # local import — already a hard dep, but keep CMA-ES branch lazy

        # 1. Tell back the previous iteration's fitness, if we have a
        #    pending ask waiting for a response. CMA-ES is minimization,
        #    so loss = 1 - fit_score (clipped) translates "higher score
        #    is better" into the right direction.
        if self._pending_params is not None:
            loss = self._fit_score_to_loss(ctx.fit_score, ctx.diff_score)
            self._opt.tell(loss)
            self._last_observed_fitness = loss

        # 2. Build the optional E-010 hint-bias callback.
        hint_payload = self._build_hint_bias_payload(ctx.analysis)
        bias_callback = hint_payload["callback"]

        # 3. Ask for the next candidate (with bias if enabled).
        proposed = self._opt.ask(bias_callback=bias_callback)
        self._pending_params = proposed
        self._asked_first = True

        # 4. Compute changes (for transparency in decision.json).
        changes = self._diff_params(ctx.current_params, proposed)

        decision: dict[str, Any] = {
            "optimizer": self.name,
            "mode": self._config.mode,
            "stage": {"name": f"cma_{self._config.mode}", "description": "Black-box CMA-ES proposal"},
            "iteration_gain": None,
            "score": ctx.diff_score,
            "changes": changes,
            "stop_reason": self.stop_reason() or ("continue" if changes else "no_effective_change"),
            "cma_es": {
                "warm_started": self._warm_started,
                "warm_start_iters_used": self._history_size_used,
                "population_size": self.population_size,
                "trainable_dim": self.trainable_dim,
                "evaluations": self._opt.evaluations,
                "best_fitness": self._opt.best[1] if self._opt.evaluations > 0 else None,
                "last_loss_fed": self._last_observed_fitness,
                "hint_bias": {
                    "mix_ratio": self._config.hint_bias_mix_ratio,
                    "applied": hint_payload["applied"],
                    "n_axes_biased": hint_payload["n_axes_biased"],
                    "max_abs_delta": hint_payload["max_abs_delta"],
                    "channels_used": hint_payload["channels_used"],
                },
            },
        }
        return proposed, decision

    # -----------------------------------------------------------------
    # E-010 hint-bias machinery

    _SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.25}

    def _build_hint_bias_payload(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Compute (and stash diagnostics about) the per-axis hint bias.

        Returns a dict with:

        * ``callback`` — the function to pass to ``CmaesOptimizer.ask()``
          (or ``None`` when no bias is applicable).
        * ``applied`` — True when ``callback`` is non-None.
        * ``n_axes_biased`` — count of axes with non-zero delta.
        * ``max_abs_delta`` — worst-case delta magnitude (in original
          coordinate units), useful when debugging a runaway bias.
        * ``channels_used`` — list of channel names that contributed.

        The callback is built so it always clamps to the encoder's
        bounds — feeding CMA-ES out-of-range vectors will distort
        its covariance estimate and is never desired.
        """

        import numpy as np

        mix_ratio = float(self._config.hint_bias_mix_ratio)
        if mix_ratio <= 0.0:
            return {
                "callback": None,
                "applied": False,
                "n_axes_biased": 0,
                "max_abs_delta": 0.0,
                "channels_used": [],
            }

        hints = analysis.get("adjustment_hints") if isinstance(analysis, dict) else None
        if not isinstance(hints, list) or not hints:
            return {
                "callback": None,
                "applied": False,
                "n_axes_biased": 0,
                "max_abs_delta": 0.0,
                "channels_used": [],
            }

        bias_vec, channels_used = self._compute_hint_vector(hints, mix_ratio)
        n_axes_biased = int(np.count_nonzero(bias_vec))
        max_abs = float(np.max(np.abs(bias_vec))) if bias_vec.size else 0.0
        if n_axes_biased == 0:
            return {
                "callback": None,
                "applied": False,
                "n_axes_biased": 0,
                "max_abs_delta": 0.0,
                "channels_used": [],
            }

        lower = self._encoder.lower_bounds
        upper = self._encoder.upper_bounds

        def _bias_callback(vec_orig: "np.ndarray") -> "np.ndarray":
            biased = vec_orig + bias_vec
            return np.clip(biased, lower, upper)

        return {
            "callback": _bias_callback,
            "applied": True,
            "n_axes_biased": n_axes_biased,
            "max_abs_delta": max_abs,
            "channels_used": channels_used,
        }

    def _compute_hint_vector(
        self,
        hints: list[dict[str, Any]],
        mix_ratio: float,
    ) -> tuple["np.ndarray", list[str]]:
        """Translate channel-level hints into a per-axis delta vector.

        Algorithm (E-010, see ``ExperimentLog.md`` E-010 entry):

        1. For each axis, look up its parameter name and find every
           hint whose ``related_params`` contains that name (with
           wildcard ``*`` support — e.g. ``u_MetallicRemap*`` matches
           ``u_MetallicRemapMin/Max``).
        2. Each contributing hint signs its severity weight by its
           ``direction`` (+1 = increase, -1 = decrease, 0 = inspect).
        3. The total signed weight is multiplied by the axis's range
           and 5% of one mix step:

               delta_axis = signed_weight * 0.05 * (high - low) * mix_ratio

           5% is the same scale as our heuristic's ``iteration_gain``
           default, chosen so the bias is always smaller than CMA-ES's
           own per-step exploration sigma (~0.3 of normalised range)
           and therefore cannot dominate the search.

        Returns ``(delta_vector, contributing_channels)``.
        """

        import numpy as np

        axes = self._encoder.axes
        deltas = np.zeros(len(axes), dtype=np.float64)
        channels_used: set[str] = set()

        # Pre-build a list of (severity_weight, signed_direction,
        # related_params_lower) for fast iteration.
        compiled: list[tuple[float, float, list[str], str]] = []
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            severity = self._SEVERITY_WEIGHT.get(str(hint.get("severity") or "").lower(), 0.0)
            if severity <= 0.0:
                continue
            direction = str(hint.get("direction") or "").lower()
            if direction == "increase":
                sign = +1.0
            elif direction == "decrease":
                sign = -1.0
            else:
                continue
            params = hint.get("related_params") or []
            if not isinstance(params, list):
                continue
            params_lower = [str(p).lower() for p in params if isinstance(p, str)]
            channel_name = str(hint.get("channel") or "")
            compiled.append((severity, sign, params_lower, channel_name))

        if not compiled:
            return deltas, []

        for i, axis in enumerate(axes):
            axis_name = axis.param_name.lower()
            axis_range = float(axis.high - axis.low)
            if axis_range <= 0:
                continue
            signed_weight = 0.0
            local_channels: list[str] = []
            for severity, sign, params_lower, channel in compiled:
                if any(self._param_match(axis_name, p) for p in params_lower):
                    signed_weight += severity * sign
                    local_channels.append(channel)
            if signed_weight == 0.0:
                continue
            deltas[i] = signed_weight * 0.05 * axis_range * mix_ratio
            channels_used.update(local_channels)

        return deltas, sorted(channels_used)

    @staticmethod
    def _param_match(axis_name: str, hint_pattern: str) -> bool:
        """Match a hint's ``related_params`` entry against an encoder axis name.

        Supports trailing ``*`` wildcards (e.g. ``u_MetallicRemap*``)
        and falls back to exact equality otherwise.
        """

        if not hint_pattern:
            return False
        if hint_pattern.endswith("*"):
            return axis_name.startswith(hint_pattern[:-1])
        return axis_name == hint_pattern

    # -----------------------------------------------------------------
    # helpers

    @staticmethod
    def _fit_score_to_loss(fit_score: float, diff_score: float) -> float:
        """Map the higher-is-better fit_score (or RGB MAE fallback) into
        a CMA-ES minimization loss in [0, ~1]."""
        if math.isfinite(fit_score):
            return max(0.0, 1.0 - float(fit_score))
        if math.isfinite(diff_score):
            return max(0.0, float(diff_score))
        # No usable signal — feed a neutral 0.5 so CMA-ES doesn't
        # collapse to the worst sample of the generation.
        return 0.5

    @staticmethod
    def _diff_params(
        old: dict[str, Any],
        new: dict[str, Any],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, value in new.items():
            old_value = old.get(name)
            if isinstance(value, list) and isinstance(old_value, list) and len(value) == len(old_value):
                if any(
                    not _isclose(_to_number(a), _to_number(b))
                    for a, b in zip(old_value, value)
                ):
                    out.append({
                        "param": name,
                        "old": old_value,
                        "new": value,
                        "reason": "CMA-ES sample",
                    })
            elif isinstance(value, (int, float)) and isinstance(old_value, (int, float)):
                if not _isclose(float(value), float(old_value)):
                    out.append({
                        "param": name,
                        "old": old_value,
                        "new": value,
                        "reason": "CMA-ES sample",
                    })
        return out


# ---------------------------------------------------------------------
# Semantic group strategy


class SemanticCandidateGenerator:
    """Generate semantic-group candidates without owning scheduling state."""

    def __init__(
        self,
        *,
        graph: ShaderEffectGraph,
        shader_params: Sequence[ShaderParam],
        encoder_cls: Any,
        step_schedule: Sequence[float],
    ) -> None:
        self._graph = graph
        self._shader_params = list(shader_params)
        self._encoder_cls = encoder_cls
        self._step_schedule = list(step_schedule)

    def candidate_group_params(self, group: Any) -> list[str]:
        if group.search_params:
            return list(group.search_params)
        if not group.current_active and group.gate_params:
            return list(group.gate_params)
        return list(group.params)

    def searchable_params_for_group(self, group: Any, params: dict[str, Any]) -> list[str]:
        return [
            name
            for name in self.candidate_group_params(group)
            if name in params
            and self._graph.params.get(name) is not None
            and self._graph.params[name].searchable
        ]

    def probe_candidate(self, base_params: dict[str, Any], group: Any) -> tuple[dict[str, Any], list[str]]:
        candidate = dict(base_params)
        probe_order = list(group.gate_params) + list(group.search_params) + list(group.params)
        seen: set[str] = set()
        changed: list[str] = []
        for name in probe_order:
            if name in seen or name not in candidate:
                continue
            seen.add(name)
            sem = self._graph.params.get(name)
            if sem is None or not sem.searchable:
                continue
            before = candidate.get(name)
            candidate[name] = self._probe_value(name, before, sem)
            if candidate.get(name) != before:
                changed.append(name)
                break
        return candidate, changed

    def pattern_candidate(
        self,
        *,
        base_params: dict[str, Any],
        group: Any,
        state: dict[str, Any],
        analysis: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        whitelist = self.searchable_params_for_group(group, base_params)
        if not whitelist:
            state["status"] = "exhausted"
            return dict(base_params), {}
        combo_candidate = self._base_color_combo_candidate(
            base_params=base_params,
            group=group,
            state=state,
            analysis=analysis,
            iteration=iteration,
        )
        if combo_candidate is not None:
            return combo_candidate
        encoder = self._encoder_cls(
            base_params,
            self._shader_params,
            param_whitelist=whitelist,
            semantics=self._graph,
        )
        if encoder.dim == 0:
            state["status"] = "exhausted"
            return dict(base_params), {}
        joint_candidate = self._joint_group_candidate(
            base_params=base_params,
            group=group,
            state=state,
            analysis=analysis,
            iteration=iteration,
            encoder=encoder,
        )
        if joint_candidate is not None:
            return joint_candidate
        return self._single_axis_candidate(
            base_params=base_params,
            state=state,
            analysis=analysis,
            iteration=iteration,
            encoder=encoder,
        )

    def cross_group_candidate(
        self,
        *,
        base_params: dict[str, Any],
        groups: Sequence[Any],
        group_cycle: int,
        analysis: dict[str, Any],
        base_fit_score: float,
        iteration: int,
        step_scale: float = 0.35,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        candidate = dict(base_params)
        changed_params: list[str] = []
        axes_payload: list[dict[str, Any]] = []
        for group in groups:
            updated, payload = self._nudge_first_axis_for_group(
                base_params=candidate,
                group=group,
                analysis=analysis,
                step_scale=step_scale,
                group_cycle=group_cycle,
            )
            if updated is None:
                continue
            candidate = updated
            changed_params.extend(str(item) for item in payload.get("changed_params", []) if isinstance(item, str))
            axes_payload.append(payload)
        if len(set(changed_params)) < 2 or not CmaesStrategy._diff_params(base_params, candidate):
            return None
        return candidate, {
            "cross_groups": [str(group.name) for group in groups],
            "changed_params": sorted(set(changed_params)),
            "axes": axes_payload,
            "base_fit_score": base_fit_score,
            "iteration": iteration,
        }

    def nudge_group_candidate(
        self,
        *,
        base_params: dict[str, Any],
        group: Any,
        analysis: dict[str, Any],
        step_scale: float,
        group_cycle: int,
        axis_offset: int = 0,
        direction_override: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        updated, payload = self._nudge_first_axis_for_group(
            base_params=base_params,
            group=group,
            analysis=analysis,
            step_scale=step_scale,
            group_cycle=group_cycle,
            axis_offset=axis_offset,
            direction_override=direction_override,
        )
        if updated is None:
            return None
        return updated, payload

    def nudge_param_candidate(
        self,
        *,
        base_params: dict[str, Any],
        param_name: str,
        step_scale: float,
        group_cycle: int,
        axis_offset: int = 0,
        direction_override: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if param_name not in base_params:
            return None
        sem = self._graph.params.get(param_name)
        if sem is None or not sem.searchable:
            return None
        encoder = self._encoder_cls(
            base_params,
            self._shader_params,
            param_whitelist=[param_name],
            semantics=self._graph,
        )
        if encoder.dim == 0:
            return None
        vec = encoder.encode(base_params)
        axis_index = max(0, min(int(axis_offset), encoder.dim - 1))
        axis = encoder.axes[axis_index]
        direction = direction_override if direction_override is not None else 1.0
        step_ratio = self._step_schedule[min(group_cycle, len(self._step_schedule) - 1)] * step_scale
        width = max(float(axis.high) - float(axis.low), 1e-9)
        vec[axis_index] = max(
            encoder.lower_bounds[axis_index],
            min(encoder.upper_bounds[axis_index], vec[axis_index] + direction * step_ratio * width),
        )
        proposed = encoder.decode(vec)
        changes = CmaesStrategy._diff_params(base_params, proposed)
        if not changes:
            return None
        return proposed, {
            "param": param_name,
            "axis_index": axis_index,
            "axis_param": axis.param_name,
            "direction": direction,
            "step_ratio": step_ratio,
            "changed_params": [str(change.get("param")) for change in changes if isinstance(change, dict)],
        }

    def _single_axis_candidate(
        self,
        *,
        base_params: dict[str, Any],
        state: dict[str, Any],
        analysis: dict[str, Any],
        iteration: int,
        encoder: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        vec = encoder.encode(base_params)
        axis_index = int(state.get("axis_cursor", 0)) % encoder.dim
        axis = encoder.axes[axis_index]
        hinted = self._hint_direction(analysis, axis.param_name)
        direction = hinted or float(state.get("direction", 1.0) or 1.0)
        step_index = min(int(state.get("step_index", 0)), len(self._step_schedule) - 1)
        step_ratio = self._step_schedule[step_index]
        width = max(float(axis.high) - float(axis.low), 1e-9)
        vec[axis_index] = max(
            encoder.lower_bounds[axis_index],
            min(encoder.upper_bounds[axis_index], vec[axis_index] + direction * step_ratio * width),
        )
        proposed = encoder.decode(vec)
        state["last_axis"] = axis.param_name
        state["last_direction"] = direction
        return proposed, {
            "axis_index": axis_index,
            "param": axis.param_name,
            "sub_index": axis.sub_index,
            "transform": axis.transform,
            "direction": direction,
            "hint_direction": hinted,
            "step_ratio": step_ratio,
            "step_index": step_index,
            "iteration": iteration,
        }

    def _joint_group_candidate(
        self,
        *,
        base_params: dict[str, Any],
        group: Any,
        state: dict[str, Any],
        analysis: dict[str, Any],
        iteration: int,
        encoder: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if encoder.dim < 2:
            return None
        joint_index = int(state.get("joint_cursor", 0))
        variants = ("hinted_positive", "hinted_negative")
        if joint_index >= len(variants):
            return None
        variant = variants[joint_index]
        vec = encoder.encode(base_params)
        step_index = min(int(state.get("step_index", 0)), len(self._step_schedule) - 1)
        step_ratio = self._step_schedule[step_index] * 0.55
        touched_axes: list[int] = []
        touched_params: list[str] = []
        for axis_index, axis in enumerate(encoder.axes):
            if axis.param_name not in touched_params:
                if len(touched_params) >= 3:
                    continue
                touched_params.append(axis.param_name)
            if len(touched_axes) >= 6:
                break
            hinted = self._hint_direction(analysis, axis.param_name)
            fallback = 1.0 if variant == "hinted_positive" else -1.0
            direction = hinted or fallback
            width = max(float(axis.high) - float(axis.low), 1e-9)
            vec[axis_index] = max(
                encoder.lower_bounds[axis_index],
                min(encoder.upper_bounds[axis_index], vec[axis_index] + direction * step_ratio * width),
            )
            touched_axes.append(axis_index)
        if len(touched_axes) < 2:
            return None
        proposed = encoder.decode(vec)
        changes = CmaesStrategy._diff_params(base_params, proposed)
        if not changes:
            state["joint_cursor"] = joint_index + 1
            return None
        changed_params = [str(change.get("param")) for change in changes if isinstance(change, dict)]
        state["last_axis"] = f"joint:{variant}"
        state["last_direction"] = 0.0
        return proposed, {
            "joint": True,
            "joint_index": joint_index,
            "joint_name": variant,
            "param": "joint:" + ",".join(changed_params),
            "changed_params": changed_params,
            "axis_indices": touched_axes,
            "step_ratio": step_ratio,
            "step_index": step_index,
            "iteration": iteration,
        }

    def _base_color_combo_candidate(
        self,
        *,
        base_params: dict[str, Any],
        group: Any,
        state: dict[str, Any],
        analysis: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if group.name != "base_color":
            return None
        base_name = next((name for name in group.search_params if name in base_params and "basecolor" in name.lower()), "")
        gamma_name = next((name for name in group.search_params if name in base_params and "gamma" in name.lower()), "")
        if not base_name or not isinstance(base_params.get(base_name), list):
            return None
        channels = analysis.get("material_channels") if isinstance(analysis, dict) else None
        channel = channels.get("base_color_main_texture", {}) if isinstance(channels, dict) else {}
        rgb_bias = channel.get("rgb_bias_candidate_minus_reference") if isinstance(channel, dict) else None
        if not isinstance(rgb_bias, list) or len(rgb_bias) < 3:
            rgb_bias = [0.0, 0.0, 0.0]
        rgb_bias = [float(v) if isinstance(v, (int, float)) and math.isfinite(float(v)) else 0.0 for v in rgb_bias[:3]]
        luma_bias = channel.get("luma_bias_candidate_minus_reference") if isinstance(channel, dict) else 0.0
        luma_bias = float(luma_bias) if isinstance(luma_bias, (int, float)) and math.isfinite(float(luma_bias)) else 0.0
        combos = [
            ("inverse_rgb_bias", 0.55, 1.0, "bias"),
            ("strong_inverse_rgb_bias", 0.90, 1.0, "bias"),
            ("darken_desaturate", 0.0, 0.78, "desaturate"),
            ("cool_shadow", 0.0, 1.0, "scale:0.65,0.75,0.95"),
            ("purple_shadow", 0.0, 1.0, "scale:0.65,0.55,0.90"),
            ("reduce_red_lift_blue", 0.0, 1.0, "offset:-0.20,-0.10,+0.10"),
        ]
        combo_index = int(state.get("combo_cursor", 0))
        if combo_index >= len(combos):
            return None
        combo_name, bias_gain, value_scale, mode = combos[combo_index]
        current = list(base_params.get(base_name) or [])
        if len(current) < 3:
            return None
        rgb = self._combo_rgb(current, rgb_bias, bias_gain, value_scale, mode)
        proposed = dict(base_params)
        new_color = list(current)
        for i in range(3):
            new_color[i] = rgb[i]
        proposed[base_name] = new_color
        changed = [base_name]
        if gamma_name and isinstance(base_params.get(gamma_name), (int, float)):
            gamma = self._combo_gamma(float(base_params[gamma_name]), luma_bias, combo_name)
            if abs(gamma - float(base_params[gamma_name])) > 1e-8:
                proposed[gamma_name] = gamma
                changed.append(gamma_name)
        if not CmaesStrategy._diff_params(base_params, proposed):
            state["combo_cursor"] = combo_index + 1
            return self._base_color_combo_candidate(
                base_params=base_params,
                group=group,
                state=state,
                analysis=analysis,
                iteration=iteration,
            )
        state["last_axis"] = f"combo:{combo_name}"
        state["last_direction"] = 0.0
        return proposed, {
            "combo": True,
            "combo_index": combo_index,
            "combo_name": combo_name,
            "param": base_name,
            "changed_params": changed,
            "rgb_bias_candidate_minus_reference": rgb_bias,
            "luma_bias_candidate_minus_reference": luma_bias,
            "step_ratio": self._step_schedule[min(int(state.get("step_index", 0)), len(self._step_schedule) - 1)],
            "iteration": iteration,
        }

    def _nudge_first_axis_for_group(
        self,
        *,
        base_params: dict[str, Any],
        group: Any,
        analysis: dict[str, Any],
        step_scale: float,
        group_cycle: int,
        axis_offset: int = 0,
        direction_override: float | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        whitelist = self.searchable_params_for_group(group, base_params)
        if not whitelist:
            return None, {}
        encoder = self._encoder_cls(
            base_params,
            self._shader_params,
            param_whitelist=whitelist,
            semantics=self._graph,
        )
        if encoder.dim == 0:
            return None, {}
        vec = encoder.encode(base_params)
        axis_index = max(0, min(int(axis_offset), encoder.dim - 1))
        axis = encoder.axes[axis_index]
        direction = direction_override if direction_override is not None else (self._hint_direction(analysis, axis.param_name) or 1.0)
        step_ratio = self._step_schedule[min(group_cycle, len(self._step_schedule) - 1)] * step_scale
        width = max(float(axis.high) - float(axis.low), 1e-9)
        vec[axis_index] = max(
            encoder.lower_bounds[axis_index],
            min(encoder.upper_bounds[axis_index], vec[axis_index] + direction * step_ratio * width),
        )
        proposed = encoder.decode(vec)
        changes = CmaesStrategy._diff_params(base_params, proposed)
        if not changes:
            return None, {}
        return proposed, {
            "group": group.name,
            "axis_index": axis_index,
            "param": axis.param_name,
            "direction": direction,
            "step_ratio": step_ratio,
            "changed_params": [str(change.get("param")) for change in changes if isinstance(change, dict)],
        }

    def _probe_value(self, name: str, value: Any, sem: Any) -> Any:
        if isinstance(value, bool):
            return True
        if isinstance(value, (int, float)):
            low, high = self._bounds_for_value(name, float(value), sem)
            if float(value) <= low + 1e-8:
                return max(min(low + (high - low) * 0.35, high), low)
            step = max((high - low) * 0.18, 1e-4)
            return max(low, min(high, float(value) + step))
        if isinstance(value, list) and value and all(isinstance(item, (int, float)) for item in value):
            out = list(value)
            for idx in range(min(3, len(out))):
                out[idx] = max(0.0, min(1.0, float(out[idx]) + 0.18))
            return out
        return value

    def _bounds_for_value(self, name: str, value: float, sem: Any) -> tuple[float, float]:
        lower = name.lower()
        if (bounds := effective_bounds_for_param(name)) is not None:
            return bounds
        low = sem.range_min if getattr(sem, "range_min", None) is not None else None
        high = sem.range_max if getattr(sem, "range_max", None) is not None else None
        if low is not None and high is not None and float(low) < float(high):
            return float(low), float(high)
        if any(token in lower for token in ("intensity", "strength", "scale")):
            return 0.0, 8.0
        if any(token in lower for token in ("threshold", "smooth", "metallic", "occlusion")):
            return 0.0, 1.0
        if "pow" in lower or "power" in lower:
            return 0.0, 10.0
        if "gamma" in lower:
            return 0.05, 10.0
        return min(value - 1.0, 0.0), max(value + 1.0, 1.0)

    @classmethod
    def _combo_rgb(cls, current: list[Any], rgb_bias: list[float], bias_gain: float, value_scale: float, mode: str) -> list[float]:
        rgb = [cls._clamp01(float(current[i])) for i in range(3)]
        if mode == "bias":
            return [cls._clamp01(rgb[i] - bias_gain * rgb_bias[i]) for i in range(3)]
        if mode == "desaturate":
            mean = sum(rgb) / 3.0
            return [cls._clamp01((mean + (rgb[i] - mean) * 0.65) * value_scale) for i in range(3)]
        if mode.startswith("scale:"):
            scales = [float(item) for item in mode.split(":", 1)[1].split(",")]
            return [cls._clamp01(rgb[i] * scales[i]) for i in range(3)]
        if mode.startswith("offset:"):
            offsets = [float(item) for item in mode.split(":", 1)[1].split(",")]
            return [cls._clamp01(rgb[i] + offsets[i]) for i in range(3)]
        return rgb

    @staticmethod
    def _combo_gamma(gamma: float, luma_bias: float, combo_name: str) -> float:
        if luma_bias > 0.02:
            gamma *= 0.65
        elif luma_bias < -0.02:
            gamma *= 1.25
        if combo_name in {"darken_desaturate", "cool_shadow", "purple_shadow"}:
            gamma *= 0.80
        return max(0.05, min(10.0, gamma))

    @staticmethod
    def _hint_direction(analysis: dict[str, Any], param_name: str) -> float:
        hints = analysis.get("adjustment_hints") if isinstance(analysis, dict) else None
        if not isinstance(hints, list):
            return 0.0
        total = 0.0
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            related = hint.get("related_params")
            if not isinstance(related, list):
                continue
            if not any(CmaesStrategy._param_match(param_name.lower(), str(item).lower()) for item in related):
                continue
            direction = str(hint.get("direction", "")).lower()
            if direction == "increase":
                total += 1.0
            elif direction == "decrease":
                total -= 1.0
        if total > 0.0:
            return 1.0
        if total < 0.0:
            return -1.0
        return 0.0

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class SemanticGroupStrategy(OptimizerStrategy):
    """Low-dimensional group search driven by :class:`ShaderEffectGraph`."""

    name = "semantic_group"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        graph: ShaderEffectGraph,
        auto_adjust_mode: str = "fresh_fit",
    ) -> None:
        from .cma_es_optimizer import ParameterEncoder

        self._graph = graph
        self._shader_params = list(shader_params)
        # Honor the human-curated order from the run console preset
        # first; fall back to suggested_by_unity / search_priority for
        # groups that don't carry an explicit order. This way the UI
        # panel order is what the optimizer walks through.
        groups_with_order = [
            (int(getattr(group, "order", 0) or 0), idx, group)
            for idx, group in enumerate(graph.groups.values())
        ]
        groups_with_order.sort(
            key=lambda item: (
                self._group_order_key(item[2]),
                not item[2].suggested_by_unity,
                -float(item[2].search_priority or 0.0),
                item[1],
            )
        )
        self._step_schedule = [0.25, 0.14, 0.075, 0.040]
        self._group_order: list[str] = []
        self._candidate_generator = SemanticCandidateGenerator(
            graph=graph,
            shader_params=shader_params,
            encoder_cls=ParameterEncoder,
            step_schedule=self._step_schedule,
        )
        for _, _, group in groups_with_order:
            candidate_params = self._candidate_generator.candidate_group_params(group)
            if any(graph.params.get(p) and graph.params[p].searchable for p in candidate_params):
                self._group_order.append(group.name)
        if not self._group_order:
            self._group_order = [group.name for group in graph.groups.values()]
        self._encoder_cls = ParameterEncoder
        self._initial_params = dict(initial_params)
        # Phase-summary 2026-05-08 follow-up: the first post-P0 run
        # (job 22:05:24) showed that ±18% single-axis perturbation
        # only nudges the perceptual fit_score by ~±1e-4 ~ ±7e-4,
        # which never cleared the old 0.5%-of-fit threshold. Bumping
        # the cold-start step to 0.25 produces visibly larger pixel
        # changes (typical ΔMAE ~5e-3 → Δfit ~2e-3) so the algorithm
        # can actually accept candidates instead of rolling back 30
        # iterations in a row.
        # Same root cause: the relative threshold of 0.5% × fit was
        # too strict for the actual signal magnitude. We tighten the
        # absolute floor (5e-5 ≈ noise of two consecutive identical
        # screenshots) and lower the relative floor to 0.1% so a
        # genuine pixel-level improvement is not classified as noise.
        self._min_improvement_abs = 5.0e-5
        self._min_improvement_rel = 0.001  # 0.1% of base fit
        self._probe_score_delta_abs = 2.5e-5
        self._probe_score_delta_rel = 0.0005
        # When a group only exposes one or two searchable axes, allow
        # very few rejected probes before declaring it exhausted —
        # otherwise the very first FishStandard run wastes 7+ iterations
        # bouncing on u_BaseColor before fresnel ever gets a turn.
        self._max_group_no_improve = 8
        self._max_group_no_improve_small = 3
        self._max_group_cycles = 999
        self._breakthrough_cycle = 3
        self._group_cycle = 0
        self._group_order_revision = 0
        self._group_state: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, Any] | None = None
        self._influence = InfluenceTracker()
        self._param_influence = ParamInfluenceTracker()
        self._topk = TopKArchive(capacity=16)
        self._acceptance_policy = AcceptancePolicy()
        self._branch_guard = BranchDriftGuard()
        self._breakthrough_queue = BreakthroughCandidateQueue(max_size=10)
        self._auto_adjust_mode = (auto_adjust_mode or "fresh_fit").strip().lower()
        self._isolation_done = False
        self._cross_group_cycles_done: set[int] = set()
        self._best_fit_history: list[tuple[int, float]] = []
        self._force_breakthrough = False
        self._plateau_window = 18
        self._plateau_min_gain = 0.002
        self._early_breakthrough_iteration = 36
        self._plateau_min_exhausted_ratio = 0.55
        self._param_candidate_pool_size = 10
        self._trust_region = TrustRegionBranch()
        self._current_iteration = 0
        self._breakthrough_window_start: int | None = None
        self._breakthrough_window_best = -math.inf
        self._breakthrough_window_no_improve = 0
        self._breakthrough_window_max_iters = 30
        self._breakthrough_window_max_no_improve = 16
        self._breakthrough_cooldown_until = -1
        self._breakthrough_cooldown_iters = 24

    def wants_global_no_improve_check(self) -> bool:
        # This strategy owns accept/reject and per-group exhaustion. The
        # legacy global abort is too aggressive for deliberate probes,
        # where a visible-but-worse candidate is still useful evidence.
        return False

    def research_summary(self) -> dict[str, Any]:
        bottleneck: dict[str, float] = {}
        if self._topk.items:
            latest_components = self._topk.items[0].get("components")
            if isinstance(latest_components, dict):
                bottleneck = {
                    str(key): float(value)
                    for key, value in sorted(
                        latest_components.items(),
                        key=lambda item: float(item[1]) if isinstance(item[1], (int, float)) else 0.0,
                        reverse=True,
                    )[:4]
                    if isinstance(value, (int, float))
                }
        return {
            "phase": self._scheduler_phase(),
            "cycle": self._group_cycle,
            "breakthrough_cycle": self._breakthrough_cycle,
            "topk": self._topk.summary(limit=8),
            "influence": self._influence.summary(bottleneck),
            "influence_trial_count": self._influence.trial_count,
            "param_priority": self._param_ranking({}, {"research_metrics": {"components": bottleneck}}, limit=None),
            "param_candidate_pool_size": self._param_candidate_pool_size,
            "breakthrough_queue": self._breakthrough_queue.summary(),
            "trust_region": self._trust_region.summary(),
            "branch_guard": self._branch_guard.summary(),
            "acceptance_policy": self._acceptance_policy.summary(),
            "group_order": list(self._group_order),
        }

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._current_iteration = int(ctx.iteration)
        if not self._group_order:
            return ctx.current_params, {
                "optimizer": self.name,
                "stop_reason": "no_semantic_groups",
                "stage": None,
            }
        previous_eval = self._consume_pending(ctx)
        self._update_plateau_state(ctx)
        if not previous_eval:
            self._record_topk(ctx, group=None)
        base_params = previous_eval.get("next_base_params")
        if not isinstance(base_params, dict):
            base_params = dict(ctx.current_params)

        isolation = self._isolation_candidate(base_params)
        if isolation is not None:
            proposed, changed = isolation
            self._pending = {
                "group": "__isolate_base__",
                "kind": "isolation",
                "base_params": dict(base_params),
                "base_fit_score": float(ctx.fit_score),
                "base_metrics": metric_vector_from_analysis(ctx.analysis, ctx.fit_score),
                "changed_params": changed,
                "force_accept": True,
            }
            self._isolation_done = True
            return proposed, {
                "optimizer": self.name,
                "stage": {
                    "name": "isolate_base",
                    "description": (
                        "actively suppress specular/reflection/matcap/"
                        "emission/fresnel before tuning base color"
                    ),
                },
                "semantic_action": "isolate_base_color",
                "changes": CmaesStrategy._diff_params(base_params, proposed),
                "stop_reason": "continue",
                "previous_candidate": previous_eval or None,
                "isolation_forced_accept": True,
            }

        breakthrough = self._breakthrough_candidate(
            base_params=base_params,
            base_fit_score=ctx.fit_score,
            analysis=ctx.analysis,
            iteration=ctx.iteration,
        )
        if breakthrough is not None:
            proposed, payload = breakthrough
            changes = CmaesStrategy._diff_params(base_params, proposed)
            self._pending = {
                "group": "__breakthrough__",
                "kind": str(payload.get("candidate_kind") or "breakthrough"),
                "base_params": dict(base_params),
                "base_fit_score": float(ctx.fit_score),
                "base_metrics": metric_vector_from_analysis(ctx.analysis, ctx.fit_score),
                "changed_params": [str(change.get("param")) for change in changes if isinstance(change, dict)],
                "breakthrough": payload,
            }
            return proposed, {
                "optimizer": self.name,
                "stage": {"name": "breakthrough", "description": "archive/influence driven breakthrough candidate"},
                "semantic_action": "breakthrough_candidate",
                "scheduler": self._scheduler_state("breakthrough", ctx.analysis, base_params=base_params),
                "changes": changes,
                "stop_reason": "continue",
                "previous_candidate": previous_eval or None,
                **payload,
            }

        cross_group = self._cross_group_candidate(
            base_params=base_params,
            base_fit_score=ctx.fit_score,
            analysis=ctx.analysis,
            iteration=ctx.iteration,
        )
        if cross_group is not None:
            proposed, payload = cross_group
            self._pending = {
                "group": "__cross_group__",
                "kind": "cross_group",
                "base_params": dict(base_params),
                "base_fit_score": float(ctx.fit_score),
                "base_metrics": metric_vector_from_analysis(ctx.analysis, ctx.fit_score),
                "changed_params": payload["changed_params"],
            }
            return proposed, {
                "optimizer": self.name,
                "stage": {"name": "cross_group", "description": "combine best semantic groups from previous pass"},
                "semantic_action": "cross_group_combo",
                "scheduler": self._scheduler_state("cross_group", ctx.analysis, base_params=base_params),
                "changes": CmaesStrategy._diff_params(base_params, proposed),
                "stop_reason": "continue",
                "previous_candidate": previous_eval or None,
                **payload,
            }

        group_name = self._select_group(
            ctx.analysis,
            ctx.iteration,
            preferred=previous_eval.get("group"),
            base_params=base_params,
        )
        if not group_name:
            return base_params, {
                "optimizer": self.name,
                "stop_reason": "all_semantic_groups_exhausted",
                "stage": None,
                "previous_candidate": previous_eval or None,
            }

        proposed, decision = self._propose_for_group(
            group_name=group_name,
            base_params=base_params,
            base_fit_score=ctx.fit_score,
            analysis=ctx.analysis,
            iteration=ctx.iteration,
        )
        decision["previous_candidate"] = previous_eval or None
        return proposed, decision

    def _isolation_candidate(self, base_params: dict[str, Any]) -> tuple[dict[str, Any], list[str]] | None:
        """Do not write diagnostic isolation into the optimization path."""

        # Full-image fitting scores the complete material. Suppressing
        # reflection/specular/rim/emission can be useful for diagnostics,
        # but force-accepting that preset corrupts fresh_fit trajectories.
        # Keep isolation out of the real search until it has a separate
        # diagnostic-only render path and metric.
        self._isolation_done = True
        return None

    def _semantic_isolation_values(self, base_params: dict[str, Any]) -> dict[str, Any]:
        """Choose suppress targets from the effect graph before falling back to names."""

        targets: dict[str, Any] = {}
        suppress_tokens = (
            "fresnel",
            "rim",
            "emission",
            "emissive",
            "matcap",
            "specular",
            "reflection",
            "environment",
            "ibl",
            "outline",
        )
        for group in self._graph.groups.values():
            group_text = " ".join(
                [
                    str(group.name),
                    str(group.reason),
                    " ".join(str(item) for item in group.channels),
                    " ".join(str(item) for item in group.unity_features),
                ]
            ).lower()
            if group.name == "base_color" or not any(token in group_text for token in suppress_tokens):
                continue
            for name in self._candidate_generator.candidate_group_params(group):
                if name not in base_params or name in targets:
                    continue
                targets[name] = self._neutral_suppressed_value(name, base_params.get(name))
        return targets

    def _neutral_suppressed_value(self, name: str, value: Any) -> Any:
        sem = self._graph.params.get(name)
        text = " ".join(
            [
                name,
                str(getattr(sem, "group", "")),
                str(getattr(sem, "role", "")),
                str(getattr(sem, "reason", "")),
            ]
        ).lower()
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 0.0
        if isinstance(value, list):
            if any(token in text for token in ("emission", "emissive", "fresnel", "rim", "outline")):
                return [0.0 for _ in value]
            if any(token in text for token in ("matcap", "ibl", "environment", "reflection")):
                return [1.0 for _ in value]
            return [0.0 for _ in value]
        return value

    def stop_reason(self) -> str | None:
        if (
            self._group_cycle >= self._max_group_cycles
            and self._group_order
            and all(self._group_status(name) in {"exhausted", "inactive_or_invisible"} for name in self._group_order)
        ):
            return "semantic_groups_exhausted"
        return None

    def _consume_pending(self, ctx: StrategyContext) -> dict[str, Any]:
        if self._pending is None:
            return {}
        pending = self._pending
        self._pending = None
        group_name = str(pending.get("group") or "")
        state = self._state_for_group(group_name)
        base_fit = float(pending.get("base_fit_score", ctx.fit_score))
        delta = float(ctx.fit_score) - base_fit
        candidate_metrics = metric_vector_from_analysis(ctx.analysis, ctx.fit_score)
        self._record_topk(ctx, group=group_name)
        # Both thresholds are now ``max(abs, rel * base_fit)`` so they
        # auto-scale: when fit_score is tiny (cold-start) almost any
        # measurable gain counts; when fit_score is high we demand a
        # proportionally bigger improvement to keep moving.
        min_improvement = max(
            self._min_improvement_abs,
            self._min_improvement_rel * abs(base_fit),
        )
        probe_threshold = max(
            self._probe_score_delta_abs,
            self._probe_score_delta_rel * abs(base_fit),
        )
        base_metrics = pending.get("base_metrics")
        if not hasattr(base_metrics, "components"):
            base_metrics = metric_vector_from_analysis({}, base_fit)
        acceptance = self._acceptance_policy.evaluate(
            base=base_metrics,
            candidate=candidate_metrics,
            fit_delta=delta,
            min_improvement=min_improvement,
            phase=self._scheduler_phase(),
            force_accept=bool(pending.get("force_accept")),
        )
        run_best_params = getattr(ctx.state, "best_fit_params", {}) or getattr(ctx.state, "best_params", {})
        run_best_score = float(getattr(ctx.state, "best_fit_score", -math.inf))
        if isinstance(run_best_params, dict) and run_best_params:
            self._branch_guard.update_checkpoint(params=run_best_params, fit_score=run_best_score)
        branch_exploratory_accept = (
            not acceptance.accepted
            and acceptance.reason == "insufficient_gain"
            and pending.get("kind") != "probe"
            and self._branch_guard.allows_exploration(fit_score=float(ctx.fit_score))
        )
        accepted = acceptance.accepted or branch_exploratory_accept
        visibly_changed = abs(delta) >= probe_threshold
        if pending.get("kind") == "probe" and visibly_changed:
            state["phase"] = "optimize"
            state["probe_passed"] = True
        if accepted:
            state["status"] = "active"
            state["no_improve"] = 0
            state["best_fit_score"] = max(float(state.get("best_fit_score", -math.inf)), float(ctx.fit_score))
            state["best_params"] = dict(ctx.current_params)
            state["axis_rejected_dirs"] = {}
            state["accepted_count"] = int(state.get("accepted_count", 0)) + 1
            state["total_delta"] = float(state.get("total_delta", 0.0)) + max(delta, 0.0)
            state["last_delta"] = delta
            is_run_best = float(ctx.fit_score) >= run_best_score - 1.0e-9
            drift = self._branch_guard.observe(
                iteration=ctx.iteration,
                params=ctx.current_params,
                fit_score=float(ctx.fit_score),
                metrics=candidate_metrics,
            )
            if drift.should_rollback and self._branch_guard.checkpoint_params:
                next_base = self._branch_guard.checkpoint_params
                outcome = "accepted_but_drift_rollback_to_checkpoint"
                if pending.get("group") == "__breakthrough__":
                    self._trust_region.record_failure()
            else:
                next_base = dict(ctx.current_params)
                if pending.get("force_accept"):
                    outcome = "accepted_for_isolation"
                elif branch_exploratory_accept:
                    outcome = "exploratory_accept_checkpoint_branch"
                elif acceptance.provisional:
                    outcome = "provisional_accept_component_gain"
                elif pending.get("group") == "__breakthrough__" and not is_run_best:
                    outcome = "accepted_trust_region_branch"
                elif not is_run_best:
                    outcome = "accepted_checkpoint_branch"
                else:
                    outcome = "accepted"
                if pending.get("group") == "__breakthrough__":
                    if self._trust_region.can_accept(
                        fit_score=float(ctx.fit_score),
                        global_best_score=run_best_score,
                    ):
                        self._trust_region.record_success(
                            params=ctx.current_params,
                            fit_score=float(ctx.fit_score),
                            min_improvement=min_improvement,
                        )
                    else:
                        self._trust_region.record_failure()
        else:
            state["no_improve"] = int(state.get("no_improve", 0)) + 1
            state["last_delta"] = delta
            base_drift = self._branch_guard.evaluate_without_record(fit_score=base_fit)
            if pending.get("group") == "__breakthrough__" and self._trust_region.active:
                self._trust_region.record_failure()
                if self._trust_region.active:
                    next_base = self._trust_region.center_params or dict(pending.get("base_params") or ctx.current_params)
                else:
                    next_base = dict(pending.get("base_params") or ctx.current_params)
            elif base_drift.should_rollback and self._branch_guard.checkpoint_params:
                next_base = self._branch_guard.checkpoint_params
                outcome = "rejected_drift_rollback_to_checkpoint"
            else:
                next_base = dict(pending.get("base_params") or ctx.current_params)
                outcome = "rejected_keep_branch_base"
            if "outcome" not in locals() or not str(outcome).startswith("rejected_"):
                outcome = "rejected_keep_branch_base"
            limit = self._effective_no_improve_limit(group_name)
            if pending.get("kind") == "probe" and not visibly_changed and state["no_improve"] >= 2:
                state["status"] = "inactive_or_invisible"
            elif state["no_improve"] >= limit:
                state["status"] = "exhausted"
        if pending.get("kind") in {"pattern", "param_priority"} and not accepted:
            self._advance_after_reject(state, pending)
        elif pending.get("kind") in {"pattern", "param_priority"} and accepted:
            if pending.get("joint"):
                state["joint_cursor"] = int(pending.get("joint_index", state.get("joint_cursor", 0))) + 1
            elif pending.get("combo"):
                state["combo_cursor"] = int(pending.get("combo_index", state.get("combo_cursor", 0))) + 1
            else:
                state["axis_cursor"] = int(pending.get("axis_index", 0)) + 1
            state["direction"] = 1.0
        if pending.get("kind") in {"pattern", "param_priority"}:
            state["visit_attempts"] = int(state.get("visit_attempts", 0)) + 1
            if int(state["visit_attempts"]) >= self._effective_visit_limit(group_name):
                if self._group_has_uncovered_priority_params(
                    group_name,
                    base_params=dict(pending.get("base_params") or {}),
                    analysis=ctx.analysis,
                ):
                    state["status"] = "active"
                    state["visit_attempts"] = max(0, self._effective_visit_limit(group_name) - 2)
                else:
                    state["status"] = "exhausted"
        evidence_payload: dict[str, Any] | None = None
        if hasattr(base_metrics, "components") and group_name and not str(group_name).startswith("__"):
            evidence = self._influence.observe(
                group=group_name,
                kind=str(pending.get("kind") or ""),
                before=base_metrics,
                after=candidate_metrics,
                fit_delta=delta,
                accepted=accepted,
                changed_params=[str(item) for item in pending.get("changed_params", [])],
            )
            evidence_payload = {
                "group": evidence.group,
                "kind": evidence.kind,
                "fit_delta": evidence.fit_delta,
                "component_improvement": evidence.component_improvement,
                "accepted": evidence.accepted,
                "changed_params": evidence.changed_params,
            }
        if hasattr(base_metrics, "components"):
            self._param_influence.observe(
                changed_params=[str(item) for item in pending.get("changed_params", [])],
                before=base_metrics,
                after=candidate_metrics,
                fit_delta=delta,
                accepted=accepted,
            )
        return {
            "group": group_name,
            "kind": pending.get("kind"),
            "outcome": outcome,
            "accepted": accepted,
            "fit_score": ctx.fit_score,
            "base_fit_score": base_fit,
            "delta": delta,
            "min_improvement": min_improvement,
            "probe_threshold": probe_threshold,
            "visible_probe_delta": visibly_changed,
            "changed_params": pending.get("changed_params", []),
            "next_base_params": next_base,
            "group_state": self._json_group_state(state),
            "acceptance": acceptance.to_dict(),
            "branch_exploratory_accept": branch_exploratory_accept,
            "branch_guard": self._branch_guard.summary(),
            "evidence": evidence_payload,
            "topk": self._topk_summary(),
        }

    def _propose_for_group(
        self,
        *,
        group_name: str,
        base_params: dict[str, Any],
        base_fit_score: float,
        analysis: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        group = self._graph.groups[group_name]
        state = self._state_for_group(group_name)
        if state["phase"] == "probe":
            probe_params, probe_changes = self._candidate_generator.probe_candidate(base_params, group)
            if probe_changes:
                self._pending = {
                    "group": group_name,
                    "kind": "probe",
                    "base_params": dict(base_params),
                    "base_fit_score": float(base_fit_score),
                    "base_metrics": metric_vector_from_analysis(analysis, base_fit_score),
                    "changed_params": probe_changes,
                }
                return probe_params, self._decision(
                    group=group,
                    state=state,
                    action="probe_group",
                    changes=CmaesStrategy._diff_params(base_params, probe_params),
                    stop_reason="continue",
                    analysis=analysis,
                    base_params=base_params,
                    extra={"probe_changed_params": probe_changes},
                )
            state["phase"] = "optimize"

        priority_result = self._priority_param_candidate(
            group_name=group_name,
            base_params=base_params,
            analysis=analysis,
        )
        if priority_result is not None:
            proposed, priority_payload, priority_row = priority_result
            changes = CmaesStrategy._diff_params(base_params, proposed)
            if changes:
                self._pending = {
                    "group": group_name,
                    "kind": "param_priority",
                    "base_params": dict(base_params),
                    "base_fit_score": float(base_fit_score),
                    "base_metrics": metric_vector_from_analysis(analysis, base_fit_score),
                    "changed_params": [str(change.get("param")) for change in changes if isinstance(change, dict)],
                    **priority_payload,
                }
                return proposed, self._decision(
                    group=group,
                    state=state,
                    action="param_priority_search",
                    changes=changes,
                    stop_reason="continue",
                    analysis=analysis,
                    base_params=base_params,
                    extra={
                        "axis": priority_payload,
                        "param_priority_choice": priority_row,
                    },
                )

        proposed, pattern_payload = self._candidate_generator.pattern_candidate(
            base_params=base_params,
            group=group,
            state=state,
            analysis=analysis,
            iteration=iteration,
        )
        changes = CmaesStrategy._diff_params(base_params, proposed)
        if changes:
            self._pending = {
                "group": group_name,
                "kind": "pattern",
                "base_params": dict(base_params),
                "base_fit_score": float(base_fit_score),
                "base_metrics": metric_vector_from_analysis(analysis, base_fit_score),
                "changed_params": [str(change.get("param")) for change in changes if isinstance(change, dict)],
                **pattern_payload,
            }
        else:
            state["status"] = "exhausted"
        return proposed, self._decision(
            group=group,
            state=state,
            action="pattern_search",
            changes=changes,
            stop_reason="continue" if changes else "no_effective_change",
            analysis=analysis,
            base_params=base_params,
            extra={"axis": pattern_payload} if pattern_payload else {},
        )

    def _cross_group_candidate(
        self,
        *,
        base_params: dict[str, Any],
        base_fit_score: float,
        analysis: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self._group_cycle <= 0 or self._group_cycle in self._cross_group_cycles_done:
            return None
        scored = [
            (
                self._group_utility(name, analysis),
                name,
            )
            for name in self._group_order
        ]
        selected = [name for score, name in sorted(scored, reverse=True) if score > 0.0][:2]
        if len(selected) < 2:
            self._cross_group_cycles_done.add(self._group_cycle)
            return None
        self._cross_group_cycles_done.add(self._group_cycle)
        groups = [self._graph.groups[name] for name in selected if name in self._graph.groups]
        return self._candidate_generator.cross_group_candidate(
            base_params=base_params,
            groups=groups,
            group_cycle=self._group_cycle,
            analysis=analysis,
            base_fit_score=base_fit_score,
            iteration=iteration,
        )

    def _breakthrough_candidate(
        self,
        *,
        base_params: dict[str, Any],
        base_fit_score: float,
        analysis: dict[str, Any],
        iteration: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self._scheduler_phase_for(analysis) != "breakthrough":
            return None
        if self._breakthrough_window_should_pause(iteration=iteration, fit_score=base_fit_score):
            return None
        self._trust_region.ensure(center_params=base_params, fit_score=base_fit_score)
        active_groups = self._active_subspace_groups(analysis)
        active_groups = {
            name
            for name in active_groups
            if name in self._group_order and self._group_status(name) not in {"inactive_or_invisible"}
        }
        if not active_groups:
            active_groups = {
                name
                for name in self._group_order
                if self._group_status(name) not in {"inactive_or_invisible"}
            }
        group_scores = {name: self._group_utility(name, analysis) for name in self._group_order}
        self._breakthrough_queue.ensure(
            base_params=base_params,
            base_fit_score=base_fit_score,
            analysis=analysis,
            iteration=iteration,
            group_cycle=self._group_cycle,
            groups_by_name=self._graph.groups,
            group_order=self._group_order,
            group_scores=group_scores,
            active_groups=active_groups,
            bottleneck=self._metric_bottleneck(analysis),
            archive=self._topk,
            generator=self._candidate_generator,
            param_agenda=self._param_agenda(base_params, analysis, limit=self._param_candidate_pool_size),
            radius_scale=self._trust_region.radius_scale,
        )
        return self._breakthrough_queue.pop()

    def _state_for_group(self, group_name: str) -> dict[str, Any]:
        state = self._group_state.get(group_name)
        if state is not None:
            return state
        group = self._graph.groups.get(group_name)
        state = {
            "phase": "probe" if group is not None and (group.probe_required or not group.current_active) else "optimize",
            "status": "pending",
            "step_index": 0,
            "axis_cursor": 0,
            "direction": 1.0,
            "no_improve": 0,
            "probe_passed": False,
            "best_fit_score": -math.inf,
            "best_params": dict(self._initial_params),
            "visit_attempts": 0,
            "accepted_count": 0,
            "total_delta": 0.0,
            "last_delta": 0.0,
            "joint_cursor": 0,
        }
        self._group_state[group_name] = state
        return state

    def _group_status(self, group_name: str) -> str:
        return str(self._state_for_group(group_name).get("status", "pending"))

    def _effective_no_improve_limit(self, group_name: str) -> int:
        group = self._graph.groups.get(group_name)
        if group is None:
            return self._max_group_no_improve
        searchable = [
            name
            for name in self._candidate_generator.candidate_group_params(group)
            if self._graph.params.get(name) is not None and self._graph.params[name].searchable
        ]
        if len(searchable) <= 2:
            return self._max_group_no_improve_small
        return self._max_group_no_improve

    def _effective_visit_limit(self, group_name: str) -> int:
        group = self._graph.groups.get(group_name)
        if group is None:
            return 6
        searchable = [
            name
            for name in self._candidate_generator.candidate_group_params(group)
            if self._graph.params.get(name) is not None and self._graph.params[name].searchable
        ]
        # A group pass is an exploration budget, not a proof that the
        # group is globally solved. Without this cap, one-dimensional
        # groups such as emission can keep resetting no_improve after
        # small accepted moves and starve all later semantic groups.
        return max(6, min(18, len(searchable) * 3))

    def _advance_after_reject(self, state: dict[str, Any], pending: dict[str, Any]) -> None:
        if pending.get("joint"):
            state["joint_cursor"] = int(pending.get("joint_index", state.get("joint_cursor", 0))) + 1
            return
        if pending.get("combo"):
            state["combo_cursor"] = int(pending.get("combo_index", state.get("combo_cursor", 0))) + 1
            if int(state.get("no_improve", 0)) > 0 and int(state["no_improve"]) % 4 == 0:
                state["step_index"] = min(int(state.get("step_index", 0)) + 1, len(self._step_schedule) - 1)
            return
        # Track per-axis +/- attempts so once both directions have been
        # rejected for the same axis we advance the cursor immediately.
        # Without this the strategy spent 7+ iterations re-trying a
        # single u_BaseColor axis in the first FishStandard run.
        axis_index = int(pending.get("axis_index", state.get("axis_cursor", 0)))
        direction = float(pending.get("direction", state.get("direction", 1.0)) or 1.0)
        rejected = state.setdefault("axis_rejected_dirs", {})
        bucket = rejected.setdefault(axis_index, [])
        sign = "+" if direction >= 0.0 else "-"
        if sign not in bucket:
            bucket.append(sign)
        both_dirs_tried = "+" in bucket and "-" in bucket
        if both_dirs_tried:
            state["axis_cursor"] = axis_index + 1
            state["direction"] = 1.0
            rejected.pop(axis_index, None)
        elif direction > 0.0:
            state["direction"] = -1.0
        else:
            state["direction"] = 1.0
            state["axis_cursor"] = axis_index + 1
            rejected.pop(axis_index, None)
        if int(state.get("no_improve", 0)) > 0 and int(state["no_improve"]) % 4 == 0:
            state["step_index"] = min(int(state.get("step_index", 0)) + 1, len(self._step_schedule) - 1)

    def _decision(
        self,
        *,
        group: Any,
        state: dict[str, Any],
        action: str,
        changes: list[dict[str, Any]],
        stop_reason: str,
        analysis: dict[str, Any] | None = None,
        base_params: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "optimizer": self.name,
            "stage": {"name": group.name, "description": f"semantic group {action}: {group.reason}"},
            "semantic_group": group.to_dict(),
            "semantic_action": action,
            "group_state": self._json_group_state(state),
            "scheduler": self._scheduler_state(group.name, analysis, base_params=base_params),
            "changes": changes,
            "stop_reason": stop_reason,
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _json_group_state(state: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in state.items()
            if key != "best_params"
        }

    @staticmethod
    def _group_order_key(group: Any) -> int:
        order = int(getattr(group, "order", 0) or 0)
        if order > 0:
            return order
        if getattr(group, "name", "") == "base_color":
            return 0
        return 10_000

    def _scheduler_state(
        self,
        selected_group: str,
        analysis: dict[str, Any] | None = None,
        *,
        base_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        statuses: dict[str, dict[str, Any]] = {}
        bottleneck = self._metric_bottleneck(analysis or {})
        ranking = self._param_ranking(base_params or {}, analysis or {}, limit=None)
        gated_rows = self._gated_param_rows(base_params or {})
        activation_rows = self._activation_param_rows(base_params or {}, analysis or {})
        for name in self._group_order:
            state = self._state_for_group(name)
            runtime_status = self._graph.runtime_group_status(name, base_params or {})
            statuses[name] = {
                "status": self._group_status(name),
                "runtime_active": runtime_status.get("active"),
                "runtime_gate_reason": runtime_status.get("reason"),
                "runtime_blocked_by": runtime_status.get("blocked_by", []),
                "visit_attempts": int(state.get("visit_attempts", 0) or 0),
                "visit_limit": self._effective_visit_limit(name),
                "accepted_count": int(state.get("accepted_count", 0) or 0),
                "total_delta": float(state.get("total_delta", 0.0) or 0.0),
                "diagnostic_score": self._diagnostic_score_for_group(name, analysis or {}),
                "utility": self._group_utility(name, analysis or {}),
                "influence": self._influence.summary_for(name, bottleneck),
            }
        return {
            "phase": self._scheduler_phase_for(analysis or {}),
            "raw_phase": self._scheduler_phase(),
            "cycle": self._group_cycle,
            "force_breakthrough": self._force_breakthrough,
            "plateau": self._plateau_summary(),
            "trust_region": self._trust_region.summary(),
            "branch_guard": self._branch_guard.summary(),
            "order_revision": self._group_order_revision,
            "selected_group": selected_group,
            "group_order": list(self._group_order),
            "group_status": statuses,
            "component_bottleneck": bottleneck,
            "param_selection_rule": (
                "Rank all searchable params by bottleneck relevance, observed gain, "
                "exploration bonus, risk, failures, and oversampling penalty; "
                "groups are used only as semantic constraints and coverage guards."
            ),
            "search_param_count": len(ranking),
            "all_searchable_param_count": self._searchable_param_count(base_params or {}),
            "gated_param_count": len(gated_rows),
            "activation_candidate_count": len(activation_rows),
            "param_ranking": ranking,
            "param_candidate_pool_size": self._param_candidate_pool_size,
            "param_candidate_pool": ranking[: self._param_candidate_pool_size],
            "param_agenda": ranking[: self._param_candidate_pool_size],
            "gated_params": gated_rows,
            "activation_candidates": activation_rows,
            "topk": self._topk_summary(),
            "breakthrough_queue": self._breakthrough_queue.summary(),
            "acceptance_policy": self._acceptance_policy.summary(),
        }

    def _select_group(
        self,
        analysis: dict[str, Any],
        iteration: int,
        preferred: Any = None,
        base_params: dict[str, Any] | None = None,
    ) -> str:
        if not self._metric_bottleneck(analysis):
            for name in self._group_order:
                if self._group_status(name) not in {"exhausted", "inactive_or_invisible"}:
                    return name
        ranking = self._param_ranking(base_params or {}, analysis, limit=None)
        preferred_name = str(preferred or "")
        if preferred_name in self._group_order and self._group_status(preferred_name) not in {"exhausted", "inactive_or_invisible"}:
            global_best = float(ranking[0].get("priority", 0.0)) if ranking else 0.0
            preferred_best = max(
                (
                    float(item.get("priority", 0.0))
                    for item in ranking
                    if item.get("group") == preferred_name
                ),
                default=0.0,
            )
            if preferred_best >= global_best * 0.85:
                return preferred_name

        for item in ranking:
            group_name = str(item.get("group") or "")
            if group_name in self._group_order and self._group_status(group_name) not in {"exhausted", "inactive_or_invisible"}:
                return group_name

        for name in self._group_order:
            if self._group_status(name) not in {"exhausted", "inactive_or_invisible"}:
                return name
        if self._restart_exhausted_groups(analysis):
            for name in self._group_order:
                if self._group_status(name) not in {"exhausted", "inactive_or_invisible"}:
                    return name
        return ""

    def _restart_exhausted_groups(self, analysis: dict[str, Any]) -> bool:
        if self._group_cycle >= self._max_group_cycles:
            return False
        restarted = False
        self._group_cycle += 1
        active_subset = self._active_subspace_groups(analysis) if self._scheduler_phase_for(analysis) == "breakthrough" else set(self._group_order)
        for name in self._group_order:
            state = self._state_for_group(name)
            if state.get("status") != "exhausted":
                continue
            if name not in active_subset:
                continue
            state["status"] = "pending"
            state["phase"] = "optimize"
            state["no_improve"] = 0
            state["axis_cursor"] = 0
            state["combo_cursor"] = 0
            state["direction"] = 1.0
            state["axis_rejected_dirs"] = {}
            state["step_index"] = min(int(state.get("step_index", 0)) + 1, len(self._step_schedule) - 1)
            state["visit_attempts"] = 0
            restarted = True
        if restarted:
            self._reprioritize_groups_for_refinement(analysis)
        return restarted

    def _active_subspace_groups(self, analysis: dict[str, Any]) -> set[str]:
        """Choose a compact restart subspace from current bottlenecks.

        This is the non-neural P1 version of learned sensitivity: combine
        semantic diagnostic utility with online influence evidence, then
        restart only the groups that still look capable of reducing the
        largest component losses. If the evidence is sparse, keep all
        groups to avoid premature exclusion.
        """

        protected = self._protected_groups_for_bottleneck(self._metric_bottleneck(analysis))
        scored = [(self._group_utility(name, analysis), name) for name in self._group_order]
        positive = [(score, name) for score, name in scored if score > 0.0]
        if len(positive) < 2:
            return set(self._group_order) if not protected else protected
        positive.sort(reverse=True)
        keep_count = max(2, min(4, len(positive)))
        return {name for _, name in positive[:keep_count]} | protected

    def _reprioritize_groups_for_refinement(self, analysis: dict[str, Any]) -> None:
        previous_order = {name: index for index, name in enumerate(self._group_order)}

        self._group_order.sort(
            key=lambda name: (
                self._group_utility(name, analysis) <= 0.0,
                -self._group_utility(name, analysis),
                previous_order.get(name, 10_000),
            )
        )
        self._group_order_revision += 1

    def _group_utility(self, group_name: str, analysis: dict[str, Any]) -> float:
        state = self._state_for_group(group_name)
        group = self._graph.groups.get(group_name)
        priority = float(getattr(group, "search_priority", 0.0) or 0.0) if group is not None else 0.0
        bottleneck = self._metric_bottleneck(analysis)
        return (
            float(state.get("total_delta", 0.0) or 0.0)
            + 0.01 * float(state.get("accepted_count", 0) or 0)
            + 0.25 * self._diagnostic_score_for_group(group_name, analysis)
            + 0.50 * self._influence.utility_for(group_name, bottleneck)
            + self._bottleneck_group_bonus(group_name, bottleneck)
            + 0.001 * priority
        )

    def _scheduler_phase(self) -> str:
        if self._current_iteration < self._breakthrough_cooldown_until:
            return "refinement" if self._group_cycle > 0 else "exploration"
        if self._force_breakthrough:
            return "breakthrough"
        if self._group_cycle <= 0:
            return "exploration"
        if self._group_cycle >= self._breakthrough_cycle:
            return "breakthrough"
        return "refinement"

    def _breakthrough_window_should_pause(self, *, iteration: int, fit_score: float) -> bool:
        if self._breakthrough_window_start is None:
            self._breakthrough_window_start = int(iteration)
            self._breakthrough_window_best = float(fit_score)
            self._breakthrough_window_no_improve = 0
            return False
        if float(fit_score) > self._breakthrough_window_best + self._min_improvement_abs:
            self._breakthrough_window_best = float(fit_score)
            self._breakthrough_window_no_improve = 0
        else:
            self._breakthrough_window_no_improve += 1
        elapsed = int(iteration) - int(self._breakthrough_window_start)
        if (
            elapsed < self._breakthrough_window_max_iters
            and self._breakthrough_window_no_improve < self._breakthrough_window_max_no_improve
        ):
            return False
        self._force_breakthrough = False
        self._breakthrough_cooldown_until = int(iteration) + self._breakthrough_cooldown_iters
        self._breakthrough_window_start = None
        self._breakthrough_window_best = -math.inf
        self._breakthrough_window_no_improve = 0
        self._trust_region = TrustRegionBranch()
        return True

    def _scheduler_phase_for(self, analysis: dict[str, Any]) -> str:
        raw_phase = self._scheduler_phase()
        if raw_phase != "breakthrough":
            return raw_phase
        if self._breakthrough_ready(analysis):
            return "breakthrough"
        return "refinement"

    def _breakthrough_ready(self, analysis: dict[str, Any]) -> bool:
        required = self._required_groups_before_breakthrough(analysis)
        if not required:
            return True
        for name in required:
            if name not in self._group_order:
                continue
            if not self._group_ready_for_breakthrough(name):
                return False
        return True

    def _group_ready_for_breakthrough(self, group_name: str) -> bool:
        status = self._group_status(group_name)
        if status == "inactive_or_invisible":
            return True
        state = self._state_for_group(group_name)
        visits = int(state.get("visit_attempts", 0) or 0)
        accepted = int(state.get("accepted_count", 0) or 0)
        min_visits = self._minimum_group_coverage(group_name)
        if visits < min_visits and accepted <= 0:
            return False
        if status == "exhausted":
            return True
        # Visit count is only a coverage floor. The real gate is marginal
        # return: if a group is still pulling score upward, keep refining it
        # before handing control to cross-group breakthrough.
        if int(state.get("no_improve", 0) or 0) >= 2:
            return True
        last_delta = float(state.get("last_delta", 0.0) or 0.0)
        if visits >= min_visits and last_delta <= self._min_improvement_abs:
            return True
        avg_gain = float(state.get("total_delta", 0.0) or 0.0) / max(visits, 1)
        return visits >= max(min_visits + 2, 4) and avg_gain <= self._min_improvement_rel

    def _minimum_group_coverage(self, group_name: str) -> int:
        group = self._graph.groups.get(group_name)
        if group is None:
            return 1
        searchable = [
            name
            for name in self._candidate_generator.candidate_group_params(group)
            if self._graph.params.get(name) is not None and self._graph.params[name].searchable
        ]
        if group_name in {"shadow_diffuse", "specular_smoothness", "reflection_matcap"}:
            return min(6, max(4, len(searchable)))
        if group_name in {"base_color", "color_grade", "shared_mask_lmap", "normal_detail"}:
            return min(4, max(2, len(searchable)))
        return min(3, max(1, len(searchable)))

    def _required_groups_before_breakthrough(self, analysis: dict[str, Any]) -> set[str]:
        bottleneck = self._metric_bottleneck(analysis)
        required = {"base_color", "color_grade", "shared_mask_lmap", "reflection_matcap"}
        keys = set(bottleneck)
        if keys & {"color_mean", "color_p95", "luminance_mae", "luminance_bias", "highlight"}:
            required.update({"shadow_diffuse", "specular_smoothness"})
        if keys & {"structure_ssim_l", "detail_texture"}:
            required.update({"normal_detail"})
        return {name for name in required if name in self._graph.groups}

    def _metric_bottleneck(self, analysis: dict[str, Any]) -> dict[str, float]:
        metrics = metric_vector_from_analysis(analysis, None)
        components = metrics.bottleneck()
        if not components:
            return {}
        ordered = sorted(components.items(), key=lambda item: item[1], reverse=True)
        return dict(ordered[:4])

    def _update_plateau_state(self, ctx: StrategyContext) -> None:
        best_score = getattr(ctx.state, "best_fit_score", None)
        if not isinstance(best_score, (int, float)) or not math.isfinite(float(best_score)):
            best_score = ctx.fit_score
        if not isinstance(best_score, (int, float)) or not math.isfinite(float(best_score)):
            return
        self._best_fit_history.append((int(ctx.iteration), float(best_score)))
        self._best_fit_history = self._best_fit_history[-(self._plateau_window + 2):]
        if self._force_breakthrough or int(ctx.iteration) < self._early_breakthrough_iteration:
            return
        if not self._plateau_search_space_ready():
            return
        if len(self._best_fit_history) < self._plateau_window:
            return
        old_iteration, old_best = self._best_fit_history[-self._plateau_window]
        if int(ctx.iteration) - old_iteration < self._plateau_window - 1:
            return
        if float(best_score) - float(old_best) < self._plateau_min_gain:
            self._force_breakthrough = True
            self._reprioritize_groups_for_refinement(ctx.analysis)

    def _plateau_search_space_ready(self) -> bool:
        if self._group_cycle > 0:
            return True
        active = [
            name
            for name in self._group_order
            if self._group_status(name) != "inactive_or_invisible"
        ]
        if not active:
            return False
        exhausted = [
            name
            for name in active
            if self._group_status(name) == "exhausted"
        ]
        return (len(exhausted) / max(len(active), 1)) >= self._plateau_min_exhausted_ratio

    def _plateau_summary(self) -> dict[str, Any]:
        if not self._best_fit_history:
            return {
                "window": self._plateau_window,
                "min_gain": self._plateau_min_gain,
                "force_breakthrough": self._force_breakthrough,
                "breakthrough_window_start": self._breakthrough_window_start,
                "breakthrough_window_best": self._breakthrough_window_best if math.isfinite(self._breakthrough_window_best) else None,
                "breakthrough_window_no_improve": self._breakthrough_window_no_improve,
                "breakthrough_cooldown_until": self._breakthrough_cooldown_until,
            }
        oldest_iteration, oldest_best = self._best_fit_history[0]
        latest_iteration, latest_best = self._best_fit_history[-1]
        return {
            "window": self._plateau_window,
            "min_gain": self._plateau_min_gain,
            "force_breakthrough": self._force_breakthrough,
            "breakthrough_window_start": self._breakthrough_window_start,
            "breakthrough_window_best": self._breakthrough_window_best if math.isfinite(self._breakthrough_window_best) else None,
            "breakthrough_window_no_improve": self._breakthrough_window_no_improve,
            "breakthrough_cooldown_until": self._breakthrough_cooldown_until,
            "min_exhausted_ratio": self._plateau_min_exhausted_ratio,
            "search_space_ready": self._plateau_search_space_ready(),
            "oldest_iteration": oldest_iteration,
            "latest_iteration": latest_iteration,
            "best_gain": latest_best - oldest_best,
        }

    def _protected_groups_for_bottleneck(self, bottleneck: dict[str, float]) -> set[str]:
        protected: set[str] = set()
        keys = set(bottleneck)
        if keys & {"color_mean", "color_p95", "luminance_mae", "luminance_bias"}:
            protected.update({"base_color", "color_grade", "shared_mask_lmap", "shadow_diffuse", "reflection_matcap"})
        if keys & {"highlight"}:
            protected.update({"shadow_diffuse", "specular_smoothness", "fresnel", "reflection_matcap"})
        if keys & {"structure_ssim_l", "detail_texture"}:
            protected.update({"normal_detail", "base_color", "shadow_diffuse"})
        return {name for name in protected if name in self._graph.groups}

    def _bottleneck_group_bonus(self, group_name: str, bottleneck: dict[str, float]) -> float:
        if group_name not in self._protected_groups_for_bottleneck(bottleneck):
            return 0.0
        if not bottleneck:
            return 0.0
        return 0.03 * max(float(value) for value in bottleneck.values())

    def _priority_param_candidate(
        self,
        *,
        group_name: str,
        base_params: dict[str, Any],
        analysis: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        if not self._metric_bottleneck(analysis):
            return None
        group = self._graph.groups.get(group_name)
        if group is None:
            return None
        group_params = set(self._candidate_generator.candidate_group_params(group))
        ranking = [
            item
            for item in self._param_ranking(base_params, analysis, limit=None)
            if item.get("param") in group_params
        ]
        if not ranking:
            return None
        state = self._state_for_group(group_name)
        direction = float(state.get("direction", 1.0) or 1.0)
        for row in ranking[:4]:
            param_name = str(row.get("param") or "")
            result = self._candidate_generator.nudge_param_candidate(
                base_params=base_params,
                param_name=param_name,
                step_scale=1.0,
                group_cycle=self._group_cycle,
                axis_offset=0,
                direction_override=direction,
            )
            if result is None:
                continue
            proposed, payload = result
            payload.update(
                {
                    "candidate_kind": "param_priority",
                    "priority": row.get("priority"),
                    "semantic_relevance": row.get("semantic_relevance"),
                    "attempts": row.get("attempts"),
                    "accepted": row.get("accepted"),
                }
            )
            return proposed, payload, row
        return None

    def _param_agenda(self, base_params: dict[str, Any], analysis: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
        return self._param_ranking(base_params, analysis, limit=limit)

    def _param_ranking(self, base_params: dict[str, Any], analysis: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
        bottleneck = self._metric_bottleneck(analysis)
        source_names = (
            self._graph.active_search_params_for(base_params)
            if base_params
            else self._graph.active_search_params()
        )
        names = [
            name
            for name in source_names
            if not base_params or name in base_params
        ]
        rows: list[dict[str, Any]] = []
        for name in names:
            sem = self._graph.params.get(name)
            group_name = str(getattr(sem, "group", "") or "")
            relevance = self._semantic_relevance_for_param(name, bottleneck)
            summary = self._param_influence.summary_for(name, bottleneck, semantic_relevance=relevance)
            rows.append(
                {
                    "param": name,
                    "group": group_name,
                    "group_status": self._group_status(group_name) if group_name in self._graph.groups else "ungrouped",
                    "role": str(getattr(sem, "role", "") or ""),
                    "transform": str(getattr(sem, "transform", "") or ""),
                    **summary,
                }
            )
        rows.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
        if limit is None:
            return rows
        return rows[: max(0, int(limit))]

    def _searchable_param_count(self, base_params: dict[str, Any]) -> int:
        return len(
            [
                name
                for name, sem in self._graph.params.items()
                if sem.searchable and (not base_params or name in base_params)
            ]
        )

    def _gated_param_rows(self, base_params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for item in self._graph.gated_search_params_for(base_params):
            name = str(item.get("param") or "")
            if base_params and name not in base_params:
                continue
            rows.append(item)
        return rows

    def _group_has_uncovered_priority_params(
        self,
        group_name: str,
        *,
        base_params: dict[str, Any],
        analysis: dict[str, Any],
    ) -> bool:
        if not base_params:
            return False
        rows = [
            item
            for item in self._param_ranking(base_params, analysis, limit=None)
            if item.get("group") == group_name
        ]
        if not rows:
            return False
        top_priority = float(rows[0].get("priority", 0.0) or 0.0)
        for item in rows[:6]:
            attempts = int(item.get("attempts", 0) or 0)
            priority = float(item.get("priority", 0.0) or 0.0)
            if attempts <= 0 and priority >= top_priority * 0.65:
                return True
        return False

    def _activation_param_rows(self, base_params: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
        bottleneck = self._metric_bottleneck(analysis)
        rows: list[dict[str, Any]] = []
        for item in self._graph.activation_params_for(base_params):
            name = str(item.get("param") or "")
            if base_params and name not in base_params:
                continue
            relevance = self._semantic_relevance_for_param(name, bottleneck)
            summary = self._param_influence.summary_for(name, bottleneck, semantic_relevance=relevance)
            rows.append({"param": name, **item, **summary})
        rows.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
        return rows

    def _semantic_relevance_for_param(self, param_name: str, bottleneck: dict[str, float]) -> float:
        sem = self._graph.params.get(param_name)
        text = " ".join(
            [
                param_name,
                str(getattr(sem, "group", "")),
                str(getattr(sem, "role", "")),
                str(getattr(sem, "transform", "")),
            ]
        ).lower()
        keys = set(bottleneck)
        score = 0.0
        if keys & {"color_mean", "color_p95"}:
            if any(token in text for token in ("color", "saturation", "hue", "gamma", "texpower", "reflect", "shadow")):
                score += 0.055
        if keys & {"luminance_mae", "luminance_bias"}:
            if any(token in text for token in ("gamma", "power", "intensity", "shadow", "ao", "contrast", "reflect")):
                score += 0.045
        if keys & {"highlight"}:
            if any(token in text for token in ("specular", "smooth", "threshold", "shadow", "rim", "fresnel", "reflect")):
                score += 0.055
        if keys & {"structure_ssim_l", "detail_texture"}:
            if any(token in text for token in ("normal", "smooth", "threshold", "specular", "shadow", "power")):
                score += 0.045
        return score

    def _record_topk(self, ctx: StrategyContext, group: str | None) -> None:
        self._topk.add(
            params=ctx.current_params,
            fit_score=float(ctx.fit_score),
            metrics=metric_vector_from_analysis(ctx.analysis, ctx.fit_score),
            group=group,
            iteration=int(ctx.iteration),
        )

    def _topk_summary(self) -> list[dict[str, Any]]:
        return self._topk.summary(limit=5)

    def _diagnostic_score_for_group(self, group_name: str, analysis: dict[str, Any]) -> float:
        group = self._graph.groups.get(group_name)
        if group is None or not isinstance(analysis, dict):
            return 0.0
        channels = analysis.get("material_channels")
        if not isinstance(channels, dict):
            return 0.0
        scores = [
            self._score_channel_diagnostic(channels.get(channel_name))
            for channel_name in getattr(group, "channels", [])
        ]
        scores = [score for score in scores if score > 0.0]
        if not scores:
            return 0.0
        # Use max rather than sum so broad groups do not win merely by
        # owning more diagnostic channels.
        return max(scores)

    @classmethod
    def _score_channel_diagnostic(cls, payload: Any) -> float:
        if not isinstance(payload, dict) or payload.get("valid") is False:
            return 0.0
        key_weights = {
            "rgb_mae": 1.0,
            "avg_rgb_mae": 1.0,
            "max_rgb_mae": 1.2,
            "luma_mae": 0.8,
            "gradient_loss": 0.8,
            "laplacian_loss": 0.8,
            "highlight_area_error": 0.8,
            "peak_luminance_error": 0.8,
        }
        best = 0.0
        for key, weight in key_weights.items():
            value = cls._finite_float(payload.get(key))
            if value is not None:
                best = max(best, abs(value) * weight)
        for key in (
            "luma_bias_candidate_minus_reference",
            "avg_luma_bias_candidate_minus_reference",
            "saturation_bias_candidate_minus_reference",
        ):
            value = cls._finite_float(payload.get(key))
            if value is not None:
                best = max(best, abs(value) * 0.5)
        return best

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None

# ---------------------------------------------------------------------
# Strategy factory


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
) -> OptimizerStrategy:
    """Construct the requested strategy.

    ``optimizer`` is one of:

    * ``"heuristic"`` — current production path (E-002 stage-aware).
    * ``"cma_cold"`` — vanilla CMA-ES.
    * ``"cma_warm"`` — Warm-Started CMA-ES (E-006).
    * ``"semantic_group"`` — effect-group local search.

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
    if optimizer in ("cma_cold", "cma_warm"):
        config = cma_es_config or CmaesStrategyConfig()
        config = CmaesStrategyConfig(
            mode="cold" if optimizer == "cma_cold" else "warm",
            warm_start_iters=config.warm_start_iters,
            population_size=config.population_size,
            sigma=config.sigma,
            seed=config.seed,
            hint_bias_mix_ratio=config.hint_bias_mix_ratio,
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
        "(expected 'heuristic', 'cma_cold', 'cma_warm', or 'semantic_group')"
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
    return CmaesStrategyConfig(
        mode=str(mode).strip().lower() if isinstance(mode, str) and mode else "warm",
        warm_start_iters=int(data.get("warm_start_iters", 12)),
        population_size=_optional_int(data.get("population_size")),
        sigma=_optional_float(data.get("sigma")),
        seed=_optional_int(data.get("seed")),
        hint_bias_mix_ratio=mix_ratio,
    )


def cmaes_strategy_config_to_dict(config: CmaesStrategyConfig) -> dict[str, Any]:
    return asdict(config)


# ---------------------------------------------------------------------
# tiny utilities


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _isclose(a: float, b: float, *, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


__all__ = [
    "CmaesStrategy",
    "CmaesStrategyConfig",
    "HeuristicStrategy",
    "SemanticGroupStrategy",
    "OptimizerStrategy",
    "OptimizerUnavailableError",
    "StrategyContext",
    "build_strategy",
    "cmaes_strategy_config_from_dict",
    "cmaes_strategy_config_to_dict",
]
