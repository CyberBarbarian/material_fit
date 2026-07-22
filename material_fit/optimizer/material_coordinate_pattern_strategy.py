"""Asset-independent coordinate pattern search for material refinement."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_proposals import parameter_changes
from .structured_fish_space import FishSearchCoordinate, structured_fish_coordinates
from .material_discrete_space import (
    attach_discrete_candidate,
    normalize_discrete_candidate,
    split_discrete_candidate,
)


_DIRECTIONS = (-1.0, 1.0)


class MaterialCoordinatePatternStrategy(OptimizerStrategy):
    """Refine shared material coordinates using only measured PNG scores."""

    name = "material_coordinate_pattern"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        discrete_candidates: Sequence[Mapping[str, Any]] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        self._coordinates = structured_fish_coordinates(
            initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        if not self._coordinates:
            raise ValueError("material_coordinate_pattern has no searchable coordinates")
        self._coordinate_by_id = {
            coordinate.coordinate_id: coordinate for coordinate in self._coordinates
        }

        initial_step_scale = _bounded_float(cfg.get("initial_step_scale"), 0.25, 0.01, 2.0)
        minimum_step_scale = _bounded_float(cfg.get("minimum_step_scale"), 1.0 / 64.0, 1.0e-4, 1.0)
        self._step_growth = _bounded_float(cfg.get("step_growth"), 1.20, 1.0, 2.0)
        self._step_shrink = _bounded_float(cfg.get("step_shrink"), 0.5, 0.1, 0.95)
        self._minimum_score_gain = max(float(cfg.get("minimum_score_gain", 1.0e-7)), 0.0)
        self._pattern_move_scales = tuple(
            value
            for value in (
                _bounded_float(raw, 0.0, 0.0, 4.0)
                for raw in cfg.get("pattern_move_scales", ())
            )
            if value > 0.0
        )
        self._active_coordinate_count = min(
            max(int(cfg.get("active_coordinate_count", 12)), 0),
            len(self._coordinates),
        )
        self._full_refresh_interval = max(int(cfg.get("full_refresh_interval", 4)), 0)
        self._hard_state_refresh_interval = max(
            int(cfg.get("hard_state_refresh_interval", 2)),
            0,
        )
        self._initial_grid_points = max(int(cfg.get("initial_grid_points", 0)), 0)

        self._hard_state_candidates = tuple(
            normalize_discrete_candidate(candidate)
            for candidate in (discrete_candidates or ())
        )
        if self._hard_state_candidates:
            ids = [str(candidate["candidate_id"]) for candidate in self._hard_state_candidates]
            if len(ids) != len(set(ids)):
                raise ValueError("material coordinate pattern hard states must be unique")
            _continuous, initial_candidate = split_discrete_candidate(initial_params)
            if initial_candidate is None or str(initial_candidate["candidate_id"]) not in ids:
                raise ValueError("initial material hard state is outside the legal candidate set")

        self._steps = {
            coordinate.coordinate_id: max(
                coordinate.initial_step * initial_step_scale,
                (coordinate.high - coordinate.low) * 1.0e-6,
            )
            for coordinate in self._coordinates
        }
        self._minimum_steps = {
            coordinate.coordinate_id: max(
                coordinate.initial_step * minimum_step_scale,
                (coordinate.high - coordinate.low) * 1.0e-7,
            )
            for coordinate in self._coordinates
        }
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._round_index = 0
        self._round_coordinates = list(self._coordinates)
        self._coordinate_index = 0
        self._direction_index = 0
        self._local_best_score: float | None = None
        self._local_best_params: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._pattern_queue: list[dict[str, Any]] = []
        self._hard_state_queue: list[dict[str, Any]] = []
        self._initial_grid_queue = self._build_initial_grid_queue(initial_params)
        self._initial_grid_completed = not self._initial_grid_queue
        self._round_start_params = copy.deepcopy(initial_params)
        self._coordinate_priorities = {
            coordinate.coordinate_id: 0.0 for coordinate in self._coordinates
        }
        self._selected_coordinate_ids: tuple[str, ...] = tuple(
            coordinate.coordinate_id for coordinate in self._round_coordinates
        )
        self._accepted_moves = 0
        self._probe_count = 0
        self._full_sweeps = 0
        self._active_sweeps = 0
        self._pattern_probe_count = 0
        self._accepted_pattern_moves = 0
        self._hard_state_sweeps = 0
        self._hard_state_probe_count = 0
        self._accepted_hard_state_moves = 0
        self._initial_grid_probe_count = 0
        self._accepted_initial_grid_moves = 0

    def wants_global_no_improve_check(self) -> bool:
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        previous = self._consume_pending(ctx)
        if self._best_fit_score is None:
            self._best_fit_score = float(ctx.fit_score)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._reset_local_search()
            self._enqueue_hard_state_scan()

        while True:
            if self._initial_grid_queue:
                item = self._initial_grid_queue.pop(0)
                coordinate = self._coordinate_by_id[str(item["coordinate_id"])]
                candidate = coordinate.write(self._best_params, float(item["value"]))
                self._initial_grid_probe_count += 1
                self._pending = {
                    "role": "initial_grid",
                    "coordinate_id": str(item["coordinate_id"]),
                    "value": float(item["value"]),
                }
                return candidate, self._initial_grid_decision(
                    item=item,
                    previous=previous,
                    candidate=candidate,
                )
            if not self._initial_grid_completed:
                self._initial_grid_completed = True
                self._round_start_params = copy.deepcopy(self._best_params)
                self._reset_local_search()
            if self._hard_state_queue:
                candidate_state = self._hard_state_queue.pop(0)
                candidate = attach_discrete_candidate(self._best_params, candidate_state)
                self._hard_state_probe_count += 1
                self._pending = {
                    "role": "hard_state",
                    "candidate_id": str(candidate_state["candidate_id"]),
                }
                return candidate, self._hard_state_decision(
                    candidate_state=candidate_state,
                    previous=previous,
                    candidate=candidate,
                )
            if self._pattern_queue:
                item = self._pattern_queue.pop(0)
                candidate = copy.deepcopy(item["candidate"])
                self._pattern_probe_count += 1
                self._pending = {
                    "role": "pattern_move",
                    "scale": float(item["scale"]),
                }
                return candidate, self._pattern_decision(
                    scale=float(item["scale"]),
                    candidate=candidate,
                    previous=previous,
                )
            coordinate = self._round_coordinates[self._coordinate_index]
            if self._direction_index < len(_DIRECTIONS):
                direction = _DIRECTIONS[self._direction_index]
                self._direction_index += 1
                candidate = coordinate.write(
                    self._best_params,
                    coordinate.read(self._best_params)
                    + direction * self._steps[coordinate.coordinate_id],
                )
                if not parameter_changes(self._best_params, candidate):
                    continue
                self._probe_count += 1
                self._pending = {
                    "role": "coordinate",
                    "coordinate_id": coordinate.coordinate_id,
                    "direction": direction,
                }
                return candidate, self._decision(
                    coordinate=coordinate,
                    direction=direction,
                    previous=previous,
                    candidate=candidate,
                )

            self._finish_coordinate(coordinate)
            self._coordinate_index += 1
            if self._coordinate_index >= len(self._round_coordinates):
                self._finish_round()
            self._reset_local_search()

    def research_summary(self) -> dict[str, Any]:
        _continuous, best_candidate = split_discrete_candidate(self._best_params)
        return {
            "profile": "material_coordinate_pattern_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_only",
            "target_params_visible": False,
            "coordinate_count": len(self._coordinates),
            "active_coordinate_count": self._active_coordinate_count,
            "full_refresh_interval": self._full_refresh_interval,
            "hard_state_count": len(self._hard_state_candidates),
            "hard_state_refresh_interval": self._hard_state_refresh_interval,
            "initial_grid_points": self._initial_grid_points,
            "initial_grid_probe_count": self._initial_grid_probe_count,
            "accepted_initial_grid_moves": self._accepted_initial_grid_moves,
            "pattern_move_scales": list(self._pattern_move_scales),
            "round": self._round_index,
            "round_coordinate_count": len(self._round_coordinates),
            "selected_coordinate_ids": list(self._selected_coordinate_ids),
            "coordinate_priorities": copy.deepcopy(self._coordinate_priorities),
            "steps": copy.deepcopy(self._steps),
            "minimum_steps": copy.deepcopy(self._minimum_steps),
            "accepted_moves": self._accepted_moves,
            "probe_count": self._probe_count,
            "full_sweeps": self._full_sweeps,
            "active_sweeps": self._active_sweeps,
            "pattern_probe_count": self._pattern_probe_count,
            "accepted_pattern_moves": self._accepted_pattern_moves,
            "hard_state_sweeps": self._hard_state_sweeps,
            "hard_state_probe_count": self._hard_state_probe_count,
            "accepted_hard_state_moves": self._accepted_hard_state_moves,
            "best_hard_state_candidate_id": (
                str(best_candidate["candidate_id"]) if best_candidate is not None else None
            ),
            "best_fit_score": self._best_fit_score,
        }

    def _consume_pending(self, ctx: StrategyContext) -> dict[str, Any] | None:
        pending = self._pending
        if pending is None:
            return None
        self._pending = None
        score = float(ctx.fit_score)
        if pending.get("role") == "initial_grid":
            accepted = score > float(self._best_fit_score or 0.0) + self._minimum_score_gain
            if accepted:
                self._best_fit_score = score
                self._best_params = copy.deepcopy(ctx.current_params)
                self._accepted_initial_grid_moves += 1
            return {
                "role": "initial_grid",
                "coordinate_id": str(pending["coordinate_id"]),
                "value": float(pending["value"]),
                "score": score,
                "accepted": accepted,
            }
        if pending.get("role") == "hard_state":
            accepted = score > float(self._best_fit_score or 0.0) + self._minimum_score_gain
            if accepted:
                self._best_fit_score = score
                self._best_params = copy.deepcopy(ctx.current_params)
                self._round_start_params = copy.deepcopy(self._best_params)
                self._accepted_hard_state_moves += 1
                self._reset_local_search()
            return {
                "role": "hard_state",
                "candidate_id": str(pending["candidate_id"]),
                "score": score,
                "accepted": accepted,
            }
        if pending.get("role") == "pattern_move":
            accepted = score > float(self._best_fit_score or 0.0) + self._minimum_score_gain
            if accepted:
                self._best_fit_score = score
                self._best_params = copy.deepcopy(ctx.current_params)
                self._round_start_params = copy.deepcopy(self._best_params)
                self._pattern_queue = []
                self._accepted_pattern_moves += 1
                self._reset_local_search()
            return {
                "role": "pattern_move",
                "scale": float(pending["scale"]),
                "score": score,
                "accepted": accepted,
            }
        if self._local_best_score is None or score > self._local_best_score + self._minimum_score_gain:
            self._local_best_score = score
            self._local_best_params = copy.deepcopy(ctx.current_params)
        return {
            "coordinate_id": pending["coordinate_id"],
            "direction": pending["direction"],
            "score": score,
        }

    def _reset_local_search(self) -> None:
        self._direction_index = 0
        self._local_best_score = self._best_fit_score
        self._local_best_params = copy.deepcopy(self._best_params)

    def _finish_coordinate(self, coordinate: FishSearchCoordinate) -> None:
        coordinate_id = coordinate.coordinate_id
        old_score = float(self._best_fit_score or 0.0)
        new_score = float(self._local_best_score or old_score)
        gain = max(new_score - old_score, 0.0)
        previous_priority = self._coordinate_priorities[coordinate_id]
        self._coordinate_priorities[coordinate_id] = max(gain, previous_priority * 0.75)
        if gain > self._minimum_score_gain:
            self._best_fit_score = new_score
            self._best_params = copy.deepcopy(self._local_best_params or self._best_params)
            self._steps[coordinate_id] = min(
                self._steps[coordinate_id] * self._step_growth,
                coordinate.initial_step,
            )
            self._accepted_moves += 1
        else:
            self._steps[coordinate_id] = max(
                self._steps[coordinate_id] * self._step_shrink,
                self._minimum_steps[coordinate_id],
            )

    def _finish_round(self) -> None:
        if len(self._round_coordinates) == len(self._coordinates):
            self._full_sweeps += 1
        else:
            self._active_sweeps += 1
        self._round_index += 1
        use_full = (
            self._active_coordinate_count <= 0
            or self._active_coordinate_count >= len(self._coordinates)
            or (
                self._full_refresh_interval > 0
                and self._round_index % self._full_refresh_interval == 0
            )
        )
        if use_full:
            self._round_coordinates = list(self._coordinates)
        else:
            order = {coordinate.coordinate_id: index for index, coordinate in enumerate(self._coordinates)}
            self._round_coordinates = sorted(
                self._coordinates,
                key=lambda coordinate: (
                    -self._coordinate_priorities[coordinate.coordinate_id],
                    order[coordinate.coordinate_id],
                ),
            )[: self._active_coordinate_count]
        self._selected_coordinate_ids = tuple(
            coordinate.coordinate_id for coordinate in self._round_coordinates
        )
        self._coordinate_index = 0
        self._pattern_queue = self._build_pattern_queue()
        self._round_start_params = copy.deepcopy(self._best_params)
        if (
            self._hard_state_refresh_interval > 0
            and self._round_index % self._hard_state_refresh_interval == 0
        ):
            self._enqueue_hard_state_scan()

    def _enqueue_hard_state_scan(self) -> None:
        if not self._hard_state_candidates:
            return
        _continuous, current = split_discrete_candidate(self._best_params)
        current_id = str(current["candidate_id"]) if current is not None else ""
        self._hard_state_queue = [
            copy.deepcopy(candidate)
            for candidate in self._hard_state_candidates
            if str(candidate["candidate_id"]) != current_id
        ]
        self._hard_state_sweeps += 1

    def _build_pattern_queue(self) -> list[dict[str, Any]]:
        if not self._pattern_move_scales:
            return []
        changed = [
            coordinate
            for coordinate in self._coordinates
            if abs(
                coordinate.read(self._best_params)
                - coordinate.read(self._round_start_params)
            )
            > 1.0e-12
        ]
        if len(changed) < 2:
            return []
        queue: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, float], ...]] = set()
        for scale in self._pattern_move_scales:
            candidate = copy.deepcopy(self._best_params)
            for coordinate in changed:
                current = coordinate.read(self._best_params)
                displacement = current - coordinate.read(self._round_start_params)
                candidate = coordinate.write(candidate, current + scale * displacement)
            key = tuple(
                (coordinate.coordinate_id, round(coordinate.read(candidate), 10))
                for coordinate in changed
            )
            if key in seen or not parameter_changes(self._best_params, candidate):
                continue
            seen.add(key)
            queue.append({"scale": scale, "candidate": candidate})
        return queue

    def _build_initial_grid_queue(
        self,
        initial_params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self._initial_grid_points < 2:
            return []
        queue: list[dict[str, Any]] = []
        for coordinate in self._coordinates:
            for index in range(self._initial_grid_points):
                fraction = index / (self._initial_grid_points - 1)
                value = coordinate.low + fraction * (coordinate.high - coordinate.low)
                candidate = coordinate.write(initial_params, value)
                if not parameter_changes(initial_params, candidate):
                    continue
                queue.append(
                    {
                        "coordinate_id": coordinate.coordinate_id,
                        "value": value,
                        "candidate": candidate,
                    }
                )
        return queue

    def _initial_grid_decision(
        self,
        *,
        item: dict[str, Any],
        previous: dict[str, Any] | None,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "material_coordinate_pattern_initial_grid",
                "description": "Target-independent global coordinate calibration scan",
            },
            "material_coordinate_pattern": {
                "round": self._round_index,
                "role": "initial_grid",
                "coordinate": str(item["coordinate_id"]),
                "value": float(item["value"]),
                "best_fit_score": self._best_fit_score,
                "previous_candidate": previous,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _pattern_decision(
        self,
        *,
        scale: float,
        candidate: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "material_coordinate_pattern_joint_move",
                "description": "Joint extrapolation of accepted coordinate moves",
            },
            "material_coordinate_pattern": {
                "round": self._round_index,
                "role": "pattern_move",
                "scale": scale,
                "best_fit_score": self._best_fit_score,
                "previous_candidate": previous,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _hard_state_decision(
        self,
        *,
        candidate_state: dict[str, Any],
        previous: dict[str, Any] | None,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "material_coordinate_pattern_hard_state_probe",
                "description": "Measured categorical neighbor in the shared material space",
            },
            "material_coordinate_pattern": {
                "round": self._round_index,
                "role": "hard_state",
                "candidate_id": str(candidate_state["candidate_id"]),
                "best_fit_score": self._best_fit_score,
                "previous_candidate": previous,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _decision(
        self,
        *,
        coordinate: FishSearchCoordinate,
        direction: float,
        previous: dict[str, Any] | None,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "material_coordinate_pattern_probe",
                "description": "Measured coordinate pattern search over the shared material space",
            },
            "material_coordinate_pattern": {
                "round": self._round_index,
                "coordinate_index": self._coordinate_index,
                "coordinate_count": len(self._coordinates),
                "round_coordinate_count": len(self._round_coordinates),
                "coordinate": coordinate.coordinate_id,
                "direction": direction,
                "step": self._steps[coordinate.coordinate_id],
                "bounds": [coordinate.low, coordinate.high],
                "best_fit_score": self._best_fit_score,
                "selected_coordinate_ids": list(self._selected_coordinate_ids),
                "previous_candidate": previous,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._best_params, candidate),
            "stop_reason": "continue",
        }


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return min(max(numeric, low), high)


__all__ = ["MaterialCoordinatePatternStrategy"]
