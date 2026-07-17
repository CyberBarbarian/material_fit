"""Deterministic circular grid search for scene and light rotations."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_proposals import parameter_changes
from .structured_fish_space import structured_fish_coordinates


class MaterialSceneGridStrategy(OptimizerStrategy):
    """Search circular scalar coordinates using PNG-score feedback only."""

    name = "material_scene_grid"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        self._coordinates = [
            coordinate
            for coordinate in structured_fish_coordinates(
                initial_params,
                shader_params=shader_params,
                search_param_names=search_param_names,
            )
            if coordinate.component is None
        ]
        if not self._coordinates:
            raise ValueError("material_scene_grid has no searchable scalar coordinates")
        raw_coarse = cfg.get(
            "coarse_values",
            (-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0),
        )
        self._coarse_values = tuple(_wrap_degrees(float(value)) for value in raw_coarse)
        self._refinement_steps = tuple(
            abs(float(value))
            for value in cfg.get("refinement_steps", (22.5, 11.25))
            if math.isfinite(float(value)) and abs(float(value)) > 0.0
        )
        self._minimum_score_gain = max(
            float(cfg.get("minimum_score_gain", 1.0e-6)),
            0.0,
        )
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._level_index = 0
        self._coordinate_index = 0
        self._queue: list[float] = []
        self._pending = False
        self._finished = False
        self._probe_count = 0
        self._accept_count = 0

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return "material_scene_grid_complete" if self._finished else None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        while not self._finished:
            coordinate = self._coordinates[self._coordinate_index]
            if not self._queue:
                self._queue = self._candidate_values(coordinate.param_name)
            while self._queue:
                value = self._queue.pop(0)
                candidate = copy.deepcopy(self._best_params)
                candidate[coordinate.param_name] = value
                if not parameter_changes(self._best_params, candidate):
                    continue
                self._pending = True
                self._probe_count += 1
                return candidate, self._decision(
                    coordinate=coordinate.param_name,
                    value=value,
                    stop=False,
                )
            self._advance()
        return copy.deepcopy(self._best_params), self._decision(
            coordinate=None,
            value=None,
            stop=True,
        )

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": "material_scene_grid_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_score_only",
            "target_params_visible": False,
            "coordinate_names": [
                coordinate.param_name for coordinate in self._coordinates
            ],
            "coarse_values": list(self._coarse_values),
            "refinement_steps": list(self._refinement_steps),
            "level_index": self._level_index,
            "coordinate_index": self._coordinate_index,
            "probe_count": self._probe_count,
            "accept_count": self._accept_count,
            "best_fit_score": self._best_fit_score,
            "stop_reason": self.stop_reason(),
        }

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if not math.isfinite(score):
            self._pending = False
            return
        if self._best_fit_score is None:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
        elif self._pending and score > self._best_fit_score + self._minimum_score_gain:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._accept_count += 1
        self._pending = False

    def _candidate_values(self, name: str) -> list[float]:
        if self._level_index == 0:
            raw_values = self._coarse_values
        else:
            step = self._refinement_steps[self._level_index - 1]
            center = float(self._best_params[name])
            raw_values = (center - step, center + step)
        values: list[float] = []
        for raw_value in raw_values:
            value = _wrap_degrees(float(raw_value))
            if all(abs(_wrapped_delta(value, existing)) > 1.0e-9 for existing in values):
                values.append(value)
        return values

    def _advance(self) -> None:
        self._coordinate_index += 1
        if self._coordinate_index < len(self._coordinates):
            return
        self._coordinate_index = 0
        self._level_index += 1
        if self._level_index > len(self._refinement_steps):
            self._finished = True

    def _decision(
        self,
        *,
        coordinate: str | None,
        value: float | None,
        stop: bool,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None
            if stop
            else {
                "name": "material_scene_circular_grid",
                "description": "Target-independent circular scene rotation search",
            },
            "material_scene_grid": {
                "level_index": self._level_index,
                "coordinate": coordinate,
                "value": value,
                "best_fit_score": self._best_fit_score,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "changes": [],
            "stop_reason": "material_scene_grid_complete" if stop else "continue",
        }


def _wrap_degrees(value: float) -> float:
    wrapped = ((value + 180.0) % 360.0) - 180.0
    return 180.0 if abs(wrapped + 180.0) <= 1.0e-12 and value > 0.0 else wrapped


def _wrapped_delta(left: float, right: float) -> float:
    return _wrap_degrees(left - right)


__all__ = ["MaterialSceneGridStrategy"]
