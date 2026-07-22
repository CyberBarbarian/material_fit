"""PNG-only Stage 1 optimizer shared by material assets."""

from __future__ import annotations

import copy
import math
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .cmaes_strategy import CmaesStrategy
from .material_coordinate_pattern_strategy import MaterialCoordinatePatternStrategy
from .material_jacobian_trust_region_strategy import MaterialJacobianTrustRegionStrategy
from .material_secant_trust_region_strategy import MaterialSecantTrustRegionStrategy
from .material_semantic_blocks import MATERIAL_SEMANTIC_BLOCK_BY_NAME
from .strategy_core import CmaesStrategyConfig, OptimizerStrategy, StrategyContext
from .structured_fish_strategy import StructuredFishStrategy
from .structured_fish_space import structured_fish_coordinates
from .structured_material_space import STRUCTURED_SCENE_PARAM_NAMES


DEFAULT_STAGE1_BLOCK_ORDER = ("rim", "specular", "tone_shadow", "base_surface")


class MaterialStage1HybridStrategy(OptimizerStrategy):
    """Run structured warmup, semantic blocks, and adaptive late alignment.

    The orchestration reproduces the successful historical Stage 1 sequence,
    but receives no target parameters. Each stage starts from the best point
    established through online PNG score and residual feedback. If the first
    material refinement remains below the configured online score threshold,
    scene lighting is realigned once more from the materially closer state,
    frozen, and followed by a final material-only polish.
    """

    name = "material_stage1_hybrid"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        self._initial_params = copy.deepcopy(initial_params)
        self._shader_params = list(shader_params)
        self._search_param_names = [
            name
            for name in dict.fromkeys(search_param_names or initial_params)
            if name in initial_params
        ]
        scene_names = set(STRUCTURED_SCENE_PARAM_NAMES)
        self._material_param_names = [
            name for name in self._search_param_names if name not in scene_names
        ]
        if not self._material_param_names:
            raise ValueError("material_stage1_hybrid has no searchable material parameters")

        configured_order = tuple(str(name) for name in cfg.get("block_order", DEFAULT_STAGE1_BLOCK_ORDER))
        unknown = [name for name in configured_order if name not in MATERIAL_SEMANTIC_BLOCK_BY_NAME]
        if unknown:
            raise ValueError(f"unknown material semantic blocks: {unknown}")
        sigma_scale = _positive_float(cfg.get("sigma_scale"), 1.0)
        allowed = set(self._material_param_names)
        self._blocks: list[tuple[str, list[str], float]] = []
        for name in configured_order:
            block_names, default_sigma = MATERIAL_SEMANTIC_BLOCK_BY_NAME[name]
            names = [param_name for param_name in block_names if param_name in allowed]
            if names:
                self._blocks.append((name, names, min(default_sigma * sigma_scale, 1.0)))
        if not self._blocks:
            raise ValueError("material_stage1_hybrid has no searchable semantic blocks")

        self._warmup_iterations = max(int(cfg.get("warmup_iterations", 1000)), 1)
        self._block_iterations = max(int(cfg.get("block_iterations", 400)), 1)
        self._refine_iterations = max(int(cfg.get("refine_iterations", 800)), 1)
        self._late_scene_realign_iterations = max(
            int(cfg.get("late_scene_realign_iterations", 256)),
            1,
        )
        self._late_material_polish_iterations = max(
            int(cfg.get("late_material_polish_iterations", 800)),
            1,
        )
        self._late_realign_trigger_score = _unit_interval_float(
            cfg.get("late_realign_trigger_score"),
            0.985,
        )
        self._local_jacobian_iterations = max(
            int(cfg.get("local_jacobian_iterations", 800)),
            1,
        )
        self._local_jacobian_trigger_score = _unit_interval_float(
            cfg.get("local_jacobian_trigger_score"),
            0.995,
        )
        raw_local_jacobian = cfg.get("local_jacobian")
        self._local_jacobian_config = (
            copy.deepcopy(raw_local_jacobian)
            if isinstance(raw_local_jacobian, dict)
            else {}
        )
        self._local_refiner_strategy = str(
            cfg.get("local_refiner_strategy", "material_jacobian_trust_region")
        )
        if self._local_refiner_strategy not in {
            "material_jacobian_trust_region",
            "material_secant_trust_region",
        }:
            raise ValueError(
                "unknown Stage 1 local refiner: "
                f"{self._local_refiner_strategy}"
            )
        raw_local_refiner = cfg.get("local_refiner")
        self._local_refiner_config = (
            copy.deepcopy(raw_local_refiner)
            if isinstance(raw_local_refiner, dict)
            else copy.deepcopy(self._local_jacobian_config)
        )
        self._terminal_pattern_iterations = max(
            int(cfg.get("terminal_pattern_iterations", 0)),
            0,
        )
        raw_terminal_pattern = cfg.get("terminal_pattern")
        self._terminal_pattern_config = (
            copy.deepcopy(raw_terminal_pattern)
            if isinstance(raw_terminal_pattern, dict)
            else {}
        )
        self._refine_gauss_newton_high_score_threshold = _unit_interval_float(
            cfg.get("refine_gauss_newton_high_score_threshold"),
            1.0,
        )
        self._refine_gauss_newton_high_score_interval = max(
            int(cfg.get("refine_gauss_newton_high_score_interval", 16)),
            1,
        )
        self._refine_gauss_newton_high_score_max_repeats = max(
            int(cfg.get("refine_gauss_newton_high_score_max_repeats", 2)),
            0,
        )
        self._refine_regularization_weight = _nonnegative_float(
            cfg.get("refine_regularization_weight"),
            0.01,
        )
        self._refine_regularization_final_weight = min(
            _nonnegative_float(
                cfg.get("refine_regularization_final_weight"),
                0.0,
            ),
            self._refine_regularization_weight,
        )
        self._refine_regularization_decay = _unit_interval_float(
            cfg.get("refine_regularization_decay"),
            0.5,
        )
        raw_regularization_disable_score = cfg.get("refine_regularization_disable_score")
        self._refine_regularization_disable_score = (
            _unit_interval_float(raw_regularization_disable_score, 1.0)
            if raw_regularization_disable_score is not None
            else None
        )
        self._population_size = max(int(cfg.get("population_size", 16)), 2)
        self._seed = int(cfg.get("seed", 20260714))
        self._structured_only = bool(cfg.get("structured_only", False))
        warmup_escape = cfg.get("warmup_basin_escape")
        warmup_escape = warmup_escape if isinstance(warmup_escape, dict) else {}
        self._warmup_basin_escape_enabled = bool(warmup_escape.get("enabled", False))
        self._warmup_basin_escape_pair_count = max(
            int(warmup_escape.get("pair_count", 40)),
            1,
        )
        self._warmup_basin_escape_round_pair_counts = tuple(
            max(int(value), 1)
            for value in warmup_escape.get("round_pair_counts", (40, 40))
        )
        self._warmup_basin_escape_radii = tuple(
            value
            for raw in warmup_escape.get("radii", (2.5, 1.0))
            if math.isfinite(value := float(raw)) and value > 0.0
        )
        self._warmup_basin_escape_activation_min_fit_score = _unit_interval_float(
            warmup_escape.get("activation_min_fit_score"),
            0.80,
        )
        self._warmup_basin_escape_seed = int(warmup_escape.get("seed", 1701))
        refine_escape = cfg.get("refine_basin_escape")
        refine_escape = refine_escape if isinstance(refine_escape, dict) else {}
        self._refine_basin_escape_enabled = bool(refine_escape.get("enabled", True))
        self._refine_basin_escape_pair_count = max(
            int(refine_escape.get("pair_count", 40)),
            1,
        )
        self._refine_basin_escape_round_pair_counts = tuple(
            max(int(value), 1)
            for value in refine_escape.get("round_pair_counts", (40, 40))
        )
        self._refine_basin_escape_radii = tuple(
            value
            for raw in refine_escape.get("radii", (1.0, 0.5))
            if math.isfinite(value := float(raw)) and value > 0.0
        )
        self._refine_basin_escape_damping = _positive_float(
            refine_escape.get("damping"),
            0.8,
        )
        self._refine_basin_escape_ridge = max(
            float(refine_escape.get("ridge", 0.001)),
            0.0,
        )
        self._refine_basin_escape_activation_min_fit_score = _unit_interval_float(
            refine_escape.get("activation_min_fit_score"),
            0.0,
        )
        self._refine_basin_escape_activation_mode = str(
            refine_escape.get("activation_mode", "initial")
        )
        self._refine_basin_escape_disable_opportunistic_when_skipped = bool(
            refine_escape.get("disable_opportunistic_when_skipped", False)
        )
        self._refine_basin_escape_response_methods = tuple(
            str(value)
            for value in refine_escape.get(
                "response_methods",
                ("residual_block_secant", "scalar_score_response"),
            )
        )
        self._refine_basin_escape_direction_design = str(
            refine_escape.get("direction_design", "coordinate_basis_v1")
        )
        raw_refine_trust_radius = refine_escape.get("response_trust_radius", 4.0)
        self._refine_basin_escape_response_trust_radius = (
            None
            if raw_refine_trust_radius is None
            else _positive_float(raw_refine_trust_radius, 4.0)
        )
        self._refine_basin_escape_response_line_search_scales = tuple(
            value
            for raw in refine_escape.get(
                "response_line_search_scales",
                (1.0, 0.5, 0.25, 0.125, -0.125, -0.25, -0.5, -1.0),
            )
            if math.isfinite(value := float(raw)) and abs(value) > 1.0e-12
        )
        self._refine_basin_escape_opportunistic_ranked_accept = bool(
            refine_escape.get("opportunistic_ranked_accept", True)
        )
        raw_refine_seed = refine_escape.get("seed")
        self._refine_basin_escape_seed = (
            int(raw_refine_seed) if raw_refine_seed is not None else None
        )
        self._profile = str(
            cfg.get("profile")
            or (
                "material_stage1_hybrid_v4_budgeted_structured"
                if self._structured_only
                else "material_stage1_hybrid_v3_scene_frozen_local_jacobian"
            )
        )
        scalar_coordinates = {
            coordinate.param_name: coordinate
            for coordinate in structured_fish_coordinates(
                self._initial_params,
                shader_params=self._shader_params,
                search_param_names=self._material_param_names,
            )
            if coordinate.component is None
        }
        self._scalar_grid_scans: list[dict[str, Any]] = []
        raw_scalar_scans = cfg.get("scalar_grid_scans")
        if isinstance(raw_scalar_scans, list):
            for raw_scan in raw_scalar_scans:
                if not isinstance(raw_scan, dict):
                    continue
                param_name = str(raw_scan.get("param_name") or "")
                coordinate = scalar_coordinates.get(param_name)
                if coordinate is None:
                    continue
                values: list[float] = []
                for raw_value in raw_scan.get("values", ()):
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    if not math.isfinite(value):
                        continue
                    clamped = min(max(value, coordinate.low), coordinate.high)
                    if not values or all(abs(clamped - item) > 1.0e-12 for item in values):
                        values.append(clamped)
                if values:
                    self._scalar_grid_scans.append(
                        {
                            "param_name": param_name,
                            "values": values,
                            "bounds": [coordinate.low, coordinate.high],
                        }
                    )

        self._best_params = copy.deepcopy(initial_params)
        self._best_fit_score = -math.inf
        self._best_analysis: dict[str, Any] = {}
        self._active: OptimizerStrategy | None = None
        self._active_kind: str | None = None
        self._active_name: str | None = None
        self._active_budget = 0
        self._active_fresh = False
        self._stage_index = 0
        self._stage_proposals = 0
        self._stage_start_score = -math.inf
        self._stage_summaries: list[dict[str, Any]] = []
        self._scalar_scan_index = 0
        self._scalar_scan_value_index = 0
        self._scalar_scan_base_params: dict[str, Any] | None = None
        self._scalar_scan_start_score = -math.inf
        self._scalar_scan_best_score = -math.inf
        self._scalar_scan_best_value: float | None = None
        self._scalar_scan_pending_value: float | None = None
        self._scalar_scan_summaries: list[dict[str, Any]] = []
        self._late_realign_activated = False
        self._late_realign_skipped = False
        self._local_jacobian_activated = False
        self._local_jacobian_completed = False
        self._terminal_pattern_activated = False
        self._terminal_pattern_completed = False
        self._finished = False

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return "material_stage1_hybrid_complete" if self._finished else None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._observe(ctx)
        if self._active is None and self._scalar_scan_index < len(self._scalar_grid_scans):
            candidate = self._propose_scalar_grid_scan()
            if candidate is not None:
                return candidate
        if self._active is not None and (
            self._stage_proposals >= self._active_budget
            or self._active.stop_reason() is not None
        ):
            self._finish_active_stage()
        if self._active is None and not self._finished:
            self._start_next_stage()
        if self._finished or self._active is None:
            return copy.deepcopy(self._best_params), self._decision({}, stop=True)

        active_ctx = self._best_context(ctx) if self._active_fresh else ctx
        self._active_fresh = False
        candidate, nested = self._active.propose(active_ctx)
        self._stage_proposals += 1
        return candidate, self._decision(nested, stop=False)

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": self._profile,
            "asset_independent": True,
            "stage_order": (
                [
                    *[
                        f"scalar_grid_scan_{scan['param_name']}"
                        for scan in self._scalar_grid_scans
                    ],
                    "structured_scene_material_warmup",
                ]
                if self._structured_only
                else [
                    *[
                        f"scalar_grid_scan_{scan['param_name']}"
                        for scan in self._scalar_grid_scans
                    ],
                    "structured_scene_material_warmup",
                    *[f"semantic_cma_{name}" for name, _names, _sigma in self._blocks],
                    "structured_material_refine",
                    "conditional_late_scene_realign",
                    "conditional_late_material_polish",
                    "conditional_local_material_jacobian",
                    "optional_terminal_material_pattern",
                ]
            ),
            "warmup_iterations": self._warmup_iterations,
            "scalar_grid_scans": {
                "configured": copy.deepcopy(self._scalar_grid_scans),
                "completed": copy.deepcopy(self._scalar_scan_summaries),
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "warmup_basin_escape": {
                "enabled": self._warmup_basin_escape_enabled,
                "direction_design": "full_rank_hadamard_v1",
                "pair_count": self._warmup_basin_escape_pair_count,
                "round_pair_counts": list(self._warmup_basin_escape_round_pair_counts),
                "radii": list(self._warmup_basin_escape_radii),
                "activation_min_fit_score": (
                    self._warmup_basin_escape_activation_min_fit_score
                ),
                "seed": self._warmup_basin_escape_seed,
                "target_params_visible": False,
            },
            "refine_basin_escape": {
                "enabled": self._refine_basin_escape_enabled,
                "direction_design": self._refine_basin_escape_direction_design,
                "pair_count": self._refine_basin_escape_pair_count,
                "round_pair_counts": list(
                    self._refine_basin_escape_round_pair_counts
                ),
                "radii": list(self._refine_basin_escape_radii),
                "damping": self._refine_basin_escape_damping,
                "ridge": self._refine_basin_escape_ridge,
                "activation_min_fit_score": (
                    self._refine_basin_escape_activation_min_fit_score
                ),
                "activation_mode": self._refine_basin_escape_activation_mode,
                "response_methods": list(
                    self._refine_basin_escape_response_methods
                ),
                "response_trust_radius": (
                    self._refine_basin_escape_response_trust_radius
                ),
                "response_line_search_scales": list(
                    self._refine_basin_escape_response_line_search_scales
                ),
                "opportunistic_ranked_accept": (
                    self._refine_basin_escape_opportunistic_ranked_accept
                ),
                "seed": self._refine_basin_escape_seed,
                "feedback_source": "online_target_png_score_and_residuals_only",
                "target_params_visible": False,
            },
            "block_iterations": self._block_iterations,
            "refine_iterations": self._refine_iterations,
            "late_scene_realign_iterations": self._late_scene_realign_iterations,
            "late_material_polish_iterations": self._late_material_polish_iterations,
            "late_realign_trigger_score": self._late_realign_trigger_score,
            "late_realign_activated": self._late_realign_activated,
            "local_jacobian_iterations": self._local_jacobian_iterations,
            "local_jacobian_trigger_score": self._local_jacobian_trigger_score,
            "local_jacobian_activated": self._local_jacobian_activated,
            "local_refiner_strategy": self._local_refiner_strategy,
            "local_refiner": {
                **copy.deepcopy(self._local_refiner_config),
                "feedback_source": "online_target_png_score_and_residuals_only",
                "target_params_visible": False,
            },
            "local_jacobian": {
                **copy.deepcopy(self._local_jacobian_config),
                "feedback_source": "online_target_png_score_and_residuals_only",
                "target_params_visible": False,
            },
            "terminal_pattern_iterations": self._terminal_pattern_iterations,
            "terminal_pattern_activated": self._terminal_pattern_activated,
            "terminal_pattern_completed": self._terminal_pattern_completed,
            "terminal_pattern": {
                **copy.deepcopy(self._terminal_pattern_config),
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            },
            "refine_gauss_newton_high_score_threshold": (
                self._refine_gauss_newton_high_score_threshold
            ),
            "refine_gauss_newton_high_score_interval": (
                self._refine_gauss_newton_high_score_interval
            ),
            "refine_gauss_newton_high_score_max_repeats": (
                self._refine_gauss_newton_high_score_max_repeats
            ),
            "refine_regularization_weight": self._refine_regularization_weight,
            "refine_regularization_final_weight": (
                self._refine_regularization_final_weight
            ),
            "refine_regularization_decay": self._refine_regularization_decay,
            "refine_regularization_disable_score": (
                self._refine_regularization_disable_score
            ),
            "population_size": self._population_size,
            "feedback_source": "online_target_png_score_and_residuals_only",
            "target_params_visible": False,
            "active_kind": self._active_kind,
            "active_name": self._active_name,
            "active_stage_proposals": self._stage_proposals,
            "best_fit_score": self._best_fit_score,
            "completed_stages": copy.deepcopy(self._stage_summaries),
            "nested": self._active.research_summary() if self._active is not None else {},
            "stop_reason": self.stop_reason(),
        }

    def _observe(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if math.isfinite(score) and score > self._best_fit_score:
            self._best_fit_score = score
            self._best_params = copy.deepcopy(ctx.current_params)
            self._best_analysis = copy.deepcopy(ctx.analysis)
        if self._scalar_scan_pending_value is not None:
            if math.isfinite(score) and score > self._scalar_scan_best_score:
                self._scalar_scan_best_score = score
                self._scalar_scan_best_value = self._scalar_scan_pending_value
            self._scalar_scan_pending_value = None

    def _propose_scalar_grid_scan(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        while self._scalar_scan_index < len(self._scalar_grid_scans):
            scan = self._scalar_grid_scans[self._scalar_scan_index]
            values = scan["values"]
            if self._scalar_scan_base_params is None:
                self._scalar_scan_base_params = copy.deepcopy(self._best_params)
                self._scalar_scan_start_score = self._best_fit_score
                self._scalar_scan_best_score = -math.inf
                self._scalar_scan_best_value = None
                self._scalar_scan_value_index = 0
            if self._scalar_scan_value_index >= len(values):
                self._scalar_scan_summaries.append(
                    {
                        "param_name": scan["param_name"],
                        "values": list(values),
                        "bounds": list(scan["bounds"]),
                        "proposals": len(values),
                        "start_fit_score": self._scalar_scan_start_score,
                        "best_fit_score": self._scalar_scan_best_score,
                        "best_value": self._scalar_scan_best_value,
                        "gain": self._scalar_scan_best_score - self._scalar_scan_start_score,
                    }
                )
                self._scalar_scan_index += 1
                self._scalar_scan_base_params = None
                self._active_kind = None
                self._active_name = None
                self._active_budget = 0
                continue

            value = float(values[self._scalar_scan_value_index])
            self._scalar_scan_value_index += 1
            candidate = copy.deepcopy(self._scalar_scan_base_params)
            before = candidate[scan["param_name"]]
            candidate[scan["param_name"]] = value
            self._scalar_scan_pending_value = value
            self._active_kind = "scalar_grid_scan"
            self._active_name = f"scalar_grid_{scan['param_name']}"
            self._active_budget = len(values)
            self._stage_proposals = self._scalar_scan_value_index
            nested = {
                "scalar_grid_scan": {
                    "param_name": scan["param_name"],
                    "value": value,
                    "proposal": self._scalar_scan_value_index,
                    "budget": len(values),
                    "feedback_source": "online_target_png_score_only",
                    "target_params_visible": False,
                },
                "changes": [
                    {
                        "param": scan["param_name"],
                        "before": before,
                        "after": value,
                    }
                ],
            }
            return candidate, self._decision(nested, stop=False)
        return None

    def _start_next_stage(self) -> None:
        self._stage_proposals = 0
        self._stage_start_score = self._best_fit_score
        if self._terminal_pattern_completed:
            self._finish_pipeline()
            return
        if (
            self._local_jacobian_completed
            and self._terminal_pattern_iterations > 0
            and not self._terminal_pattern_activated
        ):
            self._active = self._terminal_material_pattern()
            self._active_kind = "terminal_material_pattern"
            self._active_name = "terminal_material_pattern"
            self._active_budget = self._terminal_pattern_iterations
            self._terminal_pattern_activated = True
            self._active_fresh = True
            return
        if self._structured_only and self._stage_index > 0:
            self._finish_pipeline()
            return
        if self._stage_index == 0:
            self._active = self._structured_warmup()
            self._active_kind = "structured_warmup"
            self._active_name = "scene_and_material"
            self._active_budget = self._warmup_iterations
        elif self._stage_index <= len(self._blocks):
            block_index = self._stage_index - 1
            name, search_names, sigma = self._blocks[block_index]
            coordinates = structured_fish_coordinates(
                self._best_params,
                shader_params=self._shader_params,
                search_param_names=search_names,
            )
            axis_bounds = {
                coordinate.coordinate_id: (coordinate.low, coordinate.high)
                for coordinate in coordinates
            }
            self._active = CmaesStrategy(
                initial_params=self._best_params,
                shader_params=self._shader_params,
                config=CmaesStrategyConfig(
                    mode="cold",
                    population_size=self._population_size,
                    sigma=sigma,
                    seed=self._seed + block_index,
                    hint_bias_mix_ratio=0.0,
                ),
                param_whitelist=search_names,
                axis_bounds=axis_bounds,
            )
            self._active_kind = "semantic_cma"
            self._active_name = name
            self._active_budget = self._block_iterations
        elif self._stage_index == len(self._blocks) + 1:
            self._active = self._structured_material_refine()
            self._active_kind = "structured_refine"
            self._active_name = "material_only"
            self._active_budget = self._refine_iterations
        elif self._stage_index == len(self._blocks) + 2:
            if self._best_fit_score >= self._late_realign_trigger_score:
                self._late_realign_skipped = True
                if not self._start_local_jacobian_if_needed():
                    return
            else:
                self._late_realign_activated = True
                self._active = self._late_scene_realign()
                self._active_kind = "late_scene_realign"
                self._active_name = "late_scene_realign"
                self._active_budget = self._late_scene_realign_iterations
        elif self._stage_index == len(self._blocks) + 3:
            if self._late_realign_skipped:
                self._finish_pipeline()
                return
            self._active = self._late_material_polish()
            self._active_kind = "late_material_polish"
            self._active_name = "late_material_polish"
            self._active_budget = self._late_material_polish_iterations
        elif self._stage_index == len(self._blocks) + 4:
            if not self._start_local_jacobian_if_needed():
                return
        else:
            self._finish_pipeline()
            return
        self._stage_index += 1
        self._active_fresh = True

    def _structured_warmup(self) -> StructuredFishStrategy:
        return StructuredFishStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=self._search_param_names,
            regularization_weight=0.01,
            regularization_final_weight=0.0,
            regularization_decay=0.5,
            pattern_move_scale=0.5,
            gauss_newton_damping=0.75,
            gauss_newton_ridge=0.001,
            gauss_newton_max_repeats=2,
            gauss_newton_interval=16,
            broad_coordinate_max_repeats=0,
            scene_alignment_rounds=4,
            freeze_scene_after_alignment=True,
            basin_escape_enabled=self._warmup_basin_escape_enabled,
            basin_escape_pair_count=self._warmup_basin_escape_pair_count,
            basin_escape_round_pair_counts=self._warmup_basin_escape_round_pair_counts,
            basin_escape_radii=self._warmup_basin_escape_radii,
            basin_escape_damping=0.80,
            basin_escape_ridge=0.01,
            basin_escape_seed=self._warmup_basin_escape_seed,
            basin_escape_activation_min_fit_score=(
                self._warmup_basin_escape_activation_min_fit_score
            ),
            basin_escape_disable_opportunistic_when_skipped=True,
            basin_escape_response_methods=(
                "residual_block_secant",
                "scalar_score_response",
            ),
            basin_escape_direction_design="full_rank_hadamard_v1",
            opportunistic_ranked_accept=self._warmup_basin_escape_enabled,
        )

    def _structured_material_refine(self) -> StructuredFishStrategy:
        return self._material_refine(basin_escape_seed=1701)

    def _late_scene_realign(self) -> StructuredFishStrategy:
        return StructuredFishStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=[
                name
                for name in STRUCTURED_SCENE_PARAM_NAMES
                if name in self._search_param_names
            ],
            regularization_weight=0.0,
            regularization_final_weight=0.0,
            regularization_decay=1.0,
            pattern_move_scale=0.5,
            gauss_newton_damping=0.75,
            gauss_newton_ridge=0.001,
            gauss_newton_max_repeats=2,
            gauss_newton_interval=12,
            broad_coordinate_max_repeats=0,
            scene_alignment_rounds=4,
            freeze_scene_after_alignment=True,
            basin_escape_enabled=False,
            opportunistic_ranked_accept=True,
        )

    def _late_material_polish(self) -> StructuredFishStrategy:
        return self._material_refine(basin_escape_seed=2701)

    def _start_local_jacobian_if_needed(self) -> bool:
        if self._best_fit_score >= self._local_jacobian_trigger_score:
            self._finish_pipeline()
            return False
        self._local_jacobian_activated = True
        if self._local_refiner_strategy == "material_secant_trust_region":
            local_config = {
                "design_size": 64,
                "antithetic": False,
                "probe_radius": 0.02,
                "minimum_probe_radius": 0.003,
                "maximum_probe_radius": 0.08,
                "radius_growth": 1.20,
                "radius_shrink": 0.70,
                "ridge": 0.0001,
                "trust_radius": 0.12,
                "max_axis_update": 0.25,
                "score_feature_weight": 20.0,
                "maximum_score_drop": 0.01,
                "line_search_scales": [1.0, 0.75, 0.5, 0.25, 0.125],
            }
            local_config.update(copy.deepcopy(self._local_refiner_config))
            self._active = MaterialSecantTrustRegionStrategy(
                initial_params=self._best_params,
                shader_params=self._shader_params,
                search_param_names=self._material_param_names,
                config=local_config,
            )
            self._active_kind = "local_material_refiner"
            self._active_name = "local_material_secant"
            self._active_budget = self._local_jacobian_iterations
            return True
        local_config = {
            "difference_mode": "central",
            "solve_mode": "full_least_squares",
            "shader_default_anchor_enabled": False,
            "probe_step": 0.006,
            "minimum_probe_step": 0.001,
            "ridge": 0.005,
            "trust_radius": 0.04,
            "maximum_trust_radius": 0.10,
            "max_axis_update": 0.08,
            "line_search_scales": (1.0, 0.5, 0.25, 0.125),
        }
        local_config.update(copy.deepcopy(self._local_jacobian_config))
        self._active = MaterialJacobianTrustRegionStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=self._material_param_names,
            config=local_config,
        )
        self._active_kind = "local_material_jacobian"
        self._active_name = "local_material_jacobian"
        self._active_budget = self._local_jacobian_iterations
        return True

    def _terminal_material_pattern(self) -> MaterialCoordinatePatternStrategy:
        config = {
            "initial_step_scale": 0.03125,
            "minimum_step_scale": 0.000244140625,
            "step_growth": 1.15,
            "step_shrink": 0.5,
            "minimum_score_gain": 1.0e-6,
            "pattern_move_scales": (0.5, 1.0),
            "active_coordinate_count": 16,
            "full_refresh_interval": 3,
        }
        config.update(copy.deepcopy(self._terminal_pattern_config))
        return MaterialCoordinatePatternStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=self._material_param_names,
            config=config,
        )

    def _finish_pipeline(self) -> None:
        self._active = None
        self._active_kind = None
        self._active_name = None
        self._active_budget = 0
        self._finished = True

    def _material_refine(self, *, basin_escape_seed: int) -> StructuredFishStrategy:
        return StructuredFishStrategy(
            initial_params=self._best_params,
            shader_params=self._shader_params,
            search_param_names=self._material_param_names,
            regularization_weight=self._refine_regularization_weight,
            regularization_final_weight=self._refine_regularization_final_weight,
            regularization_decay=self._refine_regularization_decay,
            regularization_disable_score=self._refine_regularization_disable_score,
            pattern_move_scale=0.5,
            gauss_newton_damping=0.75,
            gauss_newton_ridge=0.001,
            gauss_newton_max_repeats=2,
            gauss_newton_interval=16,
            gauss_newton_high_score_threshold=(
                self._refine_gauss_newton_high_score_threshold
            ),
            gauss_newton_high_score_interval=(
                self._refine_gauss_newton_high_score_interval
            ),
            gauss_newton_high_score_max_repeats=(
                self._refine_gauss_newton_high_score_max_repeats
            ),
            broad_coordinate_max_repeats=0,
            scene_alignment_rounds=1,
            freeze_scene_after_alignment=True,
            basin_escape_enabled=self._refine_basin_escape_enabled,
            basin_escape_pair_count=self._refine_basin_escape_pair_count,
            basin_escape_round_pair_counts=(
                self._refine_basin_escape_round_pair_counts
            ),
            basin_escape_radii=self._refine_basin_escape_radii,
            basin_escape_damping=self._refine_basin_escape_damping,
            basin_escape_ridge=self._refine_basin_escape_ridge,
            basin_escape_seed=(
                self._refine_basin_escape_seed
                if self._refine_basin_escape_seed is not None
                else basin_escape_seed
            ),
            basin_escape_activation_min_fit_score=(
                self._refine_basin_escape_activation_min_fit_score
            ),
            basin_escape_activation_mode=self._refine_basin_escape_activation_mode,
            basin_escape_disable_opportunistic_when_skipped=(
                self._refine_basin_escape_disable_opportunistic_when_skipped
            ),
            basin_escape_response_methods=self._refine_basin_escape_response_methods,
            basin_escape_direction_design=self._refine_basin_escape_direction_design,
            basin_escape_response_trust_radius=(
                self._refine_basin_escape_response_trust_radius
            ),
            basin_escape_response_line_search_scales=(
                self._refine_basin_escape_response_line_search_scales
            ),
            opportunistic_ranked_accept=(
                self._refine_basin_escape_opportunistic_ranked_accept
            ),
        )

    def _finish_active_stage(self) -> None:
        assert self._active is not None
        completed_kind = self._active_kind
        self._stage_summaries.append(
            {
                "kind": self._active_kind,
                "name": self._active_name,
                "proposals": self._stage_proposals,
                "budget": self._active_budget,
                "nested_stop_reason": self._active.stop_reason(),
                "start_fit_score": self._stage_start_score,
                "best_fit_score": self._best_fit_score,
                "gain": self._best_fit_score - self._stage_start_score,
                "nested": self._active.research_summary(),
            }
        )
        if completed_kind in {"local_material_jacobian", "local_material_refiner"}:
            self._local_jacobian_completed = True
        elif completed_kind == "terminal_material_pattern":
            self._terminal_pattern_completed = True
        self._active = None
        self._active_kind = None
        self._active_name = None
        self._active_budget = 0

    def _best_context(self, ctx: StrategyContext) -> StrategyContext:
        return StrategyContext(
            iteration=ctx.iteration,
            current_params=copy.deepcopy(self._best_params),
            analysis=copy.deepcopy(self._best_analysis),
            diff_score=max(0.0, 1.0 - self._best_fit_score),
            fit_score=self._best_fit_score,
            state=ctx.state,
        )

    def _decision(self, nested: dict[str, Any], *, stop: bool) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": None if stop else {
                "name": f"material_stage1_{self._active_name}",
                "description": "PNG-only shared material Stage 1 search",
            },
            "material_stage1_hybrid": {
                "profile": self._profile,
                "active_kind": self._active_kind,
                "active_name": self._active_name,
                "stage_proposal": self._stage_proposals,
                "stage_budget": self._active_budget,
                "best_fit_score": self._best_fit_score,
                "late_realign_trigger_score": self._late_realign_trigger_score,
                "late_realign_activated": self._late_realign_activated,
                "local_jacobian_trigger_score": self._local_jacobian_trigger_score,
                "local_jacobian_activated": self._local_jacobian_activated,
                "local_refiner_strategy": self._local_refiner_strategy,
                "feedback_source": "online_target_png_score_and_residuals_only",
                "target_params_visible": False,
                "nested": nested,
            },
            "changes": nested.get("changes", []) if isinstance(nested, dict) else [],
            "stop_reason": "material_stage1_hybrid_complete" if stop else "continue",
        }


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0.0 else default


def _unit_interval_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(max(parsed, 0.0), 1.0)


def _nonnegative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else default


__all__ = ["DEFAULT_STAGE1_BLOCK_ORDER", "MaterialStage1HybridStrategy"]
