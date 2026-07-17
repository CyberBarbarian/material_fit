"""Hierarchical discrete search interleaved with continuous Stage 1 fitting."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..shared.models import ShaderParam
from .cmaes_strategy import CmaesStrategy
from .material_discrete_space import (
    BROWSER_SCORE_OVERRIDE_PARAM,
    attach_discrete_candidate,
    normalize_discrete_candidate,
    split_discrete_candidate,
)
from .material_coordinate_pattern_strategy import MaterialCoordinatePatternStrategy
from .material_jacobian_trust_region_strategy import MaterialJacobianTrustRegionStrategy
from .material_jacobian_cascade_strategy import MaterialJacobianCascadeStrategy
from .material_stage1_hybrid_strategy import MaterialStage1HybridStrategy
from .strategy_core import CmaesStrategyConfig, OptimizerStrategy, StrategyContext
from .structured_fish_strategy import StructuredFishStrategy
from .structured_fish_space import structured_fish_coordinates
from .material_discrete_joint_rescan import MaterialDiscreteRescanMixin
from .material_discrete_joint_support import (
    _axis_value_filter,
    _finite_unique_float_tuple,
    _nonnegative_float,
    _normalized_grid_step,
    _observable_score_summary,
    _positive_float,
    _positive_float_tuple,
    _positive_int_tuple,
    _quantize_optimizer_feedback,
    _select_diverse_survivors,
)


@dataclass
class _Branch:
    candidate: dict[str, Any]
    best_params: dict[str, Any]
    best_score: float = -math.inf
    best_analysis: dict[str, Any] | None = None
    last_params: dict[str, Any] | None = None
    last_score: float = -math.inf
    last_analysis: dict[str, Any] | None = None
    optimizer: OptimizerStrategy | None = None
    proposals: int = 0
    exhausted: bool = False
    round_seed_params: dict[str, Any] | None = None
    round_seed_pending: bool = False
    awaiting_seed_observation: bool = False
    race_seed: int | None = None
    race_base_params: dict[str, Any] | None = None
    race_restart_index: int = 0
    race_seeds: list[int] = field(default_factory=list)

    @property
    def candidate_id(self) -> str:
        return str(self.candidate["candidate_id"])


class MaterialDiscreteJointStrategy(MaterialDiscreteRescanMixin, OptimizerStrategy):
    """Allocate continuous-search budget adaptively across legal hard states.

    Every legal state receives an equal zero-budget observation. Multiple
    states then survive each round and receive increasingly expensive joint
    continuous CMA adaptation. The provisional winner is refined by the
    maintained continuous Stage 1 pipeline, while periodic common-parameter
    rescans let every legal hard state compete again as the continuous state
    improves. No target state or target parameters are accepted by this
    strategy.
    """

    name = "material_discrete_joint"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        raw_candidates = cfg.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ValueError("material_discrete_joint requires legal discrete candidates")
        candidates = [normalize_discrete_candidate(row) for row in raw_candidates]
        ids = [str(row["candidate_id"]) for row in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("material_discrete_joint candidate ids must be unique")

        continuous, initial_candidate = split_discrete_candidate(initial_params)
        if initial_candidate is None:
            raw_start = cfg.get("start_candidate")
            if not isinstance(raw_start, dict):
                raise ValueError("material_discrete_joint requires a start_candidate")
            initial_candidate = normalize_discrete_candidate(raw_start)
        if initial_candidate["candidate_id"] not in set(ids):
            raise ValueError("material_discrete_joint start candidate is outside the legal space")

        self._shader_params = list(shader_params)
        self._search_param_names = [
            name
            for name in dict.fromkeys(search_param_names or continuous)
            if name in continuous
        ]
        if not self._search_param_names:
            raise ValueError("material_discrete_joint has no searchable continuous parameters")
        coordinates = structured_fish_coordinates(
            continuous,
            shader_params=self._shader_params,
            search_param_names=self._search_param_names,
        )
        self._axis_bounds = {
            coordinate.coordinate_id: (coordinate.low, coordinate.high)
            for coordinate in coordinates
        }
        if not self._axis_bounds:
            raise ValueError("material_discrete_joint has no legal continuous coordinates")

        self._round_widths = _positive_int_tuple(cfg.get("round_widths"), (8, 4, 4))
        self._round_budgets = _positive_int_tuple(cfg.get("round_budgets"), (64, 160, 320))
        self._round_sigmas = _positive_float_tuple(cfg.get("round_sigmas"), (0.18, 0.10, 0.05))
        if not (
            len(self._round_widths)
            == len(self._round_budgets)
            == len(self._round_sigmas)
        ):
            raise ValueError("material_discrete_joint round schedules must have equal length")
        self._population_size = max(int(cfg.get("population_size", 16)), 2)
        self._seed = int(cfg.get("seed", 20260714))
        self._profile = str(cfg.get("profile") or "material_discrete_joint_v3_shared_seed_rescan")
        self._feedback_score_step = _nonnegative_float(
            cfg.get("feedback_score_step"),
            0.0,
        )
        self._feedback_residual_step = _nonnegative_float(
            cfg.get("feedback_residual_step"),
            0.0,
        )
        self._feedback_residual_projection_size = max(
            int(cfg.get("feedback_residual_projection_size", 0)),
            0,
        )
        self._feedback_full_precision_after_final_rescan = bool(
            cfg.get("feedback_full_precision_after_final_rescan", False)
        )
        self._feedback_quantization_start_continuous_proposals = max(
            int(cfg.get("feedback_quantization_start_continuous_proposals", 0)),
            0,
        )
        self._staged_proposal_quantization = any(
            name in cfg
            for name in (
                "proposal_quantization_pre_final_normalized_step",
                "proposal_quantization_post_final_normalized_step",
            )
        )
        self._proposal_quantization_pre_final_step = _normalized_grid_step(
            cfg.get("proposal_quantization_pre_final_normalized_step"),
            0.0,
        )
        self._proposal_quantization_post_final_step = _normalized_grid_step(
            cfg.get("proposal_quantization_post_final_normalized_step"),
            self._proposal_quantization_pre_final_step,
        )
        self._last_feedback_quantization: dict[str, Any] = {
            "enabled": False,
            "score_step": self._feedback_score_step,
            "residual_step": self._feedback_residual_step,
            "configured_score_step": self._feedback_score_step,
            "configured_residual_step": self._feedback_residual_step,
            "configured_residual_projection_size": (
                self._feedback_residual_projection_size
            ),
            "full_precision_after_final_rescan": (
                self._feedback_full_precision_after_final_rescan
            ),
            "quantization_start_continuous_proposals": (
                self._feedback_quantization_start_continuous_proposals
            ),
            "continuous_proposals": 0,
            "quantization_started": (
                self._feedback_quantization_start_continuous_proposals == 0
            ),
            "final_rescan_complete": False,
        }
        self._branch_strategy = str(cfg.get("branch_strategy", "cmaes"))
        if self._branch_strategy not in {"cmaes", "material_jacobian_trust_region"}:
            raise ValueError(
                "material_discrete_joint branch strategy must be "
                "'cmaes' or 'material_jacobian_trust_region'"
            )
        branch_jacobian = cfg.get("branch_jacobian")
        self._branch_jacobian_config = (
            copy.deepcopy(branch_jacobian) if isinstance(branch_jacobian, dict) else {}
        )
        self._winner_continuation_budget = max(
            int(cfg.get("winner_continuation_budget", 0)),
            0,
        )
        winner_sigma = cfg.get("winner_continuation_sigma")
        self._winner_continuation_sigma = (
            float(winner_sigma)
            if winner_sigma is not None and math.isfinite(float(winner_sigma))
            and float(winner_sigma) > 0.0
            else None
        )
        self._diversity_rounds = max(int(cfg.get("diversity_rounds", 3)), 0)
        self._rescan_interval = max(int(cfg.get("rescan_interval", 800)), 0)
        raw_rescan_at = cfg.get("rescan_at")
        self._rescan_schedule = (
            tuple(
                sorted(
                    {
                        int(value)
                        for value in raw_rescan_at
                        if int(value) > 0
                    }
                )
            )
            if isinstance(raw_rescan_at, (list, tuple))
            else ()
        )
        initial_score_schedule = cfg.get("initial_score_rescan_schedule")
        self._initial_score_rescan_config = (
            copy.deepcopy(initial_score_schedule)
            if isinstance(initial_score_schedule, dict)
            else {}
        )
        self._initial_score_rescan_selection: dict[str, Any] = {}
        self._max_rescans = max(int(cfg.get("max_rescans", 4)), 0)
        self._rescan_switch_min_margin_after_first = _nonnegative_float(
            cfg.get("rescan_switch_min_margin_after_first"),
            0.0,
        )
        continuous_cfg = cfg.get("continuous")
        self._continuous_config = (
            copy.deepcopy(continuous_cfg) if isinstance(continuous_cfg, dict) else {}
        )
        self._continuous_strategy = str(
            self._continuous_config.get("strategy", "material_stage1_hybrid")
        )
        if self._continuous_strategy not in {
            "material_stage1_hybrid",
            "material_jacobian_cascade",
            "material_jacobian_trust_region",
            "material_coordinate_pattern",
            "structured_fish",
        }:
            raise ValueError(
                "material_discrete_joint continuous strategy must be "
                "'material_stage1_hybrid', 'material_jacobian_cascade', or "
                "'material_jacobian_trust_region', or "
                "'material_coordinate_pattern', or 'structured_fish'"
            )
        post_rescan_cfg = cfg.get("post_rescan_branch_race")
        self._post_rescan_branch_config = (
            copy.deepcopy(post_rescan_cfg)
            if isinstance(post_rescan_cfg, dict)
            else {}
        )
        self._post_rescan_branch_enabled = bool(
            self._post_rescan_branch_config.get("enabled", False)
        )
        raw_branch_rescan_counts = self._post_rescan_branch_config.get(
            "run_at_rescan_counts"
        )
        self._post_rescan_branch_rescan_counts = (
            tuple(
                sorted(
                    {
                        int(value)
                        for value in raw_branch_rescan_counts
                        if int(value) > 0
                    }
                )
            )
            if isinstance(raw_branch_rescan_counts, (list, tuple))
            else ()
        )
        self._post_rescan_group_axis = str(
            self._post_rescan_branch_config.get("group_axis") or "normal_mode"
        )
        raw_group_axes = self._post_rescan_branch_config.get("group_axes")
        if isinstance(raw_group_axes, (list, tuple)):
            self._post_rescan_group_axes = tuple(
                str(axis).strip() for axis in raw_group_axes if str(axis).strip()
            )
        else:
            self._post_rescan_group_axes = (self._post_rescan_group_axis,)
        if not self._post_rescan_group_axes:
            raise ValueError("post-rescan branch race requires at least one group axis")
        self._post_rescan_branch_width = max(
            int(self._post_rescan_branch_config.get("width", 4)),
            1,
        )
        self._post_rescan_branch_budget = max(
            int(self._post_rescan_branch_config.get("budget_per_candidate", 0)),
            0,
        )
        self._post_rescan_branch_sigma = _positive_float(
            self._post_rescan_branch_config.get("sigma"),
            0.10,
        )
        self._post_rescan_branch_restart_count = max(
            int(self._post_rescan_branch_config.get("restart_count", 1)),
            1,
        )
        self._post_rescan_branch_restart_budget = max(
            int(
                self._post_rescan_branch_config.get(
                    "restart_budget",
                    self._post_rescan_branch_budget,
                )
            ),
            1,
        )
        self._post_rescan_branch_strategy = str(
            self._post_rescan_branch_config.get("strategy") or "cmaes"
        )
        if self._post_rescan_branch_strategy not in {
            "cmaes",
            "material_jacobian_trust_region",
            "material_stage1_hybrid",
        }:
            raise ValueError(
                "post-rescan branch strategy must be 'cmaes', "
                "'material_jacobian_trust_region', or 'material_stage1_hybrid'"
            )
        raw_post_rescan_jacobian = self._post_rescan_branch_config.get("jacobian")
        self._post_rescan_branch_jacobian_config = (
            copy.deepcopy(raw_post_rescan_jacobian)
            if isinstance(raw_post_rescan_jacobian, dict)
            else {}
        )
        raw_post_rescan_hybrid = self._post_rescan_branch_config.get("hybrid")
        self._post_rescan_branch_hybrid_config = (
            copy.deepcopy(raw_post_rescan_hybrid)
            if isinstance(raw_post_rescan_hybrid, dict)
            else {}
        )
        self._post_rescan_allowed_axis_values = _axis_value_filter(
            self._post_rescan_branch_config.get("allowed_axis_values")
        )
        frozen_names = {
            str(name)
            for name in self._post_rescan_branch_config.get("frozen_param_names", ())
        }
        self._post_rescan_branch_search_names = [
            name for name in self._search_param_names if name not in frozen_names
        ]
        if (
            self._post_rescan_branch_enabled
            and self._post_rescan_branch_budget > 0
            and not self._post_rescan_branch_search_names
        ):
            raise ValueError("post-rescan branch race has no searchable continuous parameters")
        final_continuous_cfg = self._post_rescan_branch_config.get("final_continuous")
        self._post_rescan_final_continuous_config = (
            copy.deepcopy(final_continuous_cfg)
            if isinstance(final_continuous_cfg, dict)
            else copy.deepcopy(self._continuous_config)
        )
        adaptive_fallback = self._post_rescan_branch_config.get("adaptive_fallback")
        self._post_rescan_adaptive_fallback_config = (
            copy.deepcopy(adaptive_fallback)
            if isinstance(adaptive_fallback, dict)
            else {}
        )
        self._post_rescan_effective_group_axes = self._post_rescan_group_axes
        self._post_rescan_effective_branch_width = self._post_rescan_branch_width
        self._post_rescan_effective_branch_budget = self._post_rescan_branch_budget
        self._post_rescan_effective_branch_sigma = self._post_rescan_branch_sigma
        self._post_rescan_effective_restart_count = (
            self._post_rescan_branch_restart_count
        )
        self._post_rescan_effective_restart_budget = (
            self._post_rescan_branch_restart_budget
        )
        self._post_rescan_effective_branch_strategy = self._post_rescan_branch_strategy
        self._post_rescan_effective_jacobian_config = copy.deepcopy(
            self._post_rescan_branch_jacobian_config
        )
        self._post_rescan_effective_hybrid_config = copy.deepcopy(
            self._post_rescan_branch_hybrid_config
        )
        self._post_rescan_effective_allowed_axis_values = copy.deepcopy(
            self._post_rescan_allowed_axis_values
        )
        self._post_rescan_effective_final_continuous_config = copy.deepcopy(
            self._post_rescan_final_continuous_config
        )
        final_rescan_continuous = cfg.get("continuous_after_final_rescan")
        self._continuous_after_final_rescan_config = (
            copy.deepcopy(final_rescan_continuous)
            if isinstance(final_rescan_continuous, dict)
            else {}
        )
        raw_final_score_override = self._post_rescan_branch_config.get(
            "final_continuous_browser_score_override"
        )
        self._post_rescan_effective_final_score_override: dict[str, Any] = (
            copy.deepcopy(raw_final_score_override)
            if isinstance(raw_final_score_override, dict)
            else {}
        )
        raw_axis_response_scan = cfg.get("post_rescan_axis_response_scan")
        self._post_rescan_axis_response_scan_config = (
            copy.deepcopy(raw_axis_response_scan)
            if isinstance(raw_axis_response_scan, dict)
            else {}
        )
        self._post_rescan_axis_response_scan_enabled = bool(
            self._post_rescan_axis_response_scan_config.get("enabled", False)
        )
        self._post_rescan_axis_response_group_axis = str(
            self._post_rescan_axis_response_scan_config.get("group_axis")
            or "normal_mode"
        )
        self._post_rescan_axis_response_param_name = str(
            self._post_rescan_axis_response_scan_config.get("param_name") or ""
        ).strip()
        raw_scan_values = self._post_rescan_axis_response_scan_config.get("values")
        self._post_rescan_axis_response_values = _finite_unique_float_tuple(
            raw_scan_values
        )
        raw_fixed_axes = self._post_rescan_axis_response_scan_config.get(
            "fixed_axes_from_rescan_winner",
            (),
        )
        self._post_rescan_axis_response_fixed_axes = tuple(
            dict.fromkeys(
                str(axis).strip()
                for axis in raw_fixed_axes
                if str(axis).strip()
            )
        ) if isinstance(raw_fixed_axes, (list, tuple)) else ()
        raw_activation_tiebreak = self._post_rescan_axis_response_scan_config.get(
            "activation_tiebreak"
        )
        self._post_rescan_axis_response_activation_tiebreak = (
            copy.deepcopy(raw_activation_tiebreak)
            if isinstance(raw_activation_tiebreak, dict)
            else {}
        )
        self._post_rescan_axis_response_activation_tiebreak_enabled = bool(
            self._post_rescan_axis_response_activation_tiebreak.get(
                "enabled",
                False,
            )
        )
        self._post_rescan_axis_response_minimum_range = _nonnegative_float(
            self._post_rescan_axis_response_activation_tiebreak.get(
                "minimum_response_range"
            ),
            0.0,
        )
        self._post_rescan_axis_response_maximum_peak_gap = _nonnegative_float(
            self._post_rescan_axis_response_activation_tiebreak.get(
                "maximum_peak_score_gap"
            ),
            0.0,
        )
        self._post_rescan_axis_response_require_nonminimum_peak = bool(
            self._post_rescan_axis_response_activation_tiebreak.get(
                "require_peak_above_minimum_probe",
                True,
            )
        )
        self._post_rescan_axis_response_continuous_seed_mode = str(
            self._post_rescan_axis_response_scan_config.get("continuous_seed_mode")
            or "best_probe"
        )
        if self._post_rescan_axis_response_continuous_seed_mode not in {
            "best_probe",
            "common_rescan",
            "best_online",
        }:
            raise ValueError(
                "post-rescan axis-response continuous_seed_mode must be "
                "'best_probe', 'common_rescan', or 'best_online'"
            )
        if self._post_rescan_axis_response_scan_enabled:
            if not self._post_rescan_axis_response_param_name:
                raise ValueError("post-rescan axis-response scan requires param_name")
            if self._post_rescan_axis_response_param_name not in self._axis_bounds:
                raise ValueError(
                    "post-rescan axis-response scan parameter is not a searchable "
                    f"continuous coordinate: {self._post_rescan_axis_response_param_name}"
                )
            if not self._post_rescan_axis_response_values:
                raise ValueError("post-rescan axis-response scan requires finite values")
            low, high = self._axis_bounds[
                self._post_rescan_axis_response_param_name
            ]
            outside = [
                value
                for value in self._post_rescan_axis_response_values
                if value < low or value > high
            ]
            if outside:
                raise ValueError(
                    "post-rescan axis-response scan values are outside the searchable "
                    f"bounds [{low}, {high}]: {outside}"
                )
            required_axes = {
                self._post_rescan_axis_response_group_axis,
                *self._post_rescan_axis_response_fixed_axes,
            }
            missing_axes = [
                str(candidate["candidate_id"])
                for candidate in candidates
                if not required_axes.issubset(candidate.get("axes", {}))
            ]
            if missing_axes:
                raise ValueError(
                    "post-rescan axis-response scan candidates are missing required "
                    f"axes {sorted(required_axes)}: {missing_axes}"
                )
        self._score_domain_warmup_continuous_config: dict[str, Any] = {}
        self._post_rescan_adaptive_fallback_applied = False
        self._post_rescan_adaptive_trigger: dict[str, Any] = {}
        self._final_grouped_rescan_axes: tuple[str, ...] = ()
        self._final_grouped_rescan_after: int | None = None
        self._final_grouped_rescan_score_override: dict[str, Any] = {}
        self._final_grouped_rescan_override_applies_to_rescan = True
        self._active_browser_score_override: dict[str, Any] = {}
        self._restart_continuous_after_rescan = bool(
            cfg.get("restart_continuous_after_rescan", False)
        )

        self._branches = {
            str(candidate["candidate_id"]): _Branch(
                candidate=copy.deepcopy(candidate),
                best_params=copy.deepcopy(continuous),
            )
            for candidate in candidates
        }
        self._candidate_order = ids
        self._initial_continuous = copy.deepcopy(continuous)
        self._start_candidate_id = str(initial_candidate["candidate_id"])
        self._probed_ids: set[str] = set()
        self._pending_branch_id: str | None = None
        self._phase = "discrete_probe"
        self._round_index = -1
        self._active_ids: list[str] = []
        self._round_cursor = 0
        self._round_summaries: list[dict[str, Any]] = []
        self._continuous: OptimizerStrategy | None = None
        self._winner_id: str | None = None
        self._winner_continuation_proposals = 0
        self._continuous_proposals = 0
        self._rescan_count = 0
        self._next_rescan_at: int | None = (
            self._rescan_schedule[0]
            if self._rescan_schedule
            else (self._rescan_interval if self._rescan_interval > 0 else None)
        )
        self._rescan_params: dict[str, Any] | None = None
        self._rescan_candidate_ids: list[str] = list(self._candidate_order)
        self._rescan_group_axes: tuple[str, ...] = ()
        self._rescan_scores: dict[str, float] = {}
        self._rescan_analyses: dict[str, dict[str, Any]] = {}
        self._rescan_summaries: list[dict[str, Any]] = []
        self._post_rescan_branch_done = False
        self._post_rescan_branch_cursor = 0
        self._post_rescan_branch_summaries: list[dict[str, Any]] = []
        self._post_rescan_axis_response_scan_done = False
        self._post_rescan_axis_response_common_params: dict[str, Any] | None = None
        self._post_rescan_axis_response_candidate_ids: list[str] = []
        self._post_rescan_axis_response_queue: list[tuple[str, float]] = []
        self._post_rescan_axis_response_pending: tuple[str, float] | None = None
        self._post_rescan_axis_response_results: list[dict[str, Any]] = []
        self._post_rescan_axis_response_rescan_scores: dict[str, float] = {}
        self._post_rescan_axis_response_rescan_analyses: dict[
            str, dict[str, Any]
        ] = {}
        self._post_rescan_axis_response_prior_branch_seeds: dict[
            str, dict[str, Any]
        ] = {}
        self._post_rescan_axis_response_summaries: list[dict[str, Any]] = []
        self._best_params = attach_discrete_candidate(continuous, initial_candidate)
        self._best_fit_score = -math.inf
        self._best_analysis: dict[str, Any] = {}
        self._finished = False

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return "material_discrete_joint_complete" if self._finished else None

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        final_rescan_complete = bool(
            self._max_rescans > 0 and self._rescan_count >= self._max_rescans
        )
        quantization_started = bool(
            self._continuous_proposals
            >= self._feedback_quantization_start_continuous_proposals
        )
        full_precision = bool(
            not quantization_started
            or (
                self._feedback_full_precision_after_final_rescan
                and final_rescan_complete
            )
        )
        ctx, self._last_feedback_quantization = _quantize_optimizer_feedback(
            ctx,
            score_step=0.0 if full_precision else self._feedback_score_step,
            residual_step=0.0 if full_precision else self._feedback_residual_step,
            residual_projection_size=(
                0 if full_precision else self._feedback_residual_projection_size
            ),
        )
        self._last_feedback_quantization.update(
            {
                "configured_score_step": self._feedback_score_step,
                "configured_residual_step": self._feedback_residual_step,
                "configured_residual_projection_size": (
                    self._feedback_residual_projection_size
                ),
                "full_precision_after_final_rescan": (
                    self._feedback_full_precision_after_final_rescan
                ),
                "quantization_start_continuous_proposals": (
                    self._feedback_quantization_start_continuous_proposals
                ),
                "continuous_proposals": self._continuous_proposals,
                "quantization_started": quantization_started,
                "final_rescan_complete": final_rescan_complete,
            }
        )
        self._select_initial_score_rescan_schedule(ctx.fit_score)
        self._observe(ctx)

        if self._phase == "discrete_probe":
            next_id = next(
                (candidate_id for candidate_id in self._candidate_order if candidate_id not in self._probed_ids),
                None,
            )
            if next_id is not None:
                self._pending_branch_id = next_id
                candidate = attach_discrete_candidate(
                    self._initial_continuous,
                    self._branches[next_id].candidate,
                )
                return candidate, self._decision({}, candidate_id=next_id)
            self._start_round(0, list(self._branches))

        if self._phase == "successive_halving":
            while True:
                branch = self._next_round_branch()
                if branch is not None:
                    candidate, nested = self._propose_branch(branch, ctx)
                    self._pending_branch_id = branch.candidate_id
                    return candidate, self._decision(nested, candidate_id=branch.candidate_id)
                if self._pending_branch_id is not None:
                    raise RuntimeError("discrete branch observation was not consumed")
                if self._round_index + 1 < len(self._round_budgets):
                    self._finish_round()
                    self._start_round(self._round_index + 1, self._active_ids)
                    continue
                self._finish_round()
                if self._winner_continuation_budget > 0:
                    self._start_winner_continuation()
                else:
                    self._start_continuous_refine()
                break

        if self._phase == "winner_continuation":
            assert self._winner_id is not None
            winner = self._branches[self._winner_id]
            if (
                self._winner_continuation_proposals >= self._winner_continuation_budget
                or winner.optimizer is None
                or winner.optimizer.stop_reason() is not None
            ):
                self._start_continuous_refine()
            else:
                candidate, nested = self._propose_branch(winner, ctx)
                self._winner_continuation_proposals += 1
                self._pending_branch_id = winner.candidate_id
                return candidate, self._decision(nested, candidate_id=winner.candidate_id)

        if self._phase == "discrete_rescan":
            candidate = self._propose_rescan_candidate()
            if candidate is not None:
                return candidate
            self._finish_rescan(ctx)

        if self._phase == "post_rescan_axis_response_scan":
            candidate = self._propose_post_rescan_axis_response_candidate()
            if candidate is not None:
                return candidate
            score_domain_warmup = self._finish_post_rescan_axis_response_scan(ctx)
            if score_domain_warmup is not None:
                return score_domain_warmup

        if self._phase == "post_rescan_branch_race":
            branch = self._next_post_rescan_branch()
            if branch is not None:
                candidate, nested = self._propose_branch(branch, ctx)
                self._pending_branch_id = branch.candidate_id
                return candidate, self._decision(nested, candidate_id=branch.candidate_id)
            if self._pending_branch_id is not None:
                raise RuntimeError("post-rescan branch observation was not consumed")
            score_domain_warmup = self._finish_post_rescan_branch_race(ctx)
            if score_domain_warmup is not None:
                return score_domain_warmup

        if self._phase == "continuous_score_domain_warmup":
            if self._pending_branch_id is not None:
                raise RuntimeError("score-domain warmup observation was not consumed")
            assert self._winner_id is not None
            winner = self._branches[self._winner_id]
            if not math.isfinite(winner.best_score):
                raise RuntimeError("score-domain warmup did not produce a finite score")
            self._start_continuous_from_winner(
                winner,
                self._score_domain_warmup_continuous_config,
            )

        if self._phase == "continuous_refine":
            assert self._continuous is not None
            assert self._winner_id is not None
            if self._should_start_rescan():
                self._start_rescan(ctx)
                candidate = self._propose_rescan_candidate()
                assert candidate is not None
                return candidate
            winner = self._branches[self._winner_id]
            if self._continuous.stop_reason() is not None:
                self._finished = True
                self._phase = "complete"
                return copy.deepcopy(self._best_params), self._decision({}, candidate_id=self._winner_id, stop=True)
            winner_ctx = self._branch_context(winner, ctx)
            candidate, nested = self._continuous.propose(winner_ctx)
            continuous, _unused = split_discrete_candidate(candidate)
            result = self._with_browser_score_override(
                attach_discrete_candidate(continuous, winner.candidate)
            )
            self._continuous_proposals += 1
            self._pending_branch_id = winner.candidate_id
            return result, self._decision(nested, candidate_id=winner.candidate_id)

        self._finished = True
        return copy.deepcopy(self._best_params), self._decision({}, candidate_id=self._winner_id, stop=True)

    def research_summary(self) -> dict[str, Any]:
        branches = sorted(
            (
                {
                    "candidate_id": branch.candidate_id,
                    "axes": copy.deepcopy(branch.candidate.get("axes", {})),
                    "best_fit_score": branch.best_score,
                    "proposals": branch.proposals,
                    "observable_score_summary": _observable_score_summary(
                        branch.best_analysis
                    ),
                }
                for branch in self._branches.values()
            ),
            key=lambda row: float(row["best_fit_score"]),
            reverse=True,
        )
        return {
            "profile": self._profile,
            "feedback_quantization": copy.deepcopy(
                self._last_feedback_quantization
            ),
            "proposal_quantization": {
                "staged": self._staged_proposal_quantization,
                "pre_final_normalized_step": (
                    self._proposal_quantization_pre_final_step
                ),
                "post_final_normalized_step": (
                    self._proposal_quantization_post_final_step
                ),
                "current_normalized_step": self._proposal_quantization_step(),
                "final_rescan_complete": self._final_rescan_complete(),
            },
            "asset_independent": True,
            "phase": self._phase,
            "legal_candidate_count": len(self._branches),
            "start_candidate_id": self._start_candidate_id,
            "round_widths": list(self._round_widths),
            "round_budgets": list(self._round_budgets),
            "round_sigmas": list(self._round_sigmas),
            "branch_strategy": self._branch_strategy,
            "winner_continuation_budget": self._winner_continuation_budget,
            "winner_continuation_sigma": self._winner_continuation_sigma,
            "winner_continuation_proposals": self._winner_continuation_proposals,
            "diversity_rounds": self._diversity_rounds,
            "rescan_interval": self._rescan_interval,
            "rescan_at": list(self._rescan_schedule),
            "rescan_switch_min_margin_after_first": (
                self._rescan_switch_min_margin_after_first
            ),
            "initial_score_rescan_schedule": copy.deepcopy(
                self._initial_score_rescan_selection
            ),
            "restart_continuous_after_rescan": self._restart_continuous_after_rescan,
            "continuous_after_final_rescan": copy.deepcopy(
                self._continuous_after_final_rescan_config
            ),
            "max_rescans": self._max_rescans,
            "continuous_strategy": self._continuous_strategy,
            "rescan_count": self._rescan_count,
            "rescan_summaries": copy.deepcopy(self._rescan_summaries),
            "post_rescan_axis_response_scan": {
                "enabled": self._post_rescan_axis_response_scan_enabled,
                "group_axis": self._post_rescan_axis_response_group_axis,
                "param_name": self._post_rescan_axis_response_param_name,
                "values": list(self._post_rescan_axis_response_values),
                "fixed_axes_from_rescan_winner": list(
                    self._post_rescan_axis_response_fixed_axes
                ),
                "activation_tiebreak": copy.deepcopy(
                    self._post_rescan_axis_response_activation_tiebreak
                ),
                "continuous_seed_mode": (
                    self._post_rescan_axis_response_continuous_seed_mode
                ),
                "completed": self._post_rescan_axis_response_scan_done,
                "summaries": copy.deepcopy(
                    self._post_rescan_axis_response_summaries
                ),
            },
            "post_rescan_branch_race": {
                "enabled": self._post_rescan_branch_enabled,
                "run_at_rescan_counts": list(
                    self._post_rescan_branch_rescan_counts
                ),
                "group_axis": self._post_rescan_group_axis,
                "group_axes": list(self._post_rescan_effective_group_axes),
                "width": self._post_rescan_effective_branch_width,
                "budget_per_candidate": self._post_rescan_effective_branch_budget,
                "sigma": self._post_rescan_effective_branch_sigma,
                "restart_count": self._post_rescan_effective_restart_count,
                "restart_budget": self._post_rescan_effective_restart_budget,
                "strategy": self._post_rescan_effective_branch_strategy,
                "allowed_axis_values": copy.deepcopy(
                    self._post_rescan_effective_allowed_axis_values
                ),
                "adaptive_fallback_applied": self._post_rescan_adaptive_fallback_applied,
                "adaptive_trigger": copy.deepcopy(self._post_rescan_adaptive_trigger),
                "final_grouped_rescan_axes": list(self._final_grouped_rescan_axes),
                "final_grouped_rescan_after": self._final_grouped_rescan_after,
                "final_grouped_rescan_score_override": copy.deepcopy(
                    self._final_grouped_rescan_score_override
                ),
                "final_continuous_score_override": copy.deepcopy(
                    self._post_rescan_effective_final_score_override
                ),
                "frozen_param_names": sorted(
                    set(self._search_param_names)
                    - set(self._post_rescan_branch_search_names)
                ),
                "completed": self._post_rescan_branch_done,
                "summaries": copy.deepcopy(self._post_rescan_branch_summaries),
            },
            "round_summaries": copy.deepcopy(self._round_summaries),
            "winner_candidate_id": self._winner_id,
            "best_fit_score": self._best_fit_score,
            "branches": branches,
            "feedback_source": "target_png_score_and_signed_residuals_only",
            "target_discrete_state_visible": False,
            "target_continuous_params_visible": False,
            "continuous": self._continuous.research_summary() if self._continuous else {},
            "stop_reason": self.stop_reason(),
        }

    def _select_initial_score_rescan_schedule(self, fit_score: float) -> None:
        if not self._initial_score_rescan_config or self._initial_score_rescan_selection:
            return
        score = float(fit_score)
        threshold = float(self._initial_score_rescan_config.get("threshold", 0.0))
        if not math.isfinite(score) or not math.isfinite(threshold):
            raise ValueError("initial-score rescan routing requires finite scores")
        route = "at_or_above" if score >= threshold else "below"
        raw_schedule = self._initial_score_rescan_config.get(route)
        if not isinstance(raw_schedule, (list, tuple)):
            raise ValueError(
                f"initial-score rescan routing requires a {route!r} schedule"
            )
        schedule = tuple(
            sorted({int(value) for value in raw_schedule if int(value) > 0})
        )
        if not schedule:
            raise ValueError("initial-score rescan routing selected an empty schedule")
        self._rescan_schedule = schedule
        self._next_rescan_at = schedule[0]
        self._initial_score_rescan_selection = {
            "initial_fit_score": score,
            "threshold": threshold,
            "route": route,
            "rescan_at": list(schedule),
            "feedback_source": "initial_online_target_png_score_only",
            "target_params_visible": False,
        }

    def _observe(self, ctx: StrategyContext) -> None:
        continuous, candidate = split_discrete_candidate(ctx.current_params)
        candidate_id = (
            str(candidate["candidate_id"])
            if candidate is not None
            else self._start_candidate_id
        )
        branch = self._branches.get(candidate_id)
        if branch is None:
            raise ValueError(f"observed unknown discrete candidate: {candidate_id}")
        score = float(ctx.fit_score)
        branch.last_params = copy.deepcopy(continuous)
        branch.last_score = score
        branch.last_analysis = copy.deepcopy(ctx.analysis)
        if math.isfinite(score) and score > branch.best_score:
            branch.best_score = score
            branch.best_params = copy.deepcopy(continuous)
            branch.best_analysis = copy.deepcopy(ctx.analysis)
        if math.isfinite(score) and score > self._best_fit_score:
            self._best_fit_score = score
            self._best_params = attach_discrete_candidate(continuous, branch.candidate)
            self._best_analysis = copy.deepcopy(ctx.analysis)
        if self._phase == "discrete_probe":
            self._probed_ids.add(candidate_id)
        if self._phase == "discrete_rescan":
            self._rescan_scores[candidate_id] = score
            self._rescan_analyses[candidate_id] = copy.deepcopy(ctx.analysis)
        if self._phase == "post_rescan_axis_response_scan":
            pending = self._post_rescan_axis_response_pending
            if pending is None:
                raise RuntimeError(
                    "post-rescan axis-response observation has no pending probe"
                )
            pending_candidate_id, pending_value = pending
            if candidate_id != pending_candidate_id:
                raise RuntimeError(
                    "post-rescan axis-response observation candidate mismatch: "
                    f"expected {pending_candidate_id}, got {candidate_id}"
                )
            observed_value = float(
                continuous[self._post_rescan_axis_response_param_name]
            )
            if not math.isclose(observed_value, pending_value, abs_tol=1e-12):
                raise RuntimeError(
                    "post-rescan axis-response observation value mismatch: "
                    f"expected {pending_value}, got {observed_value}"
                )
            self._post_rescan_axis_response_results.append(
                {
                    "candidate_id": candidate_id,
                    "axes": copy.deepcopy(branch.candidate.get("axes", {})),
                    "param_value": pending_value,
                    "fit_score": score,
                    "params": copy.deepcopy(continuous),
                    "analysis": copy.deepcopy(ctx.analysis),
                    "observable_score_summary": _observable_score_summary(
                        ctx.analysis
                    ),
                }
            )
            self._post_rescan_axis_response_pending = None
        if self._pending_branch_id == candidate_id:
            self._pending_branch_id = None
        if branch.awaiting_seed_observation:
            branch.awaiting_seed_observation = False

    def _start_round(self, round_index: int, source_ids: Sequence[str]) -> None:
        self._phase = "successive_halving"
        self._round_index = round_index
        width = min(self._round_widths[round_index], len(source_ids))
        source = [self._branches[candidate_id] for candidate_id in source_ids]
        selected = _select_diverse_survivors(
            source,
            width,
            use_diversity=round_index < self._diversity_rounds,
        )
        self._active_ids = [branch.candidate_id for branch in selected]
        self._round_cursor = 0
        sigma = self._round_sigmas[round_index]
        shared_seed = copy.deepcopy(
            max(source, key=lambda branch: branch.best_score).best_params
        )
        for branch_index, branch in enumerate(selected):
            branch.proposals = 0
            branch.exhausted = False
            branch.round_seed_params = copy.deepcopy(shared_seed)
            branch.round_seed_pending = True
            branch.awaiting_seed_observation = False
            if self._branch_strategy == "material_jacobian_trust_region":
                branch.optimizer = MaterialJacobianTrustRegionStrategy(
                    initial_params=copy.deepcopy(shared_seed),
                    shader_params=self._shader_params,
                    search_param_names=self._search_param_names,
                    config=self._branch_jacobian_config,
                )
            else:
                branch.optimizer = CmaesStrategy(
                    initial_params=copy.deepcopy(shared_seed),
                    shader_params=self._shader_params,
                    config=CmaesStrategyConfig(
                        mode="cold",
                        population_size=self._population_size,
                        sigma=sigma,
                        seed=self._seed + round_index * 1000 + branch_index,
                        hint_bias_mix_ratio=0.0,
                        allow_scene_lighting=True,
                    ),
                    param_whitelist=self._search_param_names,
                    axis_bounds=self._axis_bounds,
                )

    def _next_round_branch(self) -> _Branch | None:
        if not self._active_ids:
            return None
        budget = self._round_budgets[self._round_index]
        for offset in range(len(self._active_ids)):
            index = (self._round_cursor + offset) % len(self._active_ids)
            branch = self._branches[self._active_ids[index]]
            if branch.round_seed_pending:
                self._round_cursor = (index + 1) % len(self._active_ids)
                return branch
            if branch.optimizer is not None and branch.optimizer.stop_reason() is not None:
                branch.exhausted = True
            if branch.exhausted or branch.proposals >= budget:
                continue
            self._round_cursor = (index + 1) % len(self._active_ids)
            return branch
        return None

    def _propose_branch(
        self,
        branch: _Branch,
        fallback_ctx: StrategyContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert branch.optimizer is not None
        if branch.round_seed_pending:
            assert branch.round_seed_params is not None
            branch.round_seed_pending = False
            branch.awaiting_seed_observation = True
            return attach_discrete_candidate(
                branch.round_seed_params,
                branch.candidate,
            ), {
                "optimizer": self.name,
                "stage": {
                    "name": "material_discrete_joint_shared_seed",
                    "description": "Evaluate the shared continuous seed under this hard state",
                },
                "changes": [],
                "stop_reason": "continue",
            }
        if branch.awaiting_seed_observation:
            raise RuntimeError("shared seed observation was not consumed")
        branch_ctx = self._branch_context(branch, fallback_ctx)
        candidate, nested = branch.optimizer.propose(branch_ctx)
        continuous, _unused = split_discrete_candidate(candidate)
        branch.proposals += 1
        return attach_discrete_candidate(continuous, branch.candidate), nested

    def _branch_context(self, branch: _Branch, fallback: StrategyContext) -> StrategyContext:
        params = branch.last_params if branch.last_params is not None else branch.best_params
        score = branch.last_score if math.isfinite(branch.last_score) else branch.best_score
        if not math.isfinite(score):
            score = fallback.fit_score
        analysis = branch.last_analysis if branch.last_analysis is not None else branch.best_analysis
        return StrategyContext(
            iteration=fallback.iteration,
            current_params=copy.deepcopy(params),
            analysis=copy.deepcopy(analysis if analysis is not None else fallback.analysis),
            diff_score=max(0.0, 1.0 - float(score)),
            fit_score=float(score),
            state=fallback.state,
        )

    def _finish_round(self) -> None:
        rows = sorted(
            (
                {
                    "candidate_id": candidate_id,
                    "best_fit_score": self._branches[candidate_id].best_score,
                    "proposals": self._branches[candidate_id].proposals,
                    "shared_seed_evaluated": not self._branches[candidate_id].round_seed_pending,
                    "axes": copy.deepcopy(self._branches[candidate_id].candidate.get("axes", {})),
                }
                for candidate_id in self._active_ids
            ),
            key=lambda row: float(row["best_fit_score"]),
            reverse=True,
        )
        self._round_summaries.append(
            {
                "round_index": self._round_index,
                "budget_per_candidate": self._round_budgets[self._round_index],
                "sigma": self._round_sigmas[self._round_index],
                "candidates": rows,
            }
        )

    def _start_continuous_refine(self) -> None:
        winner = max(
            (self._branches[candidate_id] for candidate_id in self._active_ids),
            key=lambda branch: branch.best_score,
        )
        self._start_continuous_from_winner(winner, self._continuous_config)

    def _start_continuous_from_winner(
        self,
        winner: _Branch,
        continuous_config: dict[str, Any],
    ) -> None:
        strategy = str(continuous_config.get("strategy", "material_stage1_hybrid"))
        frozen_names = set(continuous_config.get("frozen_param_names", ()))
        search_names = [
            name for name in self._search_param_names if name not in frozen_names
        ]
        if not search_names:
            raise ValueError("continuous refine has no searchable parameters")
        self._winner_id = winner.candidate_id
        if strategy == "material_jacobian_trust_region":
            self._continuous = MaterialJacobianTrustRegionStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                search_param_names=search_names,
                config=continuous_config.get("jacobian"),
            )
        elif strategy == "material_jacobian_cascade":
            self._continuous = MaterialJacobianCascadeStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                search_param_names=search_names,
                config=continuous_config.get("cascade"),
            )
        elif strategy == "material_stage1_hybrid":
            self._continuous = MaterialStage1HybridStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                search_param_names=search_names,
                config=continuous_config,
            )
        elif strategy == "material_coordinate_pattern":
            self._continuous = MaterialCoordinatePatternStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                search_param_names=search_names,
                config=continuous_config.get("pattern"),
            )
        elif strategy == "structured_fish":
            structured_config = continuous_config.get("structured_fish")
            structured_config = (
                structured_config if isinstance(structured_config, dict) else {}
            )
            self._continuous = StructuredFishStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                search_param_names=search_names,
                regularization_weight=float(
                    structured_config.get("regularization_weight", 0.01)
                ),
                regularization_final_weight=float(
                    structured_config.get("regularization_final_weight", 0.0)
                ),
                regularization_decay=float(
                    structured_config.get("regularization_decay", 0.5)
                ),
                pattern_move_scale=float(
                    structured_config.get("pattern_move_scale", 0.5)
                ),
                gauss_newton_damping=float(
                    structured_config.get("gauss_newton_damping", 0.75)
                ),
                gauss_newton_ridge=float(
                    structured_config.get("gauss_newton_ridge", 0.001)
                ),
                gauss_newton_max_repeats=int(
                    structured_config.get("gauss_newton_max_repeats", 2)
                ),
                gauss_newton_interval=int(
                    structured_config.get("gauss_newton_interval", 16)
                ),
                broad_coordinate_max_repeats=int(
                    structured_config.get("broad_coordinate_max_repeats", 0)
                ),
                scene_alignment_rounds=int(
                    structured_config.get("scene_alignment_rounds", 4)
                ),
                freeze_scene_after_alignment=bool(
                    structured_config.get("freeze_scene_after_alignment", True)
                ),
                basin_escape_enabled=bool(
                    structured_config.get("basin_escape_enabled", False)
                ),
                opportunistic_ranked_accept=bool(
                    structured_config.get("opportunistic_ranked_accept", False)
                ),
            )
        else:
            raise ValueError(f"unsupported continuous strategy: {strategy}")
        winner.last_params = copy.deepcopy(winner.best_params)
        winner.last_score = winner.best_score
        winner.last_analysis = copy.deepcopy(winner.best_analysis or {})
        self._phase = "continuous_refine"

    def _start_winner_continuation(self) -> None:
        winner = max(
            (self._branches[candidate_id] for candidate_id in self._active_ids),
            key=lambda branch: branch.best_score,
        )
        if winner.optimizer is None:
            raise RuntimeError("winner continuation requires the final branch optimizer")
        if self._winner_continuation_sigma is not None:
            winner.optimizer = CmaesStrategy(
                initial_params=copy.deepcopy(winner.best_params),
                shader_params=self._shader_params,
                config=CmaesStrategyConfig(
                    mode="cold",
                    population_size=self._population_size,
                    sigma=self._winner_continuation_sigma,
                    seed=self._seed + 9000,
                    hint_bias_mix_ratio=0.0,
                    allow_scene_lighting=True,
                ),
                param_whitelist=self._search_param_names,
                axis_bounds=self._axis_bounds,
            )
            winner.last_params = copy.deepcopy(winner.best_params)
            winner.last_score = winner.best_score
            winner.last_analysis = copy.deepcopy(winner.best_analysis or {})
        self._winner_id = winner.candidate_id
        self._winner_continuation_proposals = 0
        self._phase = "winner_continuation"


    def _decision(
        self,
        nested: dict[str, Any],
        *,
        candidate_id: str | None,
        stop: bool = False,
        reset_global_score_domain: bool = False,
    ) -> dict[str, Any]:
        decision = {
            "optimizer": self.name,
            "reset_global_score_domain": reset_global_score_domain,
            "stage": None if stop else {
                "name": f"material_discrete_joint_{self._phase}",
                "description": "Successive-halving hard-state and continuous material search",
            },
            "material_discrete_joint": {
                "profile": self._profile,
                "phase": self._phase,
                "candidate_id": candidate_id,
                "round_index": self._round_index,
                "active_candidate_ids": list(self._active_ids),
                "winner_candidate_id": self._winner_id,
                "best_fit_score": self._best_fit_score,
                "continuous_proposals": self._continuous_proposals,
                "rescan_count": self._rescan_count,
                "next_rescan_at": self._next_rescan_at,
                "feedback_source": "target_png_score_and_signed_residuals_only",
                "feedback_quantization": copy.deepcopy(
                    self._last_feedback_quantization
                ),
                "target_discrete_state_visible": False,
                "target_continuous_params_visible": False,
                "nested": nested,
            },
            "changes": nested.get("changes", []) if isinstance(nested, dict) else [],
            "stop_reason": "material_discrete_joint_complete" if stop else "continue",
        }
        if self._staged_proposal_quantization:
            decision["proposal_quantization_normalized_step"] = (
                self._proposal_quantization_step()
            )
        return decision

    def _final_rescan_complete(self) -> bool:
        return bool(self._max_rescans > 0 and self._rescan_count >= self._max_rescans)

    def _proposal_quantization_step(self) -> float:
        return (
            self._proposal_quantization_post_final_step
            if self._final_rescan_complete()
            else self._proposal_quantization_pre_final_step
        )
