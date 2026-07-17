"""CMA-ES optimizer strategy implementation."""

from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .semantic_graph import ShaderEffectGraph
from .strategy_core import (
    CmaesStrategyConfig,
    OptimizerStrategy,
    OptimizerUnavailableError,
    StrategyContext,
)
from .strategy_utils import (
    _coerce_initial_design_pairs,
    _isclose,
    _normalize_initial_design_local_step_ratio,
    _normalize_initial_design_method,
    _normalize_restart_center_mode,
    _normalize_restart_population_schedule,
    _to_number,
    _vector_key,
)


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
        axis_bounds: dict[str, tuple[float, float]] | None = None,
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
            allow_scene_lighting=bool(config.allow_scene_lighting),
            axis_bounds=axis_bounds,
        )
        if self._encoder.dim == 0:
            raise OptimizerUnavailableError(
                "CMA-ES has no trainable axes for this material — every "
                "parameter is either a texture binding, a tiling vector, "
                "or blacklisted. Switch to the heuristic optimizer."
            )

        warm_samples: list[tuple[dict[str, Any], float]] = []
        if config.mode == "warm" and warm_start_history:
            warm_samples = [
                (dict(params), self._fit_score_to_loss(float(fit_score), math.inf))
                for params, fit_score in list(warm_start_history[: max(int(config.warm_start_iters), 0)])
            ]
        # WS-CMA-ES requires ≥2 samples to estimate covariance; fall
        # back to cold gracefully when we don't have enough.
        if len(warm_samples) < 2:
            warm_samples = []
        self._base_warm_samples = list(warm_samples)
        self._cma_config_kwargs = dict(cma_config_kwargs)

        self._opt = self._new_optimizer(
            warm_start_samples=warm_samples or None,
            initial_mean=initial_params,
        )
        self._warm_started = self._opt.warm_started
        self._history_size_used = len(warm_samples)
        self._initial_population_size = max(int(self.population_size), 1)
        self._restart_count = 0
        self._last_restart_evaluation = 0
        self._last_restart_reason: str | None = None
        self._last_restart_center_mode: str | None = None
        self._last_restart_center_distance_norm: float | None = None

        # CMA-ES runs in ask/tell pairs. We hold the *currently asked*
        # parameter set + the fitness from the *previous* completed
        # iteration so we can chain them on the next propose() call.
        self._pending_params: dict[str, Any] | None = None
        self._last_observed_fitness: float | None = None
        # Sample a first proposal eagerly so the caller doesn't have to
        # special-case "iter 0 has no previous fitness".
        self._asked_first = False
        self._initial_design_requested = max(int(config.initial_design_samples), 0)
        self._initial_design_method = _normalize_initial_design_method(config.initial_design_method)
        self._initial_design_include_current = bool(config.initial_design_include_current)
        self._initial_design_local_step_ratio = _normalize_initial_design_local_step_ratio(
            config.initial_design_local_step_ratio
        )
        self._initial_design_queue = self._build_initial_design_queue(initial_params)
        self._initial_design_pending: list[tuple[int, dict[str, Any]]] = []
        self._initial_design_results: list[dict[str, Any]] = []
        self._initial_design_activated = not self._initial_design_queue

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
        if (
            self._stagnation_stop_after_restarts
            and self._stagnation_status()["plateau"]
            and self._restart_count >= self._max_restarts
        ):
            return "cmaes_stagnation"
        return None

    def wants_global_no_improve_check(self) -> bool:
        # E-010: CMA-ES is stochastic. A 4-consecutive-not-better
        # window is not evidence the run is stuck; it is the
        # *expected* behaviour for the first few generations.
        return False

    def save_checkpoint(self, path: str | Path) -> None:
        checkpoint_path = Path(path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_bytes(
            pickle.dumps(
                {
                    "metadata": self._opt.checkpoint_metadata_payload(),
                    "strategy_metadata": {
                        "schema_version": 1,
                        "restart_count": self._restart_count,
                        "last_restart_evaluation": self._last_restart_evaluation,
                        "last_restart_reason": self._last_restart_reason,
                        "last_restart_center_mode": self._last_restart_center_mode,
                        "last_restart_center_distance_norm": self._last_restart_center_distance_norm,
                        "initial_design_queue": self._initial_design_queue,
                        "initial_design_pending": self._initial_design_pending,
                        "initial_design_results": self._initial_design_results,
                        "initial_design_activated": self._initial_design_activated,
                    },
                    "optimizer": self._opt,
                }
            )
        )

    def load_checkpoint(self, path: str | Path) -> None:
        from .cma_es_optimizer import CmaesOptimizer  # noqa: WPS433 — lazy import

        checkpoint_path = Path(path)
        strategy_metadata: dict[str, Any] = {}
        try:
            payload = pickle.loads(checkpoint_path.read_bytes())
        except (OSError, pickle.UnpicklingError, EOFError, TypeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("strategy_metadata"), dict):
            strategy_metadata = dict(payload["strategy_metadata"])
        self._opt = CmaesOptimizer.load_checkpoint(path, expected_encoder=self._encoder)
        self._warm_started = self._opt.warm_started
        history = self._opt.history()
        self._last_observed_fitness = history[-1][1] if history else None
        self._pending_params = None
        self._asked_first = bool(history)
        self._restart_count = max(int(strategy_metadata.get("restart_count") or 0), 0)
        self._last_restart_evaluation = min(
            max(int(strategy_metadata.get("last_restart_evaluation") or 0), 0),
            self._opt.evaluations,
        )
        reason = strategy_metadata.get("last_restart_reason")
        self._last_restart_reason = str(reason) if isinstance(reason, str) and reason else None
        center_mode = strategy_metadata.get("last_restart_center_mode")
        self._last_restart_center_mode = str(center_mode) if isinstance(center_mode, str) and center_mode else None
        center_distance = strategy_metadata.get("last_restart_center_distance_norm")
        try:
            self._last_restart_center_distance_norm = (
                float(center_distance) if center_distance is not None else None
            )
        except (TypeError, ValueError):
            self._last_restart_center_distance_norm = None
        self._initial_design_queue = _coerce_initial_design_pairs(
            strategy_metadata.get("initial_design_queue")
        )
        self._initial_design_pending = _coerce_initial_design_pairs(
            strategy_metadata.get("initial_design_pending")
        )
        raw_results = strategy_metadata.get("initial_design_results")
        self._initial_design_results = [dict(item) for item in raw_results] if isinstance(raw_results, list) else []
        self._initial_design_activated = bool(strategy_metadata.get("initial_design_activated", True))

    def _new_optimizer(
        self,
        *,
        warm_start_samples: list[tuple[dict[str, Any], float]] | None,
        initial_mean: dict[str, Any] | Any,
    ) -> Any:
        from .cma_es_optimizer import CmaesConfig, CmaesOptimizer  # noqa: WPS433 — lazy import

        return CmaesOptimizer(
            self._encoder,
            config=CmaesConfig(**self._cma_config_kwargs),
            warm_start_samples=warm_start_samples,
            initial_mean=initial_mean,
        )

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._initial_design_pending:
            self._record_initial_design_scores([(float(ctx.fit_score), float(ctx.diff_score))])
            if not self._initial_design_queue:
                self._activate_initial_design_optimizer()
        if self._initial_design_queue:
            index, proposed = self._initial_design_queue.pop(0)
            self._initial_design_pending.append((index, proposed))
            return proposed, self._build_initial_design_decision(ctx, proposed)

        if self._pending_params is None and self._opt.pending_count > 0:
            raise RuntimeError(
                "propose() cannot run while batch candidates are pending; "
                "call tell_many_scores() first"
            )

        # 1. Tell back the previous iteration's fitness, if we have a
        #    pending ask waiting for a response. CMA-ES is minimization,
        #    so loss = 1 - fit_score (clipped) translates "higher score
        #    is better" into the right direction.
        if self._pending_params is not None:
            loss = self._fit_score_to_loss(ctx.fit_score, ctx.diff_score)
            self._opt.tell(loss)
            self._last_observed_fitness = loss
            self._restart_if_stagnated()

        # 2. Build the optional E-010 hint-bias callback.
        hint_payload = self._build_hint_bias_payload(ctx.analysis)
        bias_callback = hint_payload["callback"]

        # 3. Ask for the next candidate (with bias if enabled).
        proposed = self._opt.ask(bias_callback=bias_callback)
        self._pending_params = proposed
        self._asked_first = True

        return proposed, self._build_decision(ctx, proposed, hint_payload)

    def propose_many(
        self,
        ctx: StrategyContext,
        *,
        count: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Ask CMA-ES for a batch of candidates without consuming ``ctx`` fitness.

        This is the batch-mode counterpart of :meth:`propose`. The caller
        renders and scores every returned candidate, then feeds the scores back
        with :meth:`tell_many_scores`.
        """

        count = int(count)
        if count <= 0:
            raise ValueError("count must be positive")
        if self._initial_design_pending:
            raise RuntimeError(
                "propose_many() cannot run while initial-design candidates "
                "are waiting for tell_many_scores()"
            )
        if self._initial_design_queue:
            design_batch: list[tuple[dict[str, Any], dict[str, Any]]] = []
            batch_size = min(count, len(self._initial_design_queue))
            selected: list[tuple[int, dict[str, Any]]] = []
            for batch_index in range(batch_size):
                selected.append(self._initial_design_queue.pop(0))
            self._initial_design_pending.extend(selected)
            for batch_index, (_index, proposed) in enumerate(selected):
                design_batch.append(
                    (
                        proposed,
                        self._build_initial_design_decision(
                            ctx,
                            proposed,
                            batch_index=batch_index,
                            batch_size=batch_size,
                        ),
                    )
                )
            return design_batch
        if self._pending_params is not None:
            raise RuntimeError(
                "propose_many() cannot run while a single pending candidate "
                "is waiting for the next propose() call"
            )
        if self._opt.pending_count > 0:
            raise RuntimeError(
                "propose_many() cannot run while batch candidates are pending; "
                "call tell_many_scores() first"
            )

        hint_payload = self._build_hint_bias_payload(ctx.analysis)
        proposals = self._opt.ask_many(count, bias_callback=hint_payload["callback"])
        self._asked_first = True
        batch_size = len(proposals)
        return [
            (
                proposed,
                self._build_decision(
                    ctx,
                    proposed,
                    hint_payload,
                    batch_index=index,
                    batch_size=batch_size,
                ),
            )
            for index, proposed in enumerate(proposals)
        ]

    def tell_many_scores(self, score_pairs: Sequence[tuple[float, float]]) -> None:
        """Tell a pending batch back as ``(fit_score, diff_score)`` pairs."""

        if self._initial_design_pending:
            pairs = list(score_pairs)
            if len(pairs) != len(self._initial_design_pending):
                raise RuntimeError(
                    "tell_many_scores() expected "
                    f"{len(self._initial_design_pending)} initial-design score pairs, got {len(pairs)}"
                )
            self._record_initial_design_scores(pairs)
            if not self._initial_design_queue:
                self._activate_initial_design_optimizer()
            return

        if self._pending_params is not None:
            raise RuntimeError(
                "tell_many_scores() cannot consume a single pending candidate; "
                "continue the single-candidate propose() loop instead"
            )
        expected = self._opt.pending_count
        if expected <= 0:
            raise RuntimeError("tell_many_scores() called without pending batch candidates")
        pairs = list(score_pairs)
        if len(pairs) != expected:
            raise RuntimeError(
                f"tell_many_scores() expected {expected} score pairs, got {len(pairs)}"
            )

        losses = [
            self._fit_score_to_loss(float(fit_score), float(diff_score))
            for fit_score, diff_score in pairs
        ]
        self._opt.tell_many(losses)
        self._last_observed_fitness = losses[-1] if losses else self._last_observed_fitness
        self._restart_if_stagnated()

    def _build_initial_design_queue(self, initial_params: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
        if self._initial_design_requested <= 0:
            return []
        queue: list[tuple[int, dict[str, Any]]] = []
        if self._initial_design_include_current:
            queue.append((0, dict(initial_params)))

        sample_count = self._initial_design_requested - len(queue)
        if sample_count <= 0:
            return queue[: self._initial_design_requested]

        import numpy as np  # noqa: WPS433 — CMA-ES path already depends on numpy.

        if self._initial_design_method == "local_coordinate_probe":
            initial_vector = self._encoder.encode(initial_params)
            lower = self._encoder.lower_bounds
            upper = self._encoder.upper_bounds
            seen = {_vector_key(initial_vector)}
            for axis_index in range(self._encoder.dim):
                width = float(upper[axis_index] - lower[axis_index])
                if width <= 0.0:
                    continue
                step = self._initial_design_local_step_ratio * width
                for sign in (1.0, -1.0):
                    vector = initial_vector.copy()
                    vector[axis_index] = float(np.clip(vector[axis_index] + sign * step, lower[axis_index], upper[axis_index]))
                    key = _vector_key(vector)
                    if key in seen:
                        continue
                    seen.add(key)
                    queue.append((len(queue), self._encoder.decode(vector)))
                    if len(queue) >= self._initial_design_requested:
                        return queue[: self._initial_design_requested]
            return queue[: self._initial_design_requested]

        rng = np.random.default_rng(self._config.seed)
        lower = self._encoder.lower_bounds
        upper = self._encoder.upper_bounds
        width = upper - lower
        design = np.empty((sample_count, self._encoder.dim), dtype=np.float64)
        for axis_index in range(self._encoder.dim):
            order = rng.permutation(sample_count)
            design[:, axis_index] = (order + 0.5) / sample_count
        for row_index, unit_row in enumerate(design, start=len(queue)):
            vector = lower + unit_row * width
            queue.append((row_index, self._encoder.decode(vector)))
        return queue[: self._initial_design_requested]

    def _build_initial_design_decision(
        self,
        ctx: StrategyContext,
        proposed: dict[str, Any],
        *,
        batch_index: int | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        cma_info = {
            "warm_started": self._warm_started,
            "warm_start_iters_used": self._history_size_used,
            "population_size": self.population_size,
            "trainable_dim": self.trainable_dim,
            "evaluations": self._opt.evaluations,
            "pending_count": self._opt.pending_count,
            "best_fitness": self._opt.best[1] if self._opt.evaluations > 0 else None,
            "last_loss_fed": self._last_observed_fitness,
            "stagnation": self._stagnation_status(),
            "initial_design": self._initial_design_status(),
        }
        if batch_index is not None and batch_size is not None:
            cma_info["batch"] = {
                "index": int(batch_index),
                "size": int(batch_size),
                "pending_count": len(self._initial_design_pending),
            }
        return {
            "optimizer": self.name,
            "mode": self._config.mode,
            "stage": {
                "name": "cma_initial_design",
                "description": "Space-filling initial design before CMA-ES",
            },
            "iteration_gain": None,
            "score": ctx.diff_score,
            "changes": self._diff_params(ctx.current_params, proposed),
            "stop_reason": "initial_design",
            "cma_es": cma_info,
        }

    def _record_initial_design_scores(self, score_pairs: Sequence[tuple[float, float]]) -> None:
        if len(score_pairs) != len(self._initial_design_pending):
            raise RuntimeError(
                "initial-design score count mismatch: "
                f"{len(score_pairs)} scores for {len(self._initial_design_pending)} pending candidates"
            )
        pending = list(self._initial_design_pending)
        self._initial_design_pending = []
        for (index, params), (fit_score, diff_score) in zip(pending, score_pairs):
            loss = self._fit_score_to_loss(float(fit_score), float(diff_score))
            self._initial_design_results.append(
                {
                    "index": int(index),
                    "params": dict(params),
                    "fit_score": float(fit_score),
                    "diff_score": float(diff_score),
                    "loss": float(loss),
                }
            )

    def _activate_initial_design_optimizer(self) -> None:
        if self._initial_design_activated:
            return
        self._initial_design_activated = True
        if not self._initial_design_results:
            return

        best_result = min(
            self._initial_design_results,
            key=lambda item: float(item.get("loss", math.inf)),
        )
        design_samples = [
            (dict(item["params"]), float(item["loss"]))
            for item in self._initial_design_results
            if isinstance(item.get("params"), dict) and math.isfinite(float(item.get("loss", math.inf)))
        ]
        combined_samples = list(self._base_warm_samples) + design_samples
        combined_samples.sort(key=lambda item: float(item[1]))
        limit = max(int(self._config.warm_start_iters), 0)
        if limit > 0:
            combined_samples = combined_samples[:limit]
        warm_start_samples = combined_samples if len(combined_samples) >= 2 else None
        self._opt = self._new_optimizer(
            warm_start_samples=warm_start_samples,
            initial_mean=dict(best_result["params"]),
        )
        self._warm_started = self._opt.warm_started
        self._history_size_used = len(warm_start_samples or [])
        self._initial_population_size = max(int(self.population_size), 1)
        self._last_observed_fitness = None
        self._pending_params = None
        self._asked_first = False

    def _initial_design_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "enabled": self._initial_design_requested > 0,
            "method": self._initial_design_method,
            "requested_samples": self._initial_design_requested,
            "include_current": self._initial_design_include_current,
            "evaluated_samples": len(self._initial_design_results),
            "pending_samples": len(self._initial_design_pending),
            "remaining_samples": len(self._initial_design_queue),
            "completed": self._initial_design_activated
            and not self._initial_design_queue
            and not self._initial_design_pending,
        }
        if self._initial_design_results:
            best = max(
                self._initial_design_results,
                key=lambda item: float(item.get("fit_score", -math.inf)),
            )
            status["best_fit_score"] = float(best["fit_score"])
            status["best_index"] = int(best["index"])
        if self._initial_design_method == "local_coordinate_probe":
            status["local_step_ratio"] = self._initial_design_local_step_ratio
        return status

    def _build_decision(
        self,
        ctx: StrategyContext,
        proposed: dict[str, Any],
        hint_payload: dict[str, Any],
        *,
        batch_index: int | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        changes = self._diff_params(ctx.current_params, proposed)
        cma_info: dict[str, Any] = {
            "warm_started": self._warm_started,
            "warm_start_iters_used": self._history_size_used,
            "population_size": self.population_size,
            "trainable_dim": self.trainable_dim,
            "evaluations": self._opt.evaluations,
            "pending_count": self._opt.pending_count,
            "best_fitness": self._opt.best[1] if self._opt.evaluations > 0 else None,
            "last_loss_fed": self._last_observed_fitness,
            "stagnation": self._stagnation_status(),
            "restarts": {
                "count": self._restart_count,
                "max": self._max_restarts,
                "last_reason": self._last_restart_reason,
                "last_evaluation": self._last_restart_evaluation,
                "population_size": self.population_size,
                "center_mode": self._restart_center_mode,
                "last_center_mode": self._last_restart_center_mode,
                "last_center_distance_norm": self._last_restart_center_distance_norm,
                "population_multiplier": self._restart_population_multiplier,
                "population_schedule": self._restart_population_schedule,
                "max_population_size": self._restart_max_population_size,
                "stop_after_max": self._stagnation_stop_after_restarts,
            },
            "hint_bias": {
                "mix_ratio": self._config.hint_bias_mix_ratio,
                "applied": hint_payload["applied"],
                "n_axes_biased": hint_payload["n_axes_biased"],
                "max_abs_delta": hint_payload["max_abs_delta"],
                "channels_used": hint_payload["channels_used"],
            },
            "initial_design": self._initial_design_status(),
        }
        if batch_index is not None and batch_size is not None:
            cma_info["batch"] = {
                "index": int(batch_index),
                "size": int(batch_size),
                "pending_count": self._opt.pending_count,
            }

        return {
            "optimizer": self.name,
            "mode": self._config.mode,
            "stage": {
                "name": f"cma_{self._config.mode}",
                "description": "Black-box CMA-ES proposal",
            },
            "iteration_gain": None,
            "score": ctx.diff_score,
            "changes": changes,
            "stop_reason": self.stop_reason() or ("continue" if changes else "no_effective_change"),
            "cma_es": cma_info,
        }

    @property
    def _max_restarts(self) -> int:
        return max(int(self._config.stagnation_max_restarts), 0)

    def _restart_if_stagnated(self) -> bool:
        if self._restart_count >= self._max_restarts:
            return False
        status = self._stagnation_status()
        if not status["plateau"]:
            return False
        self._restart_count += 1
        seed = int(self._config.seed) + self._restart_count if self._config.seed is not None else None
        restart_center = self._restart_initial_mean(seed=seed)
        self._opt.restart(
            initial_mean=restart_center,
            seed=seed,
            population_size=self._next_restart_population_size(),
        )
        self._last_restart_evaluation = self._opt.evaluations
        self._last_restart_reason = "cmaes_stagnation"
        return True

    @property
    def _restart_center_mode(self) -> str:
        return _normalize_restart_center_mode(self._config.restart_center_mode)

    def _effective_restart_center_mode(self) -> str:
        mode = self._restart_center_mode
        if mode != "alternate":
            return mode
        return "best" if self._restart_count % 2 == 1 else "random"

    def _restart_initial_mean(self, *, seed: int | None) -> Any:
        best_params, _best_loss = self._opt.best
        effective_mode = self._effective_restart_center_mode()
        if effective_mode != "random":
            self._last_restart_center_mode = "best"
            self._last_restart_center_distance_norm = 0.0
            return best_params

        import numpy as np  # noqa: WPS433 — CMA-ES path already depends on numpy.

        rng = np.random.default_rng(seed)
        lower = self._encoder.lower_bounds
        upper = self._encoder.upper_bounds
        restart_vector = rng.uniform(lower, upper)
        reference = self._encoder.encode(best_params) if best_params is not None else self._encoder.initial_vector
        width = np.where((upper - lower) > 0.0, upper - lower, 1.0)
        distance = np.sqrt(np.mean(np.square((restart_vector - reference) / width)))
        self._last_restart_center_mode = "random"
        self._last_restart_center_distance_norm = float(distance)
        return restart_vector

    @property
    def _restart_population_multiplier(self) -> float:
        value = float(self._config.restart_population_multiplier)
        if not math.isfinite(value) or value < 1.0:
            return 1.0
        return value

    @property
    def _restart_max_population_size(self) -> int | None:
        value = self._config.restart_max_population_size
        if value is None:
            return None
        return max(int(value), 1)

    @property
    def _restart_population_schedule(self) -> str:
        return _normalize_restart_population_schedule(self._config.restart_population_schedule)

    @property
    def _stagnation_stop_after_restarts(self) -> bool:
        return bool(self._config.stagnation_stop_after_restarts)

    def _next_restart_population_size(self) -> int:
        if self._restart_population_schedule == "bipop":
            proposed = self._next_bipop_population_size()
        else:
            current = max(int(self.population_size), 1)
            proposed = max(int(math.ceil(current * self._restart_population_multiplier)), current)
        max_population = self._restart_max_population_size
        if max_population is not None:
            proposed = min(proposed, max_population)
        return max(proposed, 1)

    def _next_bipop_population_size(self) -> int:
        base = max(int(self._initial_population_size), 1)
        if self._restart_count % 2 == 0:
            return base
        large_restart_index = (self._restart_count + 1) // 2
        multiplier = self._restart_population_multiplier ** large_restart_index
        return max(int(math.ceil(base * multiplier)), base)

    def _stagnation_status(self) -> dict[str, Any]:
        patience = max(int(self._config.stagnation_patience), 0)
        min_evaluations = max(int(self._config.stagnation_min_evaluations), 0)
        min_delta = float(self._config.stagnation_min_delta)
        if not math.isfinite(min_delta) or min_delta < 0.0:
            min_delta = 0.0
        evaluations = int(self._opt.evaluations)
        evaluations_since_restart = max(0, evaluations - self._last_restart_evaluation)
        status: dict[str, Any] = {
            "active": patience > 0,
            "patience": patience,
            "min_delta": min_delta,
            "min_evaluations": min_evaluations,
            "evaluations": evaluations,
            "evaluations_since_restart": evaluations_since_restart,
            "plateau": False,
            "best_fit_score": None,
            "reference_fit_score": None,
            "window_best_fit_score": None,
        }
        if patience <= 0:
            return status
        losses = self._opt.loss_history()[self._last_restart_evaluation :]
        fit_scores = [1.0 - float(loss) for loss in losses]
        if fit_scores:
            status["best_fit_score"] = max(fit_scores)
        if evaluations_since_restart < min_evaluations or len(fit_scores) < patience:
            return status

        window = fit_scores[-patience:]
        previous = fit_scores[:-patience]
        reference = max(previous) if previous else window[0]
        window_best = max(window)
        status["reference_fit_score"] = reference
        status["window_best_fit_score"] = window_best
        status["plateau"] = window_best <= reference + min_delta
        return status

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

        Algorithm:

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
