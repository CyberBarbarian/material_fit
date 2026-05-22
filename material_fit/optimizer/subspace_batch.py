"""Low-dimensional subspace candidate generation for plateau search.

The goal is to test coordinated parameter moves without the old coarse
``color_joint_population`` behavior that changed many hand-picked color
parameters at once.  This module keeps the policy small and deterministic:
select a few high-priority params, generate low-discrepancy +/- directions,
and let the existing real-render loop evaluate candidates one by one.
"""

from __future__ import annotations

from typing import Any, Sequence


class SubspaceBatchGenerator:
    """Generate small trust-region candidates from a ranked param agenda."""

    def __init__(self, max_params: int = 6, max_candidates: int = 10) -> None:
        self.max_params = max(2, int(max_params))
        self.max_candidates = max(1, int(max_candidates))

    def generate(
        self,
        *,
        base_params: dict[str, Any],
        param_agenda: Sequence[dict[str, Any]],
        generator: Any,
        group_cycle: int,
        radius_scale: float,
        iteration: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        names = self._select_param_names(base_params, param_agenda)
        if len(names) < 2:
            return []
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        radius_scale = max(0.10, min(1.20, float(radius_scale)))
        for candidate_index, directions in enumerate(self._direction_rows(len(names))):
            candidate = dict(base_params)
            axes: list[dict[str, Any]] = []
            changed: list[str] = []
            # Keep each candidate sparse enough for attribution while still
            # allowing non-separable moves.
            active_slots = [idx for idx, direction in enumerate(directions) if direction != 0][:4]
            if len(active_slots) < 2:
                continue
            for idx in active_slots:
                name = names[idx]
                result = generator.nudge_param_candidate(
                    base_params=candidate,
                    param_name=name,
                    step_scale=0.16 * radius_scale,
                    group_cycle=group_cycle,
                    axis_offset=0,
                    direction_override=float(directions[idx]),
                )
                if result is None:
                    continue
                candidate, payload = result
                axes.append(payload)
                changed.extend(str(item) for item in payload.get("changed_params", []) if item)
            unique_changed = sorted(set(changed))
            if len(unique_changed) < 2 or candidate == base_params:
                continue
            out.append(
                (
                    candidate,
                    {
                        "candidate_kind": "subspace_batch",
                        "changed_params": unique_changed,
                        "subspace_params": names,
                        "subspace_directions": list(directions),
                        "subspace_candidate_index": candidate_index,
                        "iteration": iteration,
                        "radius_scale": radius_scale,
                        "axes": axes,
                    },
                )
            )
            if len(out) >= self.max_candidates:
                break
        return out

    def _select_param_names(self, base_params: dict[str, Any], param_agenda: Sequence[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        groups: dict[str, int] = {}
        for item in param_agenda:
            if not isinstance(item, dict):
                continue
            name = str(item.get("param") or "")
            if not name or name in names or name not in base_params:
                continue
            group = str(item.get("group") or "")
            if groups.get(group, 0) >= 2:
                continue
            names.append(name)
            groups[group] = groups.get(group, 0) + 1
            if len(names) >= self.max_params:
                break
        return names

    def _direction_rows(self, dim: int) -> list[tuple[int, ...]]:
        # Deterministic sparse low-discrepancy-ish pattern.  Zero means keep
        # that coordinate unchanged; +/- are local trust-region nudges.
        rows: list[tuple[int, ...]] = []
        for seed in range(1, self.max_candidates * 3 + 1):
            values: list[int] = []
            active = 0
            for axis in range(dim):
                code = (seed * (axis + 3) + axis * axis) % 5
                direction = 0 if code == 0 else (1 if code in {1, 3} else -1)
                values.append(direction)
                if direction != 0:
                    active += 1
            if 2 <= active <= 4:
                row = tuple(values)
                if row not in rows:
                    rows.append(row)
            if len(rows) >= self.max_candidates:
                break
        return rows


__all__ = ["SubspaceBatchGenerator"]
