"""Expensive subspace CMA-ES strategy for effect-first comparison runs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .candidate_builder import diff_params
from .cma_es_optimizer import CmaesConfig, CmaesOptimizer, ParameterEncoder
from .semantic_graph import ShaderEffectGraph


@dataclass
class _SubspaceState:
    subspace_id: str
    reason: str
    params: list[str]
    encoder: ParameterEncoder
    optimizer: CmaesOptimizer
    archive: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    best_history: list[tuple[int, float]] = field(default_factory=list)
    last_loss: float | None = None
    last_fit_score: float | None = None
    restart_count: int = 0
    switch_in_count: int = 0
    last_restart_reason: str = "initial"


class SubspaceCmaEsStrategy:
    """Run CMA-ES inside a compact semantic/metric subspace."""

    name = "subspace_cma_es"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        graph: ShaderEffectGraph,
        population_size: int | None = None,
        sigma: float | None = None,
        seed: int | None = None,
        max_axes: int = 10,
    ) -> None:
        self._initial_params = dict(initial_params)
        self._shader_params = list(shader_params)
        self._graph = graph
        self._max_axes = max(2, int(max_axes))
        self._config = CmaesConfig(
            population_size=population_size,
            sigma=float(sigma) if sigma is not None else 0.22,
            seed=seed,
        )
        self._states: dict[str, _SubspaceState] = {}
        self._subspace_order: list[str] = []
        self._active_subspace_id: str | None = None
        self._pending_params: dict[str, Any] | None = None
        self._global_archive: list[tuple[float, dict[str, Any]]] = []
        self._global_best_params: dict[str, Any] | None = None
        self._global_best_fit_score = -math.inf
        self._total_evaluations = 0
        self._switch_count = 0
        self._min_generations_per_subspace = 6
        self._plateau_generations = 4
        self._plateau_fit_epsilon = 0.003
        self._max_generations_per_subspace = 16

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        state = self._active_state()
        if state is not None and state.optimizer.should_stop():
            return "subspace_cma_should_stop"
        return None

    def research_summary(self) -> dict[str, Any]:
        state = self._active_state()
        best_params, best_loss = (
            state.optimizer.best if state is not None else (None, math.inf)
        )
        best_fit_score = (1.0 - best_loss) if math.isfinite(float(best_loss)) else None
        return {
            "phase": "subspace_cma",
            "subspace_id": state.subspace_id if state is not None else None,
            "subspace_reason": state.reason if state is not None else None,
            "subspace_params": list(state.params) if state is not None else [],
            "subspace_count": len(self._states),
            "subspace_order": list(self._subspace_order),
            "trainable_dim": state.encoder.dim if state is not None else 0,
            "population_size": state.optimizer.population_size if state is not None else None,
            "evaluations": state.optimizer.evaluations if state is not None else 0,
            "total_evaluations": self._total_evaluations,
            "generation": self._generation(),
            "population_index": self._population_index(),
            "sigma": self._config.sigma,
            "restart_count": state.restart_count if state is not None else 0,
            "switch_count": self._switch_count,
            "archive_size": len(state.archive) if state is not None else 0,
            "global_archive_size": len(self._global_archive),
            "global_best_fit_score": self._global_best_score_json(),
            "best_loss": best_loss if math.isfinite(float(best_loss)) else None,
            "best_fit_score_in_subspace": best_fit_score,
            "has_best_params": best_params is not None,
        }

    def propose(self, ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe_run_best(ctx)
        if not self._states:
            self._initialize_subspaces(ctx.current_params, ctx.analysis)
        state = self._active_state()
        if state is None:
            return ctx.current_params, {
                "optimizer": self.name,
                "stage": None,
                "stop_reason": "no_subspace_axes",
                "changes": [],
            }
        if self._pending_params is not None:
            loss = self._fit_score_to_loss(ctx.fit_score, ctx.diff_score)
            state.optimizer.tell(loss)
            self._total_evaluations += 1
            self._record_archive(state, self._pending_params, loss)
            self._record_global_archive(self._pending_params, loss)
            self._remember_best(state)
            state.last_loss = loss
            state.last_fit_score = float(ctx.fit_score)
            self._pending_params = None
            restart_reason = self._restart_reason(state)
            if restart_reason:
                state = self._switch_or_restart(ctx.current_params, ctx.analysis, state, restart_reason)
            if state is None:
                return ctx.current_params, {
                    "optimizer": self.name,
                    "stage": None,
                    "stop_reason": "subspace_cma_restart_failed",
                    "changes": [],
                }

        raw_candidate = state.optimizer.ask()
        proposal_center = self._proposal_center(ctx.current_params)
        proposed = self._merge_subspace_candidate(proposal_center, raw_candidate, state.params)
        self._pending_params = proposed
        changes = diff_params(ctx.current_params, proposed)
        return proposed, {
            "optimizer": self.name,
            "stage": {
                "name": "subspace_cma_es",
                "description": "CMA-ES inside response/semantic active subspace",
            },
            "semantic_action": "subspace_cma_candidate",
            "changes": changes,
            "stop_reason": self.stop_reason()
            or ("continue" if changes else "no_effective_change"),
            "subspace_cma_es": {
                "subspace_id": state.subspace_id,
                "subspace_reason": state.reason,
                "subspace_params": list(state.params),
                "subspace_count": len(self._states),
                "subspace_order": list(self._subspace_order),
                "trainable_dim": state.encoder.dim,
                "population_size": state.optimizer.population_size,
                "evaluations": state.optimizer.evaluations,
                "total_evaluations": self._total_evaluations,
                "generation": self._generation(),
                "population_index": self._population_index(),
                "sigma": self._config.sigma,
                "restart_count": state.restart_count,
                "switch_count": self._switch_count,
                "switch_in_count": state.switch_in_count,
                "archive_size": len(state.archive),
                "global_archive_size": len(self._global_archive),
                "global_best_fit_score": self._global_best_score_json(),
                "proposal_center": "global_best_or_elite",
                "last_restart_reason": state.last_restart_reason,
                "subspace_age_generations": self._generation(state),
                "last_loss_fed": state.last_loss,
                "last_fit_score": state.last_fit_score,
                "best": self._best_summary(),
            },
        }

    def _initialize_subspaces(self, current_params: dict[str, Any], analysis: dict[str, Any]) -> None:
        candidates = self._build_subspace_specs(current_params, analysis)
        for subspace_id, reason, params in candidates:
            self._ensure_state(subspace_id, reason, params, current_params)
        if self._subspace_order:
            self._active_subspace_id = self._subspace_order[0]
            state = self._active_state()
            if state is not None:
                state.switch_in_count += 1

    def _build_subspace_specs(
        self,
        current_params: dict[str, Any],
        analysis: dict[str, Any],
    ) -> list[tuple[str, str, list[str]]]:
        candidates = [
            name for name in self._graph.active_search_params_for(current_params)
            if name in current_params
        ]
        bottleneck = self._metric_bottleneck(analysis)
        candidates.sort(key=lambda name: self._semantic_relevance(name, bottleneck), reverse=True)
        if not candidates:
            return []
        specs: list[tuple[str, str, list[str]]] = []
        top = self._fit_params_to_axis_budget(candidates, current_params)
        if top:
            specs.append((
                "top_bottleneck",
                "top active params by current metric bottleneck relevance",
                top,
            ))
        seen_groups: set[str] = set()
        for group in self._graph.groups.values():
            group_params = [
                name for name in (group.search_params or group.params)
                if name in candidates and name not in seen_groups
            ]
            fitted = self._fit_params_to_axis_budget(group_params, current_params)
            if fitted:
                specs.append((
                    f"group:{group.name}",
                    f"semantic group {group.name}",
                    fitted,
                ))
                seen_groups.update(fitted)
        role_buckets = {
            "color_grade": ("color", "saturation", "hue", "gamma", "texpower"),
            "shadow_luma": ("shadow", "ao", "contrast", "power"),
            "specular_reflect": (
                "specular",
                "smooth",
                "reflect",
                "matcap",
                "fresnel",
                "rim",
            ),
        }
        for bucket, tokens in role_buckets.items():
            bucket_params = [
                name for name in candidates
                if self._name_matches(name, tokens)
            ]
            fitted = self._fit_params_to_axis_budget(bucket_params, current_params)
            if fitted:
                specs.append((
                    f"role:{bucket}",
                    f"role bucket {bucket}",
                    fitted,
                ))
        deduped: list[tuple[str, str, list[str]]] = []
        seen_param_sets: set[tuple[str, ...]] = set()
        for subspace_id, reason, params in specs:
            key = tuple(params)
            if key in seen_param_sets:
                continue
            seen_param_sets.add(key)
            deduped.append((subspace_id, reason, params))
        return deduped

    def _fit_params_to_axis_budget(self, params: Sequence[str], current_params: dict[str, Any]) -> list[str]:
        selected: list[str] = []
        best_selected: list[str] = []
        for name in params:
            if name in selected:
                continue
            selected.append(name)
            encoder = ParameterEncoder(
                current_params,
                self._shader_params,
                param_whitelist=selected,
                semantics=self._graph,
            )
            if encoder.dim > self._max_axes:
                selected.pop()
                break
            if encoder.dim > 0:
                best_selected = list(selected)
            if encoder.dim >= self._max_axes:
                break
        return best_selected

    def _ensure_state(
        self,
        subspace_id: str,
        reason: str,
        params: list[str],
        current_params: dict[str, Any],
        *,
        restart: bool = False,
        restart_reason: str = "",
    ) -> _SubspaceState | None:
        if subspace_id in self._states and not restart:
            return self._states[subspace_id]
        encoder = ParameterEncoder(
            current_params,
            self._shader_params,
            param_whitelist=params,
            semantics=self._graph,
        )
        if encoder.dim <= 0:
            return None
        previous = self._states.get(subspace_id)
        state = _SubspaceState(
            subspace_id=subspace_id,
            reason=reason,
            params=list(params),
            encoder=encoder,
            optimizer=CmaesOptimizer(
                encoder,
                config=self._config,
                initial_mean=current_params,
            ),
            archive=list(previous.archive) if previous is not None else [],
            restart_count=(previous.restart_count + 1) if previous is not None else 0,
            switch_in_count=previous.switch_in_count if previous is not None else 0,
            last_restart_reason=restart_reason or ("restart" if restart else "initial"),
        )
        self._states[subspace_id] = state
        if subspace_id not in self._subspace_order:
            self._subspace_order.append(subspace_id)
        return state

    def _switch_or_restart(
        self,
        current_params: dict[str, Any],
        analysis: dict[str, Any],
        state: _SubspaceState,
        reason: str,
    ) -> _SubspaceState | None:
        if reason == "cma_should_stop":
            center = self._restart_center(state, current_params)
            state = self._ensure_state(
                state.subspace_id,
                state.reason,
                state.params,
                center,
                restart=True,
                restart_reason=reason,
            ) or state
            self._active_subspace_id = state.subspace_id
            return state
        if len(self._subspace_order) <= 1:
            center = self._restart_center(state, current_params)
            state = self._ensure_state(
                state.subspace_id,
                state.reason,
                state.params,
                center,
                restart=True,
                restart_reason=reason,
            ) or state
            self._active_subspace_id = state.subspace_id
            return state
        current_idx = self._subspace_order.index(state.subspace_id)
        next_id = self._subspace_order[(current_idx + 1) % len(self._subspace_order)]
        next_state = self._states.get(next_id)
        if next_state is None:
            self._initialize_subspaces(current_params, analysis)
            next_state = self._states.get(next_id)
        if next_state is None:
            return None
        if self._should_elite_restart_on_switch(next_state):
            center = self._restart_center(next_state, current_params)
            next_state = self._ensure_state(
                next_state.subspace_id,
                next_state.reason,
                next_state.params,
                center,
                restart=True,
                restart_reason=f"elite_center_after:{reason}",
            ) or next_state
        self._active_subspace_id = next_id
        self._switch_count += 1
        next_state.switch_in_count += 1
        next_state.last_restart_reason = f"switched_from:{state.subspace_id}:{reason}"
        return next_state

    def _active_state(self) -> _SubspaceState | None:
        if self._active_subspace_id is None:
            return None
        return self._states.get(self._active_subspace_id)

    def _generation(self, state: _SubspaceState | None = None) -> int:
        state = state or self._active_state()
        if state is None:
            return 0
        population_size = max(state.optimizer.population_size, 1)
        return int(state.optimizer.evaluations // population_size)

    def _population_index(self, state: _SubspaceState | None = None) -> int:
        state = state or self._active_state()
        if state is None:
            return 0
        population_size = max(state.optimizer.population_size, 1)
        return int(state.optimizer.evaluations % population_size)

    def _best_summary(self) -> dict[str, Any]:
        state = self._active_state()
        if state is None:
            return {"loss": None, "fit_score": None, "has_params": False}
        best_params, best_loss = state.optimizer.best
        if not math.isfinite(float(best_loss)):
            return {"loss": None, "fit_score": None, "has_params": best_params is not None}
        return {
            "loss": float(best_loss),
            "fit_score": 1.0 - float(best_loss),
            "has_params": best_params is not None,
        }

    def _global_best_score_json(self) -> float | None:
        if math.isfinite(self._global_best_fit_score):
            return self._global_best_fit_score
        return None

    def _record_archive(self, state: _SubspaceState, params: dict[str, Any] | None, loss: float) -> None:
        if params is None or not math.isfinite(float(loss)):
            return
        state.archive.append((float(loss), dict(params)))
        state.archive.sort(key=lambda item: item[0])
        del state.archive[8:]

    def _record_global_archive(self, params: dict[str, Any] | None, loss: float) -> None:
        if params is None or not math.isfinite(float(loss)):
            return
        self._global_archive.append((float(loss), dict(params)))
        self._global_archive.sort(key=lambda item: item[0])
        del self._global_archive[16:]
        fit_score = 1.0 - float(loss)
        if fit_score > self._global_best_fit_score:
            self._global_best_fit_score = fit_score
            self._global_best_params = dict(params)

    def _archive_center(self, state: _SubspaceState, fallback: dict[str, Any]) -> dict[str, Any]:
        if state.archive:
            return dict(state.archive[0][1])
        return dict(fallback)

    def _restart_center(self, state: _SubspaceState, fallback: dict[str, Any]) -> dict[str, Any]:
        if self._global_best_params:
            return dict(self._global_best_params)
        if self._global_archive:
            return dict(self._global_archive[0][1])
        return self._archive_center(state, fallback)

    def _proposal_center(self, fallback: dict[str, Any]) -> dict[str, Any]:
        if self._global_best_params:
            return dict(self._global_best_params)
        if self._global_archive:
            return dict(self._global_archive[0][1])
        return dict(fallback)

    def _observe_run_best(self, ctx: Any) -> None:
        state_obj = getattr(ctx, "state", None)
        best_params = getattr(state_obj, "best_fit_params", None) or getattr(state_obj, "best_params", None)
        best_score = getattr(state_obj, "best_fit_score", None)
        if (
            isinstance(best_params, dict)
            and isinstance(best_score, (int, float))
            and math.isfinite(float(best_score))
        ):
            loss = self._fit_score_to_loss(float(best_score), 0.0)
            self._record_global_archive(best_params, loss)
        elif (
            isinstance(getattr(ctx, "current_params", None), dict)
            and isinstance(getattr(ctx, "fit_score", None), (int, float))
        ):
            diff_score = float(getattr(ctx, "diff_score", 0.0) or 0.0)
            loss = self._fit_score_to_loss(float(ctx.fit_score), diff_score)
            self._record_global_archive(ctx.current_params, loss)

    def _should_elite_restart_on_switch(self, state: _SubspaceState) -> bool:
        if not self._global_best_params:
            return False
        if state.optimizer.evaluations == 0:
            return True
        _, state_best_loss = state.optimizer.best
        if not math.isfinite(float(state_best_loss)):
            return True
        return (1.0 - float(state_best_loss)) + 0.01 < self._global_best_fit_score

    def _remember_best(self, state: _SubspaceState) -> None:
        _, best_loss = state.optimizer.best
        if not math.isfinite(float(best_loss)):
            return
        state.best_history.append((self._generation(state), 1.0 - float(best_loss)))
        if len(state.best_history) > 32:
            del state.best_history[: len(state.best_history) - 32]

    def _restart_reason(self, state: _SubspaceState) -> str | None:
        generation = self._generation(state)
        if state.optimizer.should_stop():
            return "cma_should_stop"
        if generation < self._min_generations_per_subspace:
            return None
        if generation >= self._max_generations_per_subspace:
            return "max_generations"
        history = state.best_history
        if len(history) >= self._plateau_generations:
            oldest = history[-self._plateau_generations][1]
            latest = history[-1][1]
            if latest - oldest < self._plateau_fit_epsilon:
                return "plateau"
        return None

    @staticmethod
    def _merge_subspace_candidate(
        current_params: dict[str, Any],
        raw_candidate: dict[str, Any],
        subspace_params: Sequence[str],
    ) -> dict[str, Any]:
        proposed = dict(current_params)
        for name in subspace_params:
            if name in raw_candidate:
                value = raw_candidate[name]
                proposed[name] = list(value) if isinstance(value, list) else value
        return proposed

    def _name_matches(self, name: str, tokens: Sequence[str]) -> bool:
        sem = self._graph.params.get(name)
        text = " ".join([
            name,
            str(getattr(sem, "group", "")),
            str(getattr(sem, "role", "")),
            str(getattr(sem, "transform", "")),
        ]).lower()
        return any(token in text for token in tokens)

    @staticmethod
    def _fit_score_to_loss(fit_score: float, diff_score: float) -> float:
        if math.isfinite(float(fit_score)):
            return max(0.0, 1.0 - float(fit_score))
        if math.isfinite(float(diff_score)):
            return max(0.0, float(diff_score))
        return 0.5

    @staticmethod
    def _metric_bottleneck(analysis: dict[str, Any]) -> dict[str, float]:
        metrics = analysis.get("research_metrics") if isinstance(analysis, dict) else None
        components = metrics.get("components") if isinstance(metrics, dict) else None
        if not isinstance(components, dict):
            return {}
        rows = [
            (str(key), float(value))
            for key, value in components.items()
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            )
        ]
        rows.sort(key=lambda item: item[1], reverse=True)
        return {key: value for key, value in rows[:4] if value > 0.0}

    def _semantic_relevance(
        self,
        param_name: str,
        bottleneck: dict[str, float],
    ) -> float:
        sem = self._graph.params.get(param_name)
        text = " ".join([
            param_name,
            str(getattr(sem, "group", "")),
            str(getattr(sem, "role", "")),
            str(getattr(sem, "transform", "")),
        ]).lower()
        keys = set(bottleneck)
        score = 0.0
        if keys & {"color_mean", "color_p95"} and any(
            token in text
            for token in (
                "color",
                "saturation",
                "hue",
                "gamma",
                "texpower",
                "reflect",
                "shadow",
            )
        ):
            score += 0.055
        if keys & {"luminance_mae", "luminance_bias"} and any(
            token in text
            for token in (
                "gamma",
                "power",
                "intensity",
                "shadow",
                "ao",
                "contrast",
                "reflect",
            )
        ):
            score += 0.045
        if keys & {"highlight"} and any(
            token in text
            for token in (
                "specular",
                "smooth",
                "threshold",
                "shadow",
                "rim",
                "fresnel",
                "reflect",
            )
        ):
            score += 0.055
        if keys & {"structure_ssim_l", "detail_texture"} and any(
            token in text
            for token in (
                "normal",
                "smooth",
                "threshold",
                "specular",
                "shadow",
                "power",
            )
        ):
            score += 0.045
        return score


__all__ = ["SubspaceCmaEsStrategy"]
