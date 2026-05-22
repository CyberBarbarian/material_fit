"""Candidate queue for the P1 breakthrough phase."""

from __future__ import annotations

from itertools import combinations
from typing import Any, Sequence

from .search_evidence import TopKArchive
from .subspace_batch import SubspaceBatchGenerator


class BreakthroughCandidateQueue:
    """Build a small, evidence-ranked candidate queue on demand."""

    def __init__(self, max_size: int = 10) -> None:
        self.max_size = max(1, int(max_size))
        self._queue: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self._seen_signatures: set[str] = set()
        self.generated_count = 0
        self.archive_restart_count = 0
        self.color_joint_generated_count = 0
        self.subspace_batch_generated_count = 0
        self._subspace_batch = SubspaceBatchGenerator(max_params=6, max_candidates=8)

    def pop(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def ensure(
        self,
        *,
        base_params: dict[str, Any],
        base_fit_score: float,
        analysis: dict[str, Any],
        iteration: int,
        group_cycle: int,
        groups_by_name: dict[str, Any],
        group_order: Sequence[str],
        group_scores: dict[str, float],
        active_groups: set[str],
        bottleneck: dict[str, float],
        archive: TopKArchive,
        generator: Any,
        param_agenda: Sequence[dict[str, Any]] = (),
        radius_scale: float = 1.0,
    ) -> None:
        if self._queue:
            return
        ranked = [
            name
            for name, score in sorted(group_scores.items(), key=lambda item: item[1], reverse=True)
            if name in active_groups and score > 0.0 and name in groups_by_name
        ]
        if not ranked:
            ranked = [name for name in group_order if name in active_groups and name in groups_by_name]

        self._add_archive_restart(
            base_params=base_params,
            bottleneck=bottleneck,
            archive=archive,
            base_fit_score=base_fit_score,
        )
        self._add_subspace_batch_population(
            base_params=base_params,
            param_agenda=param_agenda,
            iteration=iteration,
            group_cycle=group_cycle,
            generator=generator,
            radius_scale=radius_scale,
        )
        self._add_param_agenda_population(
            base_params=base_params,
            param_agenda=param_agenda,
            iteration=iteration,
            group_cycle=group_cycle,
            generator=generator,
            radius_scale=radius_scale,
        )
        self._add_local_population(
            base_params=base_params,
            analysis=analysis,
            iteration=iteration,
            group_cycle=group_cycle,
            groups=[groups_by_name[name] for name in ranked[:4]],
            generator=generator,
            radius_scale=radius_scale,
        )
        self._add_cross_group_population(
            base_params=base_params,
            base_fit_score=base_fit_score,
            analysis=analysis,
            iteration=iteration,
            group_cycle=group_cycle,
            groups=[groups_by_name[name] for name in ranked[:4]],
            generator=generator,
            radius_scale=radius_scale,
        )
        self.generated_count += len(self._queue)
        del self._queue[self.max_size :]

    def summary(self) -> dict[str, Any]:
        return {
            "pending": len(self._queue),
            "generated_count": self.generated_count,
            "archive_restart_count": self.archive_restart_count,
            "color_joint_generated_count": self.color_joint_generated_count,
            "subspace_batch_generated_count": self.subspace_batch_generated_count,
            "max_size": self.max_size,
        }

    def _add_archive_restart(
        self,
        *,
        base_params: dict[str, Any],
        bottleneck: dict[str, float],
        archive: TopKArchive,
        base_fit_score: float,
    ) -> None:
        restart = archive.select_restart(
            bottleneck=bottleneck,
            current_params=base_params,
            min_fit_score=max(base_fit_score - 0.04, 0.0),
        )
        if not restart or not restart.get("params") or restart.get("params") == base_params:
            return
        appended = self._append_unique(
            base_params,
            dict(restart["params"]),
            {
                "candidate_kind": "archive_restart",
                "changed_params": [],
                "archive_restart": {
                    key: value
                    for key, value in restart.items()
                    if key != "params"
                },
            },
        )
        if appended:
            self.archive_restart_count += 1

    def _add_local_population(
        self,
        *,
        base_params: dict[str, Any],
        analysis: dict[str, Any],
        iteration: int,
        group_cycle: int,
        groups: Sequence[Any],
        generator: Any,
        radius_scale: float,
    ) -> None:
        radius_scale = max(0.10, min(2.0, float(radius_scale)))
        for group in groups:
            for axis_offset, direction in ((0, None), (0, -1.0), (1, 1.0), (1, -1.0)):
                result = generator.nudge_group_candidate(
                    base_params=base_params,
                    group=group,
                    analysis=analysis,
                    step_scale=0.22 * radius_scale,
                    group_cycle=group_cycle,
                    axis_offset=axis_offset,
                    direction_override=direction,
                )
                if result is None:
                    continue
                proposed, payload = result
                payload.update(
                    {
                        "candidate_kind": "local_population",
                        "iteration": iteration,
                    }
                )
                self._append_unique(base_params, proposed, payload)
                if len(self._queue) >= self.max_size:
                    return

    def _add_param_agenda_population(
        self,
        *,
        base_params: dict[str, Any],
        param_agenda: Sequence[dict[str, Any]],
        iteration: int,
        group_cycle: int,
        generator: Any,
        radius_scale: float,
    ) -> None:
        radius_scale = max(0.10, min(2.0, float(radius_scale)))
        for item in list(param_agenda)[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("param") or "")
            if not name or name not in base_params:
                continue
            axis_offsets = [0]
            if isinstance(base_params.get(name), list):
                axis_offsets.append(1)
            for axis_offset in axis_offsets:
                for direction in (1.0, -1.0):
                    result = generator.nudge_param_candidate(
                        base_params=base_params,
                        param_name=name,
                        step_scale=0.24 * radius_scale,
                        group_cycle=group_cycle,
                        axis_offset=axis_offset,
                        direction_override=direction,
                    )
                    if result is None:
                        continue
                    proposed, payload = result
                    payload.update(
                        {
                            "candidate_kind": "param_agenda_population",
                            "priority": item.get("priority"),
                            "semantic_relevance": item.get("semantic_relevance"),
                            "iteration": iteration,
                            "radius_scale": radius_scale,
                        }
                    )
                    self._append_unique(base_params, proposed, payload)
                    if len(self._queue) >= self.max_size:
                        return

    def _add_subspace_batch_population(
        self,
        *,
        base_params: dict[str, Any],
        param_agenda: Sequence[dict[str, Any]],
        iteration: int,
        group_cycle: int,
        generator: Any,
        radius_scale: float,
    ) -> None:
        candidates = self._subspace_batch.generate(
            base_params=base_params,
            param_agenda=param_agenda,
            generator=generator,
            group_cycle=group_cycle,
            radius_scale=radius_scale,
            iteration=iteration,
        )
        for proposed, payload in candidates:
            if self._append_unique(base_params, proposed, payload):
                self.subspace_batch_generated_count += 1
            if len(self._queue) >= self.max_size:
                return

    def _add_cross_group_population(
        self,
        *,
        base_params: dict[str, Any],
        base_fit_score: float,
        analysis: dict[str, Any],
        iteration: int,
        group_cycle: int,
        groups: Sequence[Any],
        generator: Any,
        radius_scale: float,
    ) -> None:
        radius_scale = max(0.10, min(2.0, float(radius_scale)))
        for size in (2, 3):
            for combo in combinations(groups, size):
                result = generator.cross_group_candidate(
                    base_params=base_params,
                    groups=list(combo),
                    group_cycle=group_cycle,
                    analysis=analysis,
                    base_fit_score=base_fit_score,
                    iteration=iteration,
                    step_scale=0.35 * radius_scale,
                )
                if result is None:
                    continue
                proposed, payload = result
                payload["candidate_kind"] = "cross_group_population"
                self._append_unique(base_params, proposed, payload)
                if len(self._queue) >= self.max_size:
                    return

    def _append_unique(self, base_params: dict[str, Any], proposed: dict[str, Any], payload: dict[str, Any]) -> bool:
        if proposed == base_params:
            return False
        signature = _candidate_signature(proposed)
        if signature in self._seen_signatures:
            return False
        if any(existing == proposed for existing, _ in self._queue):
            return False
        self._seen_signatures.add(signature)
        self._queue.append((proposed, payload))
        return True

def _candidate_signature(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(params):
        value = params[key]
        if isinstance(value, float):
            encoded = f"{value:.8g}"
        elif isinstance(value, list):
            encoded = "[" + ",".join(f"{item:.8g}" if isinstance(item, float) else str(item) for item in value) + "]"
        else:
            encoded = str(value)
        parts.append(f"{key}={encoded}")
    return "|".join(parts)


__all__ = ["BreakthroughCandidateQueue"]
