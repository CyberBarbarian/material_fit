"""Staged black-box optimizer over the structured fish search space."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_escape import (
    DEFAULT_ESCAPE_PAIR_COUNT,
    DEFAULT_ESCAPE_RADII,
    BlockEscapeDirection,
    BlockEscapeObservation,
    BlockEscapeProbe,
    BlockEscapeResponseMove,
    apply_block_escape_probe,
    build_block_escape_directions,
    build_block_escape_response_moves,
    build_coordinate_escape_directions,
)
from .structured_fish_proposals import (
    build_joint_pattern_move,
    normalized_coordinate_distance,
    parameter_changes as _diff_params,
    rank_coordinates,
    residual_feature_vector as _residual_feature_vector,
    solve_gauss_newton_move,
    vector_rms as _vector_rms,
)
from .structured_fish_space import (
    FishSearchCoordinate,
    MATERIAL_GROUPS,
    SCENE_ALIGNMENT_GROUP,
    STRUCTURED_GROUP_ORDER,
    structured_fish_coordinates,
    structured_fish_space_manifest,
)


_DIRECTIONS: tuple[float, float] = (-1.0, 1.0)
_EPS = 1.0e-9


class StructuredFishStrategy(OptimizerStrategy):
    """Stage-wise coordinate search with response-ranked refinement.

    The strategy sees only current parameters and image-score feedback.  It
    never receives target material parameters.  One broad pass is made over
    each semantic group, beginning with global scene alignment; subsequent
    passes rank coordinates by measured score response and shrink failed axes.
    """

    name = "structured_fish"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None = None,
        regularization_weight: float = 0.0,
        regularization_final_weight: float = 0.0,
        regularization_decay: float = 0.5,
        regularization_disable_score: float | None = None,
        pattern_move_scale: float = 0.5,
        gauss_newton_damping: float = 0.75,
        gauss_newton_ridge: float = 0.001,
        gauss_newton_max_repeats: int = 2,
        gauss_newton_interval: int = 16,
        gauss_newton_high_score_threshold: float = 1.0,
        gauss_newton_high_score_interval: int | None = None,
        gauss_newton_high_score_max_repeats: int | None = None,
        broad_coordinate_max_repeats: int = 0,
        scene_alignment_rounds: int = 1,
        freeze_scene_after_alignment: bool = False,
        basin_escape_enabled: bool = False,
        basin_escape_pair_count: int = DEFAULT_ESCAPE_PAIR_COUNT,
        basin_escape_round_pair_counts: Sequence[int] | None = None,
        basin_escape_radii: Sequence[float] = DEFAULT_ESCAPE_RADII,
        basin_escape_damping: float = 0.80,
        basin_escape_ridge: float = 0.01,
        basin_escape_seed: int = 1701,
        basin_escape_activation_min_fit_score: float = 0.0,
        basin_escape_activation_mode: str = "initial",
        basin_escape_disable_opportunistic_when_skipped: bool = False,
        basin_escape_response_methods: Sequence[str] = (
            "residual_block_secant",
            "scalar_score_response",
        ),
        basin_escape_direction_design: str = "full_rank_hadamard_v1",
        basin_escape_response_trust_radius: float | None = None,
        basin_escape_response_line_search_scales: Sequence[float] = (1.0,),
        opportunistic_ranked_accept: bool = False,
    ) -> None:
        self._coordinates = structured_fish_coordinates(
            initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        self._coordinate_by_id = {
            coordinate.coordinate_id: coordinate for coordinate in self._coordinates
        }
        self._groups = [
            (group, [coordinate for coordinate in self._coordinates if coordinate.group == group])
            for group in STRUCTURED_GROUP_ORDER
        ]
        self._groups = [(group, coordinates) for group, coordinates in self._groups if coordinates]
        self._steps = {
            coordinate.coordinate_id: float(coordinate.initial_step)
            for coordinate in self._coordinates
        }
        self._initial_params = copy.deepcopy(initial_params)
        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score: float | None = None
        self._best_objective_score: float | None = None
        weight = float(regularization_weight)
        self._initial_regularization_weight = (
            weight if math.isfinite(weight) and weight >= 0.0 else 0.0
        )
        final_weight = float(regularization_final_weight)
        self._regularization_final_weight = (
            min(max(final_weight, 0.0), self._initial_regularization_weight)
            if math.isfinite(final_weight)
            else 0.0
        )
        decay = float(regularization_decay)
        self._regularization_decay = (
            min(max(decay, 0.0), 1.0) if math.isfinite(decay) else 0.5
        )
        self._regularization_weight = self._initial_regularization_weight
        disable_score = (
            float(regularization_disable_score)
            if regularization_disable_score is not None
            else None
        )
        self._regularization_disable_score = (
            min(max(disable_score, 0.0), 1.0)
            if disable_score is not None and math.isfinite(disable_score)
            else None
        )
        self._regularization_disabled_by_score = False
        self._regularization_disable_trigger_score: float | None = None
        scale = float(pattern_move_scale)
        self._pattern_move_scale = scale if math.isfinite(scale) and scale > 0.0 else 0.5
        damping = float(gauss_newton_damping)
        self._gauss_newton_damping = min(max(damping, 0.05), 1.0) if math.isfinite(damping) else 0.75
        self._current_gauss_newton_damping = self._gauss_newton_damping
        ridge = float(gauss_newton_ridge)
        self._gauss_newton_ridge = max(ridge, 0.0) if math.isfinite(ridge) else 0.001
        self._gauss_newton_max_repeats = max(int(gauss_newton_max_repeats), 0)
        self._gauss_newton_interval = max(int(gauss_newton_interval), 1)
        high_score_threshold = float(gauss_newton_high_score_threshold)
        self._gauss_newton_high_score_threshold = (
            min(max(high_score_threshold, 0.0), 1.0)
            if math.isfinite(high_score_threshold)
            else 1.0
        )
        self._gauss_newton_high_score_interval = max(
            int(
                self._gauss_newton_interval
                if gauss_newton_high_score_interval is None
                else gauss_newton_high_score_interval
            ),
            1,
        )
        self._gauss_newton_high_score_max_repeats = max(
            int(
                self._gauss_newton_max_repeats
                if gauss_newton_high_score_max_repeats is None
                else gauss_newton_high_score_max_repeats
            ),
            0,
        )
        self._broad_coordinate_max_repeats = max(
            int(broad_coordinate_max_repeats),
            0,
        )
        self._broad_coordinate_repeat_index = 0
        self._broad_coordinate_repeat_count = 0
        self._scene_alignment_rounds = max(int(scene_alignment_rounds), 1)
        self._freeze_scene_after_alignment = bool(freeze_scene_after_alignment)
        self._scene_alignment_round = 1
        self._scene_alignment_frozen = False
        self._basin_escape_enabled = bool(basin_escape_enabled)
        self._basin_escape_pair_count = max(int(basin_escape_pair_count), 1)
        self._basin_escape_radii = tuple(
            value
            for raw in basin_escape_radii
            if math.isfinite(value := float(raw)) and value > 0.0
        )
        escape_damping = float(basin_escape_damping)
        self._basin_escape_damping = (
            min(max(escape_damping, 0.05), 1.0)
            if math.isfinite(escape_damping)
            else 0.80
        )
        escape_ridge = float(basin_escape_ridge)
        self._basin_escape_ridge = (
            max(escape_ridge, 0.0) if math.isfinite(escape_ridge) else 0.01
        )
        self._basin_escape_seed = int(basin_escape_seed)
        allowed_direction_designs = {"full_rank_hadamard_v1", "coordinate_basis_v1"}
        self._basin_escape_direction_design = (
            str(basin_escape_direction_design)
            if str(basin_escape_direction_design) in allowed_direction_designs
            else "full_rank_hadamard_v1"
        )
        raw_response_trust = (
            float(basin_escape_response_trust_radius)
            if basin_escape_response_trust_radius is not None
            else 0.0
        )
        self._basin_escape_response_trust_radius = (
            raw_response_trust
            if math.isfinite(raw_response_trust) and raw_response_trust > 0.0
            else None
        )
        self._basin_escape_response_line_search_scales = tuple(
            float(scale)
            for raw in basin_escape_response_line_search_scales
            if math.isfinite(scale := float(raw)) and abs(scale) > 0.0
        ) or (1.0,)
        activation_score = float(basin_escape_activation_min_fit_score)
        self._basin_escape_activation_min_fit_score = (
            min(max(activation_score, 0.0), 1.0)
            if math.isfinite(activation_score)
            else 0.0
        )
        allowed_activation_modes = {"initial", "after_broad_groups"}
        self._basin_escape_activation_mode = (
            str(basin_escape_activation_mode)
            if str(basin_escape_activation_mode) in allowed_activation_modes
            else "initial"
        )
        self._basin_escape_disable_opportunistic_when_skipped = bool(
            basin_escape_disable_opportunistic_when_skipped
        )
        self._basin_escape_initial_fit_score: float | None = None
        raw_round_counts = list(basin_escape_round_pair_counts or ())
        self._basin_escape_round_pair_counts = tuple(
            max(int(raw_round_counts[index]), 1)
            if index < len(raw_round_counts)
            else self._basin_escape_pair_count
            for index in range(len(self._basin_escape_radii))
        )
        allowed_response_methods = {
            "residual_block_secant",
            "scalar_score_response",
        }
        self._basin_escape_response_methods = tuple(
            method
            for raw in basin_escape_response_methods
            if (method := str(raw)) in allowed_response_methods
        )
        self._opportunistic_ranked_accept_configured = bool(
            opportunistic_ranked_accept
        )
        self._opportunistic_ranked_accept = self._opportunistic_ranked_accept_configured
        self._opportunistic_skip_count = 0
        self._basin_escape_round_index = 0
        self._basin_escape_directions: list[BlockEscapeDirection] = []
        self._basin_escape_probe_cursor = 0
        self._basin_escape_round_center: dict[str, Any] | None = None
        self._basin_escape_round_center_features: list[float] | None = None
        self._basin_escape_observation_parts: dict[int, dict[float, dict[str, Any]]] = {}
        self._basin_escape_response_moves: list[BlockEscapeResponseMove] = []
        self._basin_escape_response_index = 0
        self._basin_escape_response_built = False
        self._basin_escape_probe_count = 0
        self._basin_escape_accept_count = 0
        self._basin_escape_response_probe_count = 0
        self._basin_escape_response_accept_count = 0
        self._basin_escape_results: list[dict[str, Any]] = []
        self._gauss_newton_repeat_index = 0
        self._coordinates_since_joint = 0
        has_escape_coordinates = any(
            coordinate.group in MATERIAL_GROUPS for coordinate in self._coordinates
        )
        escape_available = (
            self._basin_escape_enabled
            and bool(self._basin_escape_radii)
            and has_escape_coordinates
        )
        self._phase = (
            "basin_escape"
            if escape_available and self._basin_escape_activation_mode == "initial"
            else "broad_groups"
        )
        self._basin_escape_activation_status = (
            (
                "pending_initial"
                if self._phase == "basin_escape"
                else "pending_after_broad_groups"
            )
            if escape_available
            else "disabled"
        )
        self._basin_escape_return_phase = "broad_groups"
        self._group_index = 0
        self._round_index = 1
        self._agenda = list(self._groups[0][1]) if self._groups else []
        self._coordinate_index = 0
        self._direction_index = 0
        self._local_best_score: float | None = None
        self._local_best_raw_score: float | None = None
        self._local_best_params: dict[str, Any] | None = None
        self._best_features: list[float] | None = None
        self._local_best_features: list[float] | None = None
        self._probe_scores: dict[float, float] = {}
        self._probe_feature_samples: dict[float, tuple[float, list[float]]] = {}
        self._jacobian_columns: dict[str, list[float]] = {}
        self._interpolation_attempted = False
        self._joint_probe_due = False
        self._pending: dict[str, Any] | None = None
        self._stop_reason: str | None = None
        self._accept_count = 0
        self._probe_count = 0
        self._shrink_count = 0
        self._joint_probe_count = 0
        self._joint_accept_count = 0
        self._gauss_newton_probe_count = 0
        self._gauss_newton_accept_count = 0
        self._gauss_newton_repeat_probe_count = 0
        self._gauss_newton_repeat_accept_count = 0
        self._response: dict[str, dict[str, Any]] = {
            coordinate.coordinate_id: {
                "attempts": 0,
                "success_count": 0,
                "best_gain": 0.0,
                "last_gain": 0.0,
                "best_direction": None,
                "fail_streak": 0,
            }
            for coordinate in self._coordinates
        }
        self._space_manifest = structured_fish_space_manifest(
            initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )

    def wants_global_no_improve_check(self) -> bool:
        return False

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        previous = self._consume_pending(ctx)
        if self._best_fit_score is None:
            self._best_fit_score = float(ctx.fit_score)
            self._best_objective_score = self._objective_score(ctx.current_params, self._best_fit_score)
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_features = _residual_feature_vector(ctx.analysis)
            self._maybe_disable_regularization(self._best_fit_score)
            self._reset_coordinate_probe()
        if (
            self._phase == "basin_escape"
            and self._basin_escape_activation_status == "pending_initial"
        ):
            if not self._activate_basin_escape(
                float(ctx.fit_score),
                skipped_status="skipped_initial_fit_below_threshold",
            ):
                self._phase = "broad_groups"
        if not self._coordinates:
            self._stop_reason = "structured_fish_no_searchable_coordinates"
            return copy.deepcopy(self._best_params), self._stop_decision(previous)
        if self._phase == "basin_escape":
            return self._next_basin_escape_candidate(previous)
        if self._phase == "broad_groups":
            return self._next_broad_candidate(previous)
        return self._next_ranked_candidate(previous)

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def research_summary(self) -> dict[str, Any]:
        group = self._current_group_name()
        return {
            "profile": "structured_fish_v1",
            "phase": self._phase,
            "group": group,
            "round": self._round_index,
            "search_space": copy.deepcopy(self._space_manifest),
            "steps": dict(self._steps),
            "agenda": [coordinate.coordinate_id for coordinate in self._agenda],
            "response": copy.deepcopy(self._response),
            "accept_count": self._accept_count,
            "probe_count": self._probe_count,
            "shrink_count": self._shrink_count,
            "joint_probe_count": self._joint_probe_count,
            "joint_accept_count": self._joint_accept_count,
            "gauss_newton_probe_count": self._gauss_newton_probe_count,
            "gauss_newton_accept_count": self._gauss_newton_accept_count,
            "gauss_newton_repeat_probe_count": self._gauss_newton_repeat_probe_count,
            "gauss_newton_repeat_accept_count": self._gauss_newton_repeat_accept_count,
            "gauss_newton_damping": self._gauss_newton_damping,
            "gauss_newton_current_damping": self._current_gauss_newton_damping,
            "gauss_newton_max_repeats": self._gauss_newton_max_repeats,
            "gauss_newton_interval": self._gauss_newton_interval,
            "gauss_newton_high_score_threshold": (
                self._gauss_newton_high_score_threshold
            ),
            "gauss_newton_high_score_interval": (
                self._gauss_newton_high_score_interval
            ),
            "gauss_newton_high_score_max_repeats": (
                self._gauss_newton_high_score_max_repeats
            ),
            "gauss_newton_effective_interval": (
                self._effective_gauss_newton_interval()
            ),
            "gauss_newton_effective_max_repeats": (
                self._effective_gauss_newton_max_repeats()
            ),
            "coordinates_since_joint": self._coordinates_since_joint,
            "broad_coordinate_max_repeats": self._broad_coordinate_max_repeats,
            "broad_coordinate_repeat_count": self._broad_coordinate_repeat_count,
            "opportunistic_ranked_accept_configured": (
                self._opportunistic_ranked_accept_configured
            ),
            "opportunistic_ranked_accept": self._opportunistic_ranked_accept,
            "opportunistic_skip_count": self._opportunistic_skip_count,
            "scene_alignment_rounds": self._scene_alignment_rounds,
            "scene_alignment_round": self._scene_alignment_round,
            "freeze_scene_after_alignment": self._freeze_scene_after_alignment,
            "scene_alignment_frozen": self._scene_alignment_frozen,
            "basin_escape": {
                "enabled": self._basin_escape_enabled,
                "activation_mode": self._basin_escape_activation_mode,
                "profile": "antithetic_block_secant_v1",
                "direction_design": self._basin_escape_direction_design,
                "contract": "start_params_public_space_and_online_image_feedback_only",
                "target_params_visible": False,
                "activation_min_fit_score": (
                    self._basin_escape_activation_min_fit_score
                ),
                "initial_fit_score": self._basin_escape_initial_fit_score,
                "activation_fit_score": self._basin_escape_initial_fit_score,
                "activation_status": self._basin_escape_activation_status,
                "disable_opportunistic_when_skipped": (
                    self._basin_escape_disable_opportunistic_when_skipped
                ),
                "pair_count": self._basin_escape_pair_count,
                "round_pair_counts": list(self._basin_escape_round_pair_counts),
                "radii": list(self._basin_escape_radii),
                "response_methods": list(self._basin_escape_response_methods),
                "round_index": self._basin_escape_round_index,
                "damping": self._basin_escape_damping,
                "ridge": self._basin_escape_ridge,
                "response_trust_radius": self._basin_escape_response_trust_radius,
                "response_line_search_scales": list(
                    self._basin_escape_response_line_search_scales
                ),
                "seed": self._basin_escape_seed,
                "probe_count": self._basin_escape_probe_count,
                "accept_count": self._basin_escape_accept_count,
                "response_probe_count": self._basin_escape_response_probe_count,
                "response_accept_count": self._basin_escape_response_accept_count,
                "current_direction_seed": (
                    self._basin_escape_directions[0].seed
                    if self._basin_escape_directions
                    else None
                ),
                "results": copy.deepcopy(self._basin_escape_results),
            },
            "jacobian_column_count": len(self._jacobian_columns),
            "residual_feature_count": len(self._best_features or []),
            "residual_feature_rms": _vector_rms(self._best_features),
            "best_fit_score": self._best_fit_score,
            "best_objective_score": self._best_objective_score,
            "regularization_weight": self._regularization_weight,
            "regularization_initial_weight": self._initial_regularization_weight,
            "regularization_final_weight": self._regularization_final_weight,
            "regularization_decay": self._regularization_decay,
            "regularization_disable_score": self._regularization_disable_score,
            "regularization_disabled_by_score": self._regularization_disabled_by_score,
            "regularization_disable_trigger_score": (
                self._regularization_disable_trigger_score
            ),
            "best_initial_distance": self._normalized_initial_distance(self._best_params),
            "pattern_move_scale": self._pattern_move_scale,
            "stop_reason": self._stop_reason,
        }

    def _consume_pending(self, ctx: StrategyContext) -> dict[str, Any] | None:
        if self._pending is None:
            return None
        pending = self._pending
        self._pending = None
        raw_score = float(ctx.fit_score)
        score = self._objective_score(ctx.current_params, raw_score)
        features = _residual_feature_vector(ctx.analysis)
        base_score = float(pending.get("base_objective_score", self._best_objective_score or score))
        gain = score - base_score
        if pending.get("probe_kind") in {
            "basin_escape_block_probe",
            "basin_escape_response",
        }:
            probe_kind = str(pending["probe_kind"])
            improved = self._best_objective_score is None or score > self._best_objective_score + _EPS
            if improved:
                self._best_objective_score = score
                self._best_fit_score = raw_score
                self._best_params = copy.deepcopy(ctx.current_params)
                self._best_features = copy.deepcopy(features)
                self._maybe_disable_regularization(raw_score)
                self._accept_count += 1
                self._basin_escape_accept_count += 1
                if probe_kind == "basin_escape_response":
                    self._basin_escape_response_accept_count += 1
            if probe_kind == "basin_escape_block_probe":
                direction_index = int(pending["direction_index"])
                polarity = float(pending["polarity"])
                self._basin_escape_observation_parts.setdefault(direction_index, {})[
                    polarity
                ] = {
                    "params": copy.deepcopy(ctx.current_params),
                    "fit_score": raw_score,
                    "objective_score": score,
                    "features": copy.deepcopy(features),
                }
            result = {
                "probe_kind": probe_kind,
                "round": int(pending["round"]),
                "radius": float(pending["radius"]),
                "direction_index": pending.get("direction_index"),
                "polarity": pending.get("polarity"),
                "response_method": pending.get("response_method"),
                "coordinates": list(pending.get("coordinates") or []),
                "fit_score": raw_score,
                "objective_score": score,
                "regularization_penalty": raw_score - score,
                "gain": gain,
                "improved": improved,
            }
            self._basin_escape_results.append(copy.deepcopy(result))
            return {
                "kind": "structured_fish_basin_escape",
                "phase": pending["phase"],
                "group": "basin_escape",
                **result,
            }
        if pending.get("probe_kind") in {"joint_pattern", "gauss_newton"}:
            probe_kind = str(pending.get("probe_kind"))
            improved = self._best_objective_score is None or score > self._best_objective_score + _EPS
            if improved:
                self._best_objective_score = score
                self._best_fit_score = raw_score
                self._best_params = copy.deepcopy(ctx.current_params)
                self._best_features = copy.deepcopy(features)
                self._maybe_disable_regularization(raw_score)
                self._accept_count += 1
                self._joint_accept_count += 1
                if probe_kind == "gauss_newton":
                    self._gauss_newton_accept_count += 1
                    repeat_index = int(pending.get("repeat_index", 0) or 0)
                    if repeat_index > 0:
                        self._gauss_newton_repeat_accept_count += 1
                    if repeat_index < self._effective_gauss_newton_max_repeats():
                        self._gauss_newton_repeat_index = repeat_index + 1
                        accepted_damping = float(
                            pending.get("damping", self._current_gauss_newton_damping)
                        )
                        self._current_gauss_newton_damping = min(
                            1.0,
                            accepted_damping * 1.2,
                        )
                        self._joint_probe_due = True
                    else:
                        self._gauss_newton_repeat_index = 0
            elif probe_kind == "gauss_newton":
                rejected_damping = float(
                    pending.get("damping", self._current_gauss_newton_damping)
                )
                self._current_gauss_newton_damping = max(
                    0.10,
                    rejected_damping * 0.5,
                )
                self._gauss_newton_repeat_index = 0
            return {
                "kind": f"structured_fish_{probe_kind}",
                "phase": pending["phase"],
                "group": probe_kind,
                "round": pending["round"],
                "repeat_index": int(pending.get("repeat_index", 0) or 0),
                "damping": pending.get("damping"),
                "coordinates": list(pending.get("coordinates") or []),
                "fit_score": raw_score,
                "objective_score": score,
                "regularization_penalty": raw_score - score,
                "gain": gain,
                "improved": improved,
            }
        coordinate_id = str(pending["coordinate"])
        response = self._response[coordinate_id]
        response["attempts"] = int(response["attempts"]) + 1
        response["last_gain"] = gain
        direction = float(pending["direction"])
        if pending.get("probe_kind") == "axis":
            self._probe_scores[direction] = score
            if features is not None:
                self._probe_feature_samples[direction] = (
                    float(pending["delta"]),
                    features,
                )
        if gain > float(response["best_gain"]) + _EPS:
            response["best_gain"] = gain
            response["best_direction"] = direction
        if gain > _EPS:
            response["success_count"] = int(response["success_count"]) + 1
            response["fail_streak"] = 0
        else:
            response["fail_streak"] = int(response["fail_streak"]) + 1

        improved_local = self._local_best_score is None or score > self._local_best_score + _EPS
        if improved_local:
            self._local_best_score = score
            self._local_best_raw_score = raw_score
            self._local_best_params = copy.deepcopy(ctx.current_params)
            self._local_best_features = copy.deepcopy(features)
        return {
            "kind": "structured_fish_probe",
            "phase": pending["phase"],
            "group": pending["group"],
            "round": pending["round"],
            "coordinate": coordinate_id,
            "direction": direction,
            "probe_kind": pending.get("probe_kind"),
            "delta": pending["delta"],
            "fit_score": raw_score,
            "objective_score": score,
            "regularization_penalty": raw_score - score,
            "gain": gain,
            "improved_local": improved_local,
        }

    def _activate_basin_escape(
        self,
        fit_score: float,
        *,
        skipped_status: str,
    ) -> bool:
        self._basin_escape_initial_fit_score = float(fit_score)
        if (
            self._basin_escape_initial_fit_score + _EPS
            < self._basin_escape_activation_min_fit_score
        ):
            self._basin_escape_activation_status = skipped_status
            if self._basin_escape_disable_opportunistic_when_skipped:
                self._opportunistic_ranked_accept = False
            return False
        self._basin_escape_activation_status = "active"
        return True

    def _enter_ranked_refinement(self) -> None:
        self._phase = "ranked_refinement"
        self._round_index = 1
        self._update_regularization_schedule()
        self._agenda = self._ranked_agenda()
        self._coordinate_index = 0
        self._reset_gauss_newton_trust_region()
        self._joint_probe_due = True
        self._reset_coordinate_probe()

    def _next_basin_escape_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._basin_escape_round_index < len(self._basin_escape_radii):
            if not self._basin_escape_directions:
                self._start_basin_escape_round()
            radius = self._basin_escape_radii[self._basin_escape_round_index]
            probe_total = 2 * len(self._basin_escape_directions)
            while self._basin_escape_probe_cursor < probe_total:
                cursor = self._basin_escape_probe_cursor
                self._basin_escape_probe_cursor += 1
                direction = self._basin_escape_directions[cursor // 2]
                polarity = -1.0 if cursor % 2 == 0 else 1.0
                probe = apply_block_escape_probe(
                    self._basin_escape_round_center or self._best_params,
                    coordinates=self._coordinates,
                    steps=self._steps,
                    direction=direction,
                    radius=radius,
                    polarity=polarity,
                )
                if probe is None:
                    continue
                candidate = copy.deepcopy(probe.candidate)
                changes = _diff_params(self._best_params, candidate)
                if not changes:
                    continue
                self._probe_count += 1
                self._basin_escape_probe_count += 1
                self._pending = {
                    "phase": self._phase,
                    "group": "basin_escape",
                    "round": self._basin_escape_round_index + 1,
                    "coordinate": "__basin_escape_block__",
                    "coordinates": list(probe.normalized_updates),
                    "direction": polarity,
                    "delta": None,
                    "probe_kind": "basin_escape_block_probe",
                    "direction_index": direction.direction_index,
                    "direction_seed": direction.seed,
                    "polarity": polarity,
                    "radius": radius,
                    "base_objective_score": self._best_objective_score,
                }
                return candidate, self._basin_escape_block_decision(
                    previous=previous,
                    direction=direction,
                    polarity=polarity,
                    radius=radius,
                    probe=probe,
                    candidate=candidate,
                    changes=changes,
                )

            if not self._basin_escape_response_built:
                self._basin_escape_response_moves = build_block_escape_response_moves(
                    self._basin_escape_round_center or self._best_params,
                    center_features=self._basin_escape_round_center_features,
                    coordinates=self._coordinates,
                    steps=self._steps,
                    radius=radius,
                    observations=self._basin_escape_observations(),
                    damping=self._basin_escape_damping,
                    ridge=self._basin_escape_ridge,
                    response_trust_radius=self._basin_escape_response_trust_radius,
                    response_line_search_scales=self._basin_escape_response_line_search_scales,
                )
                self._basin_escape_response_moves = [
                    move
                    for move in self._basin_escape_response_moves
                    if move.method in self._basin_escape_response_methods
                ]
                self._basin_escape_response_built = True
            while self._basin_escape_response_index < len(self._basin_escape_response_moves):
                move = self._basin_escape_response_moves[self._basin_escape_response_index]
                self._basin_escape_response_index += 1
                candidate = copy.deepcopy(move.candidate)
                changes = _diff_params(self._best_params, candidate)
                if not changes:
                    continue
                self._probe_count += 1
                self._basin_escape_probe_count += 1
                self._basin_escape_response_probe_count += 1
                self._pending = {
                    "phase": self._phase,
                    "group": "basin_escape",
                    "round": self._basin_escape_round_index + 1,
                    "coordinate": "__basin_escape_response__",
                    "coordinates": list(move.coordinate_ids),
                    "direction": 1.0,
                    "delta": None,
                    "probe_kind": "basin_escape_response",
                    "response_method": move.method,
                    "radius": radius,
                    "base_objective_score": self._best_objective_score,
                }
                return candidate, self._basin_escape_response_decision(
                    previous=previous,
                    move=move,
                    radius=radius,
                    candidate=candidate,
                    changes=changes,
                )
            self._finish_basin_escape_round()

        if self._basin_escape_return_phase == "ranked_refinement":
            self._enter_ranked_refinement()
            return self._next_ranked_candidate(previous)
        self._phase = "broad_groups"
        self._reset_coordinate_probe()
        return self._next_broad_candidate(previous)

    def _start_basin_escape_round(self) -> None:
        direction_builder = (
            build_coordinate_escape_directions
            if self._basin_escape_direction_design == "coordinate_basis_v1"
            else build_block_escape_directions
        )
        self._basin_escape_directions = direction_builder(
            coordinates=self._coordinates,
            pair_count=self._basin_escape_pair_count,
            round_index=self._basin_escape_round_index,
            seed=self._basin_escape_seed,
        )
        pair_limit = self._basin_escape_round_pair_counts[
            self._basin_escape_round_index
        ]
        self._basin_escape_directions = self._basin_escape_directions[:pair_limit]
        self._basin_escape_probe_cursor = 0
        self._basin_escape_round_center = copy.deepcopy(self._best_params)
        self._basin_escape_round_center_features = copy.deepcopy(self._best_features)
        self._basin_escape_observation_parts = {}
        self._basin_escape_response_moves = []
        self._basin_escape_response_index = 0
        self._basin_escape_response_built = False

    def _finish_basin_escape_round(self) -> None:
        self._basin_escape_round_index += 1
        self._basin_escape_directions = []
        self._basin_escape_probe_cursor = 0
        self._basin_escape_round_center = None
        self._basin_escape_round_center_features = None
        self._basin_escape_observation_parts = {}
        self._basin_escape_response_moves = []
        self._basin_escape_response_index = 0
        self._basin_escape_response_built = False

    def _basin_escape_observations(self) -> list[BlockEscapeObservation]:
        observations: list[BlockEscapeObservation] = []
        for direction in self._basin_escape_directions:
            pair = self._basin_escape_observation_parts.get(direction.direction_index, {})
            minus = pair.get(-1.0)
            plus = pair.get(1.0)
            if minus is None or plus is None:
                continue
            observations.append(
                BlockEscapeObservation(
                    direction=direction,
                    minus_params=copy.deepcopy(minus["params"]),
                    plus_params=copy.deepcopy(plus["params"]),
                    minus_fit_score=float(minus["fit_score"]),
                    plus_fit_score=float(plus["fit_score"]),
                    minus_objective_score=float(minus["objective_score"]),
                    plus_objective_score=float(plus["objective_score"]),
                    minus_features=copy.deepcopy(minus["features"]),
                    plus_features=copy.deepcopy(plus["features"]),
                )
            )
        return observations

    def _next_broad_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._phase == "broad_groups":
            if self._coordinate_index >= len(self._agenda):
                current_group = self._current_group_name()
                if (
                    current_group == "scene_alignment"
                    and self._scene_alignment_round < self._scene_alignment_rounds
                ):
                    self._scene_alignment_round += 1
                    self._agenda = list(self._groups[self._group_index][1])
                    self._coordinate_index = 0
                    self._reset_coordinate_probe()
                    continue
                if current_group == "scene_alignment":
                    self._scene_alignment_frozen = self._freeze_scene_after_alignment
                self._group_index += 1
                if self._group_index >= len(self._groups):
                    if (
                        self._basin_escape_activation_status
                        == "pending_after_broad_groups"
                        and self._activate_basin_escape(
                            float(self._best_fit_score or 0.0),
                            skipped_status="skipped_post_broad_fit_below_threshold",
                        )
                    ):
                        self._phase = "basin_escape"
                        self._basin_escape_return_phase = "ranked_refinement"
                        self._reset_coordinate_probe()
                        break
                    self._enter_ranked_refinement()
                    break
                self._agenda = list(self._groups[self._group_index][1])
                self._coordinate_index = 0
                self._reset_coordinate_probe()
                continue
            candidate = self._next_direction_candidate(previous)
            if candidate is not None:
                return candidate
            improved = self._finish_coordinate(
                shrink_on_failure=(
                    self._current_group_name() == "scene_alignment"
                    and self._scene_alignment_round > 1
                )
            )
            if (
                improved
                and self._current_group_name() != "scene_alignment"
                and self._broad_coordinate_repeat_index
                < self._broad_coordinate_max_repeats
            ):
                self._broad_coordinate_repeat_index += 1
                self._broad_coordinate_repeat_count += 1
                self._reset_coordinate_probe()
                continue
            self._coordinate_index += 1
            self._broad_coordinate_repeat_index = 0
            self._reset_coordinate_probe()
        if self._phase == "basin_escape":
            return self._next_basin_escape_candidate(previous)
        return self._next_ranked_candidate(previous)

    def _next_ranked_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        while self._stop_reason is None:
            if self._joint_probe_due:
                joint = self._joint_pattern_candidate(previous)
                if joint is not None:
                    return joint
            if self._coordinate_index >= len(self._agenda):
                if self._all_steps_at_min():
                    self._stop_reason = "structured_fish_step_limit"
                    return copy.deepcopy(self._best_params), self._stop_decision(previous)
                self._round_index += 1
                self._update_regularization_schedule()
                self._agenda = self._ranked_agenda()
                self._coordinate_index = 0
                self._reset_gauss_newton_trust_region()
                self._joint_probe_due = True
                self._reset_coordinate_probe()
                continue
            candidate = self._next_direction_candidate(previous)
            if candidate is not None:
                return candidate
            self._finish_coordinate(shrink_on_failure=True)
            self._coordinate_index += 1
            self._reset_coordinate_probe()
        return copy.deepcopy(self._best_params), self._stop_decision(previous)


    def _joint_pattern_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Probe a coupled direction assembled from measured 1D responses."""

        self._joint_probe_due = False
        gauss_newton = self._gauss_newton_candidate(previous)
        if gauss_newton is not None:
            return gauss_newton
        self._gauss_newton_repeat_index = 0
        move = build_joint_pattern_move(
            best_params=self._best_params,
            coordinates=self._ranked_pool_coordinates(),
            response=self._response,
            steps=self._steps,
            move_scale=self._pattern_move_scale,
        )
        if move is None:
            return None
        candidate, coordinate_ids = move

        self._probe_count += 1
        self._joint_probe_count += 1
        self._pending = {
            "phase": self._phase,
            "group": "joint_pattern",
            "round": self._round_index,
            "coordinate": "__joint__",
            "coordinates": coordinate_ids,
            "direction": self._pattern_move_scale,
            "delta": None,
            "probe_kind": "joint_pattern",
            "base_objective_score": self._best_objective_score,
        }
        return candidate, {
            "optimizer": self.name,
            "stage": {
                "name": "structured_fish_joint_pattern_probe",
                "description": "Coupled response direction over the strongest material coordinates",
            },
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": "joint_pattern",
                "round": self._round_index,
                "probe_kind": "joint_pattern",
                "pattern_move_scale": self._pattern_move_scale,
                "coordinates": coordinate_ids,
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "previous_candidate": previous,
            },
            "changes": _diff_params(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _gauss_newton_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self._best_features is None or len(self._jacobian_columns) < 2:
            return None
        move = solve_gauss_newton_move(
            best_params=self._best_params,
            residual_features=self._best_features,
            coordinates=self._ranked_pool_coordinates(),
            jacobian_columns=self._jacobian_columns,
            steps=self._steps,
            damping=self._current_gauss_newton_damping,
            ridge=self._gauss_newton_ridge,
        )
        if move is None:
            return None
        candidate = move.candidate
        coordinate_ids = move.coordinate_ids
        normalized_updates = move.normalized_updates
        applied_trust_steps = move.applied_steps
        feature_count = len(self._best_features)
        damping = self._current_gauss_newton_damping
        repeat_index = self._gauss_newton_repeat_index
        self._probe_count += 1
        self._joint_probe_count += 1
        self._gauss_newton_probe_count += 1
        self._coordinates_since_joint = 0
        if repeat_index > 0:
            self._gauss_newton_repeat_probe_count += 1
        self._pending = {
            "phase": self._phase,
            "group": "gauss_newton",
            "round": self._round_index,
            "coordinate": "__gauss_newton__",
            "coordinates": coordinate_ids,
            "direction": 1.0,
            "delta": None,
            "probe_kind": "gauss_newton",
            "repeat_index": repeat_index,
            "damping": damping,
            "base_objective_score": self._best_objective_score,
        }
        return candidate, {
            "optimizer": self.name,
            "stage": {
                "name": "structured_fish_gauss_newton_probe",
                "description": "Damped least-squares update from signed multiview image residuals",
            },
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": "gauss_newton",
                "round": self._round_index,
                "probe_kind": "gauss_newton",
                "repeat_index": repeat_index,
                "coordinates": coordinate_ids,
                "normalized_updates": normalized_updates,
                "trust_steps": applied_trust_steps,
                "damping": damping,
                "ridge": self._gauss_newton_ridge,
                "feature_count": feature_count,
                "jacobian_column_count": move.jacobian_column_count,
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "previous_candidate": previous,
            },
            "changes": _diff_params(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _next_direction_candidate(
        self,
        previous: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        coordinate = self._agenda[self._coordinate_index]
        if (
            self._phase == "ranked_refinement"
            and self._opportunistic_ranked_accept
            and self._direction_index > 0
            and self._local_best_score is not None
            and self._best_objective_score is not None
            and self._local_best_score > self._best_objective_score + _EPS
        ):
            self._opportunistic_skip_count += len(_DIRECTIONS) - self._direction_index
            self._interpolation_attempted = True
            return None
        while self._direction_index < len(_DIRECTIONS):
            direction = self._probe_direction(coordinate, self._direction_index)
            self._direction_index += 1
            before = coordinate.read(self._best_params)
            candidate = coordinate.write(
                self._best_params,
                before + direction * self._steps[coordinate.coordinate_id],
            )
            after = coordinate.read(candidate)
            if abs(after - before) <= 1.0e-12:
                continue
            delta = after - before
            self._probe_count += 1
            proposal_round = self._coordinate_round(coordinate)
            self._pending = {
                "phase": self._phase,
                "group": coordinate.group,
                "round": proposal_round,
                "coordinate": coordinate.coordinate_id,
                "direction": direction,
                "delta": delta,
                "probe_kind": "axis",
                "base_objective_score": self._best_objective_score,
            }
            return candidate, self._probe_decision(
                previous=previous,
                coordinate=coordinate,
                direction=direction,
                delta=delta,
                candidate=candidate,
                probe_kind="axis",
            )
        return self._parabolic_candidate(previous, coordinate)

    def _parabolic_candidate(
        self,
        previous: dict[str, Any] | None,
        coordinate: FishSearchCoordinate,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Estimate a continuous 1D maximum from the two axis probes."""

        if self._interpolation_attempted:
            return None
        self._interpolation_attempted = True
        if self._best_objective_score is None or any(
            direction not in self._probe_scores for direction in _DIRECTIONS
        ):
            return None
        minus = self._probe_scores[-1.0]
        plus = self._probe_scores[1.0]
        base = self._best_objective_score
        denominator = minus - 2.0 * base + plus
        if not math.isfinite(denominator) or denominator >= -_EPS:
            return None
        step = self._steps[coordinate.coordinate_id]
        offset = step * (minus - plus) / (2.0 * denominator)
        offset = min(max(offset, -2.0 * step), 2.0 * step)
        if abs(offset) <= 0.05 * step or abs(abs(offset) - step) <= 0.05 * step:
            return None
        before = coordinate.read(self._best_params)
        candidate = coordinate.write(self._best_params, before + offset)
        after = coordinate.read(candidate)
        if abs(after - before) <= 1.0e-12:
            return None
        delta = after - before
        direction = delta / step
        self._probe_count += 1
        proposal_round = self._coordinate_round(coordinate)
        self._pending = {
            "phase": self._phase,
            "group": coordinate.group,
            "round": proposal_round,
            "coordinate": coordinate.coordinate_id,
            "direction": direction,
            "delta": delta,
            "probe_kind": "parabolic",
            "base_objective_score": self._best_objective_score,
        }
        return candidate, self._probe_decision(
            previous=previous,
            coordinate=coordinate,
            direction=direction,
            delta=delta,
            candidate=candidate,
            probe_kind="parabolic",
        )

    def _finish_coordinate(self, *, shrink_on_failure: bool) -> bool:
        self._update_jacobian_column(self._agenda[self._coordinate_index])
        if self._phase == "ranked_refinement":
            self._coordinates_since_joint += 1
            if (
                self._coordinates_since_joint >= self._effective_gauss_newton_interval()
                and self._best_features is not None
                and len(self._jacobian_columns) >= 2
            ):
                self._joint_probe_due = True
        if self._local_best_score is None or self._best_objective_score is None:
            return False
        if self._local_best_score <= self._best_objective_score + _EPS:
            if shrink_on_failure:
                self._shrink_coordinate(self._agenda[self._coordinate_index])
            return False
        self._best_objective_score = self._local_best_score
        self._best_fit_score = self._local_best_raw_score
        self._best_params = copy.deepcopy(self._local_best_params or self._best_params)
        self._best_features = copy.deepcopy(self._local_best_features)
        self._maybe_disable_regularization(float(self._best_fit_score))
        self._accept_count += 1
        return True

    def _reset_coordinate_probe(self) -> None:
        self._direction_index = 0
        self._local_best_score = self._best_objective_score
        self._local_best_raw_score = self._best_fit_score
        self._local_best_params = copy.deepcopy(self._best_params)
        self._local_best_features = copy.deepcopy(self._best_features)
        self._probe_scores = {}
        self._probe_feature_samples = {}
        self._interpolation_attempted = False

    def _reset_gauss_newton_trust_region(self) -> None:
        self._current_gauss_newton_damping = self._gauss_newton_damping
        self._gauss_newton_repeat_index = 0

    def _high_score_gauss_newton_active(self) -> bool:
        return bool(
            self._best_fit_score is not None
            and self._best_fit_score >= self._gauss_newton_high_score_threshold
        )

    def _effective_gauss_newton_interval(self) -> int:
        return (
            self._gauss_newton_high_score_interval
            if self._high_score_gauss_newton_active()
            else self._gauss_newton_interval
        )

    def _effective_gauss_newton_max_repeats(self) -> int:
        return (
            self._gauss_newton_high_score_max_repeats
            if self._high_score_gauss_newton_active()
            else self._gauss_newton_max_repeats
        )

    def _update_regularization_schedule(self) -> None:
        if self._regularization_disabled_by_score:
            return
        exponent = max(self._round_index - 1, 0)
        next_weight = max(
            self._regularization_final_weight,
            self._initial_regularization_weight * self._regularization_decay**exponent,
        )
        if abs(next_weight - self._regularization_weight) <= 1.0e-12:
            return
        self._regularization_weight = next_weight
        if self._best_fit_score is not None:
            self._best_objective_score = self._objective_score(
                self._best_params,
                self._best_fit_score,
            )

    def _maybe_disable_regularization(self, fit_score: float) -> bool:
        threshold = self._regularization_disable_score
        if (
            threshold is None
            or self._regularization_disabled_by_score
            or float(fit_score) + _EPS < threshold
        ):
            return False
        self._regularization_disabled_by_score = True
        self._regularization_disable_trigger_score = float(fit_score)
        self._regularization_weight = 0.0
        if self._best_fit_score is not None:
            self._best_objective_score = self._objective_score(
                self._best_params,
                self._best_fit_score,
            )
        return True

    def _update_jacobian_column(self, coordinate: FishSearchCoordinate) -> None:
        minus = self._probe_feature_samples.get(-1.0)
        plus = self._probe_feature_samples.get(1.0)
        if minus is None or plus is None:
            return
        minus_delta, minus_features = minus
        plus_delta, plus_features = plus
        denominator = plus_delta - minus_delta
        if abs(denominator) <= 1.0e-12 or len(minus_features) != len(plus_features):
            return
        derivative = [
            (plus_value - minus_value) / denominator
            for minus_value, plus_value in zip(minus_features, plus_features)
        ]
        if derivative and all(math.isfinite(value) for value in derivative):
            self._jacobian_columns[coordinate.coordinate_id] = derivative

    def _probe_direction(self, coordinate: FishSearchCoordinate, index: int) -> float:
        if self._phase != "ranked_refinement":
            return _DIRECTIONS[index]
        best_direction = self._response[coordinate.coordinate_id].get("best_direction")
        if best_direction in _DIRECTIONS:
            return float(best_direction if index == 0 else -best_direction)
        return _DIRECTIONS[index]

    def _ranked_coordinates(self, limit: int) -> list[FishSearchCoordinate]:
        return rank_coordinates(self._ranked_pool_coordinates(), self._response)[:limit]

    def _ranked_agenda(self) -> list[FishSearchCoordinate]:
        pool = self._ranked_pool_coordinates()
        return self._ranked_coordinates(len(pool))

    def _ranked_pool_coordinates(self) -> list[FishSearchCoordinate]:
        if not self._scene_alignment_frozen:
            return list(self._coordinates)
        return [
            coordinate
            for coordinate in self._coordinates
            if coordinate.group != "scene_alignment"
        ]

    def _shrink_coordinate(self, coordinate: FishSearchCoordinate) -> None:
        coordinate_id = coordinate.coordinate_id
        old = self._steps[coordinate_id]
        self._steps[coordinate_id] = max(old * 0.5, coordinate.min_step)
        if self._steps[coordinate_id] < old - 1.0e-12:
            self._shrink_count += 1

    def _all_steps_at_min(self) -> bool:
        coordinates = self._agenda if self._phase == "ranked_refinement" else self._coordinates
        return all(
            self._steps[coordinate.coordinate_id] <= coordinate.min_step + 1.0e-12
            for coordinate in coordinates
        )

    def _current_group_name(self) -> str | None:
        if self._phase == "broad_groups" and self._group_index < len(self._groups):
            return self._groups[self._group_index][0]
        return None

    def _probe_decision(
        self,
        *,
        previous: dict[str, Any] | None,
        coordinate: FishSearchCoordinate,
        direction: float,
        delta: float,
        candidate: dict[str, Any],
        probe_kind: str,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"structured_fish_{coordinate.group}_probe",
                "description": "Target-independent black-box coordinate probe",
            },
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": coordinate.group,
                "round": self._coordinate_round(coordinate),
                "coordinate_index": self._coordinate_index,
                "coordinate": coordinate.coordinate_id,
                "param": coordinate.param_name,
                "component": coordinate.component,
                "direction": direction,
                "probe_kind": probe_kind,
                "delta": delta,
                "step": self._steps[coordinate.coordinate_id],
                "bounds": [coordinate.low, coordinate.high],
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "regularization_weight": self._regularization_weight,
                "initial_distance": self._normalized_initial_distance(candidate),
                "previous_candidate": previous,
            },
            "changes": _diff_params(self._best_params, candidate),
            "stop_reason": "continue",
        }

    def _coordinate_round(self, coordinate: FishSearchCoordinate) -> int:
        if coordinate.group == SCENE_ALIGNMENT_GROUP:
            return self._scene_alignment_round
        return self._round_index

    def _basin_escape_block_decision(
        self,
        *,
        previous: dict[str, Any] | None,
        direction: BlockEscapeDirection,
        polarity: float,
        radius: float,
        probe: BlockEscapeProbe,
        candidate: dict[str, Any],
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "structured_fish_basin_escape_block_probe",
                "description": "Antithetic coupled probe over the public material space",
            },
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": "basin_escape",
                "round": self._basin_escape_round_index + 1,
                "probe_kind": "basin_escape_block_probe",
                "escape_profile": "antithetic_block_secant_v1",
                "direction_design": self._basin_escape_direction_design,
                "direction_index": direction.direction_index,
                "direction_seed": direction.seed,
                "polarity": polarity,
                "radius": radius,
                "coordinates": list(probe.normalized_updates),
                "normalized_updates": dict(probe.normalized_updates),
                "feedback_source": "online_target_png_score_and_residuals",
                "target_params_visible": False,
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "regularization_weight": self._regularization_weight,
                "initial_distance": self._normalized_initial_distance(candidate),
                "previous_candidate": previous,
            },
            "changes": changes,
            "stop_reason": "continue",
        }

    def _basin_escape_response_decision(
        self,
        *,
        previous: dict[str, Any] | None,
        move: BlockEscapeResponseMove,
        radius: float,
        candidate: dict[str, Any],
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": "structured_fish_basin_escape_response_probe",
                "description": "Coupled response reconstructed from antithetic image probes",
            },
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": "basin_escape",
                "round": self._basin_escape_round_index + 1,
                "probe_kind": "basin_escape_response",
                "escape_profile": "antithetic_block_secant_v1",
                "direction_design": self._basin_escape_direction_design,
                "response_method": move.method,
                "radius": radius,
                "coordinates": list(move.coordinate_ids),
                "normalized_updates": dict(move.normalized_updates),
                "direction_count": move.direction_count,
                "residual_feature_count": move.residual_feature_count,
                "feedback_source": "online_target_png_score_and_residuals",
                "target_params_visible": False,
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "regularization_weight": self._regularization_weight,
                "initial_distance": self._normalized_initial_distance(candidate),
                "previous_candidate": previous,
            },
            "changes": changes,
            "stop_reason": "continue",
        }

    def _stop_decision(self, previous: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None,
            "structured_fish": {
                "profile": "structured_fish_v1",
                "phase": self._phase,
                "group": self._current_group_name(),
                "round": self._round_index,
                "best_fit_score": self._best_fit_score,
                "best_objective_score": self._best_objective_score,
                "accept_count": self._accept_count,
                "probe_count": self._probe_count,
                "shrink_count": self._shrink_count,
                "joint_probe_count": self._joint_probe_count,
                "joint_accept_count": self._joint_accept_count,
                "gauss_newton_probe_count": self._gauss_newton_probe_count,
                "gauss_newton_accept_count": self._gauss_newton_accept_count,
                "gauss_newton_repeat_probe_count": self._gauss_newton_repeat_probe_count,
                "gauss_newton_repeat_accept_count": self._gauss_newton_repeat_accept_count,
                "basin_escape_enabled": self._basin_escape_enabled,
                "basin_escape_probe_count": self._basin_escape_probe_count,
                "basin_escape_accept_count": self._basin_escape_accept_count,
                "basin_escape_response_probe_count": self._basin_escape_response_probe_count,
                "basin_escape_response_accept_count": self._basin_escape_response_accept_count,
                "opportunistic_ranked_accept": self._opportunistic_ranked_accept,
                "opportunistic_skip_count": self._opportunistic_skip_count,
                "previous_candidate": previous,
            },
            "changes": [],
            "stop_reason": self._stop_reason or "structured_fish_stopped",
        }

    def _objective_score(self, params: dict[str, Any], fit_score: float) -> float:
        return float(fit_score) - self._regularization_weight * self._normalized_initial_distance(params)

    def _normalized_initial_distance(self, params: dict[str, Any]) -> float:
        return normalized_coordinate_distance(
            params,
            self._initial_params,
            self._coordinates,
        )




__all__ = ["StructuredFishStrategy"]
