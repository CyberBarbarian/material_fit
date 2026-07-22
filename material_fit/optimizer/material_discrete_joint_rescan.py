"""Discrete rescans and branch races for the joint strategy."""

from __future__ import annotations

import copy
import math
from typing import Any

from .cmaes_strategy import CmaesStrategy
from .material_discrete_space import BROWSER_SCORE_OVERRIDE_PARAM, attach_discrete_candidate, split_discrete_candidate
from .material_jacobian_trust_region_strategy import MaterialJacobianTrustRegionStrategy
from .material_stage1_hybrid_strategy import MaterialStage1HybridStrategy
from .strategy_core import CmaesStrategyConfig
from .material_discrete_joint_support import (
    _axis_value_filter,
    _nonnegative_float,
    _positive_float,
    _semantic_branch_seed_offset,
)


class MaterialDiscreteRescanMixin:
    def _should_start_rescan(self) -> bool:
        if self._next_rescan_at is None or self._rescan_count >= self._max_rescans:
            return False
        assert self._continuous is not None
        return bool(
            self._continuous_proposals >= self._next_rescan_at
            or self._continuous.stop_reason() is not None
        )

    def _start_rescan(self, ctx: StrategyContext) -> None:
        continuous, _candidate = split_discrete_candidate(self._best_params)
        self._rescan_params = copy.deepcopy(continuous)
        previous_browser_score_override = copy.deepcopy(
            self._active_browser_score_override
        )
        candidate_mode = (
            self._rescan_candidate_modes[self._rescan_count]
            if self._rescan_count < len(self._rescan_candidate_modes)
            else "all"
        )
        self._active_browser_score_override = (
            copy.deepcopy(self._rescan_browser_score_overrides[self._rescan_count])
            if self._rescan_count < len(self._rescan_browser_score_overrides)
            else {}
        )
        self._rescan_group_axes = ()
        if candidate_mode == "current_winner" and self._winner_id is not None:
            self._rescan_candidate_ids = [self._winner_id]
        elif candidate_mode == "initial_representatives":
            self._rescan_candidate_ids = list(self._initial_candidate_order)
        elif candidate_mode.startswith("winner_axis:"):
            if self._winner_id is None:
                raise RuntimeError("winner-axis rescan requires a current winner")
            varied_axis = candidate_mode.removeprefix("winner_axis:").strip()
            winner_axes = self._branches[self._winner_id].candidate.get("axes", {})
            if varied_axis not in winner_axes:
                raise ValueError(
                    f"winner-axis rescan references unknown axis: {varied_axis}"
                )
            fixed_axes = set(winner_axes) - {varied_axis}
            self._rescan_candidate_ids = [
                candidate_id
                for candidate_id in self._candidate_order
                if all(
                    self._branches[candidate_id].candidate.get("axes", {}).get(axis)
                    == winner_axes.get(axis)
                    for axis in fixed_axes
                )
            ]
            self._rescan_group_axes = (varied_axis,)
            if not self._rescan_candidate_ids:
                raise RuntimeError("winner-axis discrete rescan selected no candidates")
        else:
            self._rescan_candidate_ids = list(self._candidate_order)
        if (
            self._post_rescan_branch_done
            and self._final_grouped_rescan_axes
            and self._rescan_count > 0
            and self._winner_id is not None
        ):
            winner_axes = self._branches[self._winner_id].candidate.get("axes", {})
            all_axes = {
                str(axis)
                for candidate_id in self._candidate_order
                for axis in self._branches[candidate_id].candidate.get("axes", {})
            }
            fixed_axes = all_axes - set(self._final_grouped_rescan_axes)
            self._rescan_candidate_ids = [
                candidate_id
                for candidate_id in self._candidate_order
                if all(
                    self._branches[candidate_id].candidate.get("axes", {}).get(axis)
                    == winner_axes.get(axis)
                    for axis in fixed_axes
                )
            ]
            self._rescan_group_axes = self._final_grouped_rescan_axes
            self._active_browser_score_override = copy.deepcopy(
                self._final_grouped_rescan_score_override
                if self._final_grouped_rescan_override_applies_to_rescan
                else {}
            )
            if not self._rescan_candidate_ids:
                raise RuntimeError("final grouped discrete rescan selected no candidates")
        self._rescan_reset_global_score_domain = bool(
            self._active_browser_score_override
            != previous_browser_score_override
        )
        if self._rescan_reset_global_score_domain:
            self._reset_score_domain(ctx)
        self._rescan_scores = {}
        self._rescan_analyses = {}
        self._pending_branch_id = None
        self._phase = "discrete_rescan"

    def _propose_rescan_candidate(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        assert self._rescan_params is not None
        next_id = next(
            (
                candidate_id
                for candidate_id in self._rescan_candidate_ids
                if candidate_id not in self._rescan_scores
            ),
            None,
        )
        if next_id is None:
            return None
        self._pending_branch_id = next_id
        candidate = self._with_browser_score_override(
            attach_discrete_candidate(
                self._rescan_params,
                self._branches[next_id].candidate,
            )
        )
        reset_global_score_domain = self._rescan_reset_global_score_domain
        self._rescan_reset_global_score_domain = False
        return candidate, self._decision(
            {},
            candidate_id=next_id,
            reset_global_score_domain=reset_global_score_domain,
        )

    def _finish_rescan(self, ctx: StrategyContext) -> None:
        if self._pending_branch_id is not None:
            raise RuntimeError("discrete rescan observation was not consumed")
        if set(self._rescan_scores) != set(self._rescan_candidate_ids):
            raise RuntimeError("discrete rescan did not observe every selected hard state")
        assert self._rescan_params is not None
        previous_winner_id = self._winner_id
        ranked = sorted(
            (
                {
                    "candidate_id": candidate_id,
                    "fit_score": self._rescan_scores[candidate_id],
                    "axes": copy.deepcopy(
                        self._branches[candidate_id].candidate.get("axes", {})
                    ),
                }
                for candidate_id in self._rescan_candidate_ids
            ),
            key=lambda row: float(row["fit_score"]),
            reverse=True,
        )
        observed_winner_id = str(ranked[0]["candidate_id"])
        winner_margin = (
            float(ranked[0]["fit_score"]) - float(ranked[1]["fit_score"])
            if len(ranked) > 1
            else math.inf
        )
        switch_suppressed = bool(
            self._rescan_count > 0
            and previous_winner_id is not None
            and previous_winner_id in self._rescan_candidate_ids
            and observed_winner_id != previous_winner_id
            and winner_margin < self._rescan_switch_min_margin_after_first
        )
        winner_id = (
            previous_winner_id if switch_suppressed else observed_winner_id
        )
        winner = self._branches[winner_id]
        winner.last_params = copy.deepcopy(self._rescan_params)
        winner.last_score = self._rescan_scores[winner_id]
        winner.last_analysis = copy.deepcopy(self._rescan_analyses[winner_id])
        self._winner_id = winner_id
        self._rescan_count += 1
        if self._rescan_count >= self._max_rescans:
            self._final_rescan_continuous_proposal_start = self._continuous_proposals
        self._rescan_summaries.append(
            {
                "rescan_index": self._rescan_count - 1,
                "continuous_proposals": self._continuous_proposals,
                "previous_winner_candidate_id": previous_winner_id,
                "winner_candidate_id": winner_id,
                "winner_changed": winner_id != previous_winner_id,
                "observed_winner_candidate_id": observed_winner_id,
                "winner_margin": winner_margin,
                "switch_min_margin_after_first": (
                    self._rescan_switch_min_margin_after_first
                ),
                "switch_suppressed": switch_suppressed,
                "group_axes": list(self._rescan_group_axes),
                "candidate_count": len(self._rescan_candidate_ids),
                "common_continuous_params": copy.deepcopy(self._rescan_params),
                "candidates": ranked,
            }
        )
        rescan_params = copy.deepcopy(self._rescan_params)
        rescan_scores = copy.deepcopy(self._rescan_scores)
        rescan_analyses = copy.deepcopy(self._rescan_analyses)
        if self._rescan_schedule:
            self._next_rescan_at = (
                self._rescan_schedule[self._rescan_count]
                if self._rescan_count < len(self._rescan_schedule)
                else None
            )
        elif self._next_rescan_at is not None:
            self._next_rescan_at += self._rescan_interval
        self._rescan_params = None
        self._rescan_scores = {}
        self._rescan_analyses = {}
        if (
            self._rescan_group_axes
            and self._final_grouped_rescan_score_override
            and not self._final_grouped_rescan_override_applies_to_rescan
        ):
            self._active_browser_score_override = copy.deepcopy(
                self._final_grouped_rescan_score_override
            )
            self._reset_score_domain(ctx)
        if (
            self._post_rescan_axis_response_scan_enabled
            and not self._post_rescan_axis_response_scan_done
        ):
            self._start_post_rescan_axis_response_scan(
                common_params=rescan_params,
                scores=rescan_scores,
                analyses=rescan_analyses,
                rescan_winner_id=winner_id,
            )
        elif (
            self._post_rescan_branch_enabled
            and self._post_rescan_branch_budget > 0
            and (
                self._rescan_count in self._post_rescan_branch_rescan_counts
                if self._post_rescan_branch_rescan_counts
                else not self._post_rescan_branch_done
            )
        ):
            self._start_post_rescan_branch_race(
                common_params=rescan_params,
                scores=rescan_scores,
                analyses=rescan_analyses,
            )
        elif self._restart_continuous_after_rescan and (
            self._rescan_count > 1
            or bool(self._post_rescan_branch_rescan_counts)
            or self._restart_continuous_after_first_rescan
        ):
            winner.best_params = copy.deepcopy(rescan_params)
            winner.best_score = float(rescan_scores[winner_id])
            winner.best_analysis = copy.deepcopy(rescan_analyses[winner_id])
            continuous_config = self._post_rescan_effective_final_continuous_config
            if (
                self._next_rescan_at is None
                and self._continuous_after_final_rescan_config
            ):
                continuous_config = self._continuous_after_final_rescan_config
            self._start_continuous_from_winner(
                winner,
                continuous_config,
            )
        else:
            self._phase = "continuous_refine"

    def _start_post_rescan_axis_response_scan(
        self,
        *,
        common_params: dict[str, Any],
        scores: dict[str, float],
        analyses: dict[str, dict[str, Any]],
        rescan_winner_id: str,
    ) -> None:
        winner_axes = self._branches[rescan_winner_id].candidate.get("axes", {})
        fixed_axis_values = {
            axis: winner_axes[axis]
            for axis in self._post_rescan_axis_response_fixed_axes
        }
        grouped: dict[Any, list[_Branch]] = {}
        for candidate_id in self._candidate_order:
            if candidate_id not in scores:
                continue
            branch = self._branches[candidate_id]
            axes = branch.candidate.get("axes", {})
            if any(
                axes.get(axis) != value
                for axis, value in fixed_axis_values.items()
            ):
                continue
            grouped.setdefault(
                axes[self._post_rescan_axis_response_group_axis], []
            ).append(branch)
        selected = [
            self._post_rescan_group_representative(rows, scores)
            for rows in grouped.values()
        ]
        selected.sort(key=lambda branch: self._candidate_order.index(branch.candidate_id))
        if not selected:
            raise RuntimeError("post-rescan axis-response scan selected no candidates")

        self._post_rescan_axis_response_prior_branch_seeds = {}
        for branch in selected:
            candidate_id = branch.candidate_id
            self._post_rescan_axis_response_prior_branch_seeds[candidate_id] = {
                "params": copy.deepcopy(branch.best_params),
                "fit_score": float(branch.best_score),
                "analysis": copy.deepcopy(branch.best_analysis),
            }
            branch.best_params = copy.deepcopy(common_params)
            branch.best_score = float(scores[candidate_id])
            branch.best_analysis = copy.deepcopy(analyses[candidate_id])
            branch.last_params = copy.deepcopy(common_params)
            branch.last_score = float(scores[candidate_id])
            branch.last_analysis = copy.deepcopy(analyses[candidate_id])

        self._post_rescan_axis_response_common_params = copy.deepcopy(common_params)
        self._post_rescan_axis_response_candidate_ids = [
            branch.candidate_id for branch in selected
        ]
        self._post_rescan_axis_response_queue = [
            (branch.candidate_id, value)
            for branch in selected
            for value in self._post_rescan_axis_response_values
        ]
        self._post_rescan_axis_response_pending = None
        self._post_rescan_axis_response_results = []
        self._post_rescan_axis_response_rescan_scores = copy.deepcopy(scores)
        self._post_rescan_axis_response_rescan_analyses = copy.deepcopy(analyses)
        self._active_ids = list(self._post_rescan_axis_response_candidate_ids)
        self._phase = "post_rescan_axis_response_scan"

    def _propose_post_rescan_axis_response_candidate(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self._post_rescan_axis_response_pending is not None:
            raise RuntimeError(
                "post-rescan axis-response probe observation was not consumed"
            )
        if not self._post_rescan_axis_response_queue:
            return None
        assert self._post_rescan_axis_response_common_params is not None
        candidate_id, value = self._post_rescan_axis_response_queue.pop(0)
        continuous = copy.deepcopy(self._post_rescan_axis_response_common_params)
        continuous[self._post_rescan_axis_response_param_name] = value
        self._post_rescan_axis_response_pending = (candidate_id, value)
        self._pending_branch_id = candidate_id
        candidate = self._with_browser_score_override(
            attach_discrete_candidate(
                continuous,
                self._branches[candidate_id].candidate,
            )
        )
        return candidate, self._decision({}, candidate_id=candidate_id)

    def _finish_post_rescan_axis_response_scan(
        self,
        ctx: StrategyContext,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if self._post_rescan_axis_response_pending is not None:
            raise RuntimeError(
                "post-rescan axis-response observation was not consumed"
            )
        expected = (
            len(self._post_rescan_axis_response_candidate_ids)
            * len(self._post_rescan_axis_response_values)
        )
        if len(self._post_rescan_axis_response_results) != expected:
            raise RuntimeError(
                "post-rescan axis-response scan did not observe every probe: "
                f"expected {expected}, got "
                f"{len(self._post_rescan_axis_response_results)}"
            )
        raw_winner_row = max(
            self._post_rescan_axis_response_results,
            key=lambda row: float(row["fit_score"]),
        )
        candidates = []
        best_rows_by_candidate: dict[str, dict[str, Any]] = {}
        for candidate_id in self._post_rescan_axis_response_candidate_ids:
            rows = [
                row
                for row in self._post_rescan_axis_response_results
                if row["candidate_id"] == candidate_id
            ]
            best_row = max(rows, key=lambda row: float(row["fit_score"]))
            best_rows_by_candidate[candidate_id] = best_row
            scores = [float(row["fit_score"]) for row in rows]
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "axes": copy.deepcopy(
                        self._branches[candidate_id].candidate.get("axes", {})
                    ),
                    "best_param_value": best_row["param_value"],
                    "best_fit_score": best_row["fit_score"],
                    "response_range": max(scores) - min(scores),
                    "probes": [
                        {
                            "param_value": row["param_value"],
                            "fit_score": row["fit_score"],
                            "observable_score_summary": copy.deepcopy(
                                row["observable_score_summary"]
                            ),
                        }
                        for row in rows
                    ],
                }
            )
        candidates.sort(key=lambda row: float(row["best_fit_score"]), reverse=True)
        raw_winner_id = str(raw_winner_row["candidate_id"])
        winner_id = raw_winner_id
        selection_reason = "highest_peak_score"
        tiebreak_eligible_ids: list[str] = []
        minimum_probe = min(self._post_rescan_axis_response_values)
        raw_winner_score = float(raw_winner_row["fit_score"])
        for row in candidates:
            peak_score_gap = raw_winner_score - float(row["best_fit_score"])
            peak_above_minimum = (
                float(row["best_param_value"]) > minimum_probe + 1e-12
            )
            eligible = (
                self._post_rescan_axis_response_activation_tiebreak_enabled
                and float(row["response_range"])
                >= self._post_rescan_axis_response_minimum_range
                and peak_score_gap
                <= self._post_rescan_axis_response_maximum_peak_gap
                and (
                    not self._post_rescan_axis_response_require_nonminimum_peak
                    or peak_above_minimum
                )
            )
            row["peak_score_gap_from_raw_winner"] = peak_score_gap
            row["peak_above_minimum_probe"] = peak_above_minimum
            row["activation_tiebreak_eligible"] = eligible
            if eligible:
                tiebreak_eligible_ids.append(str(row["candidate_id"]))
        if tiebreak_eligible_ids:
            winner_id = max(
                tiebreak_eligible_ids,
                key=lambda candidate_id: float(
                    best_rows_by_candidate[candidate_id]["fit_score"]
                ),
            )
            selection_reason = "responsive_near_peak_candidate"
        winner_row = best_rows_by_candidate[winner_id]
        winner = self._branches[winner_id]
        continuous_seed_source = self._post_rescan_axis_response_continuous_seed_mode
        if self._post_rescan_axis_response_continuous_seed_mode == "common_rescan":
            assert self._post_rescan_axis_response_common_params is not None
            winner.best_params = copy.deepcopy(
                self._post_rescan_axis_response_common_params
            )
            winner.best_score = float(
                self._post_rescan_axis_response_rescan_scores[winner_id]
            )
            winner.best_analysis = copy.deepcopy(
                self._post_rescan_axis_response_rescan_analyses[winner_id]
            )
        else:
            winner.best_params = copy.deepcopy(winner_row["params"])
            winner.best_score = float(winner_row["fit_score"])
            winner.best_analysis = copy.deepcopy(winner_row["analysis"])
        if self._post_rescan_axis_response_continuous_seed_mode == "best_online":
            assert self._post_rescan_axis_response_common_params is not None
            seed_candidates = [
                {
                    "source": "common_rescan",
                    "params": self._post_rescan_axis_response_common_params,
                    "fit_score": self._post_rescan_axis_response_rescan_scores[
                        winner_id
                    ],
                    "analysis": self._post_rescan_axis_response_rescan_analyses[
                        winner_id
                    ],
                },
                {
                    "source": "best_probe",
                    "params": winner_row["params"],
                    "fit_score": winner_row["fit_score"],
                    "analysis": winner_row["analysis"],
                },
                {
                    "source": "prior_branch_best",
                    **self._post_rescan_axis_response_prior_branch_seeds[winner_id],
                },
            ]
            selected_seed = max(
                (
                    row
                    for row in seed_candidates
                    if math.isfinite(float(row["fit_score"]))
                ),
                key=lambda row: float(row["fit_score"]),
            )
            continuous_seed_source = str(selected_seed["source"])
            winner.best_params = copy.deepcopy(selected_seed["params"])
            winner.best_score = float(selected_seed["fit_score"])
            winner.best_analysis = copy.deepcopy(selected_seed["analysis"])
        winner.last_params = copy.deepcopy(winner.best_params)
        winner.last_score = winner.best_score
        winner.last_analysis = copy.deepcopy(winner.best_analysis)
        self._winner_id = winner_id

        self._post_rescan_axis_response_summaries.append(
            {
                "scan_index": len(self._post_rescan_axis_response_summaries),
                "group_axis": self._post_rescan_axis_response_group_axis,
                "param_name": self._post_rescan_axis_response_param_name,
                "values": list(self._post_rescan_axis_response_values),
                "fixed_axes_from_rescan_winner": list(
                    self._post_rescan_axis_response_fixed_axes
                ),
                "raw_peak_winner_candidate_id": raw_winner_id,
                "winner_candidate_id": winner_id,
                "winner_param_value": winner_row["param_value"],
                "winner_fit_score": winner_row["fit_score"],
                "selection_reason": selection_reason,
                "continuous_seed_mode": (
                    self._post_rescan_axis_response_continuous_seed_mode
                ),
                "continuous_seed_source": continuous_seed_source,
                "continuous_seed_param_value": winner.best_params.get(
                    self._post_rescan_axis_response_param_name
                ),
                "continuous_seed_fit_score": winner.best_score,
                "activation_tiebreak": {
                    "enabled": (
                        self._post_rescan_axis_response_activation_tiebreak_enabled
                    ),
                    "minimum_response_range": (
                        self._post_rescan_axis_response_minimum_range
                    ),
                    "maximum_peak_score_gap": (
                        self._post_rescan_axis_response_maximum_peak_gap
                    ),
                    "require_peak_above_minimum_probe": (
                        self._post_rescan_axis_response_require_nonminimum_peak
                    ),
                    "eligible_candidate_ids": tiebreak_eligible_ids,
                },
                "candidate_count": len(candidates),
                "probe_count": len(self._post_rescan_axis_response_results),
                "candidates": candidates,
                "feedback_source": "online_target_png_score_only",
                "target_params_visible": False,
            }
        )
        self._post_rescan_axis_response_scan_done = True

        if self._post_rescan_effective_final_score_override:
            score_domain_params = copy.deepcopy(winner.best_params)
            self._active_browser_score_override = copy.deepcopy(
                self._post_rescan_effective_final_score_override
            )
            self._reset_score_domain(ctx)
            winner.best_score = -math.inf
            winner.best_analysis = None
            winner.last_params = copy.deepcopy(score_domain_params)
            winner.last_score = -math.inf
            winner.last_analysis = None
            self._score_domain_warmup_continuous_config = copy.deepcopy(
                self._post_rescan_effective_final_continuous_config
            )
            self._phase = "continuous_score_domain_warmup"
            self._pending_branch_id = winner_id
            candidate = self._with_browser_score_override(
                attach_discrete_candidate(score_domain_params, winner.candidate)
            )
            return candidate, self._decision(
                {},
                candidate_id=winner_id,
                reset_global_score_domain=True,
            )
        continuous_config = (
            self._post_rescan_axis_response_continuous_config
            if self._post_rescan_axis_response_continuous_config is not None
            else self._post_rescan_effective_final_continuous_config
        )
        self._start_continuous_from_winner(winner, continuous_config)
        return None

    def _start_post_rescan_branch_race(
        self,
        *,
        common_params: dict[str, Any],
        scores: dict[str, float],
        analyses: dict[str, dict[str, Any]],
    ) -> None:
        self._select_post_rescan_race_policy(scores)
        grouped: dict[tuple[Any, ...], list[_Branch]] = {}
        for candidate_id in self._candidate_order:
            branch = self._branches[candidate_id]
            group_value = tuple(
                self._post_rescan_group_axis_value(branch, axis)
                for axis in self._post_rescan_effective_group_axes
            )
            grouped.setdefault(group_value, []).append(branch)
        selected = [
            self._post_rescan_group_representative(rows, scores)
            for rows in grouped.values()
        ]
        if self._post_rescan_effective_allowed_axis_values:
            selected = [
                branch
                for branch in selected
                if all(
                    branch.candidate.get("axes", {}).get(axis) in allowed_values
                    for axis, allowed_values in self._post_rescan_effective_allowed_axis_values.items()
                )
            ]
        selected.sort(
            key=lambda branch: (
                self._post_rescan_branch_ranking_score(branch, scores),
                float(scores[branch.candidate_id]),
            ),
            reverse=True,
        )
        selected = selected[: self._post_rescan_effective_branch_width]
        if not selected:
            raise RuntimeError("post-rescan branch race selected no candidates")

        top_score = float(scores[selected[0].candidate_id])
        lower_scores = [
            float(scores[branch.candidate_id])
            for branch in selected[1:]
            if top_score - float(scores[branch.candidate_id])
            > self._post_rescan_confident_tie_tolerance
        ]
        confidence_margin = (
            top_score - max(lower_scores) if lower_scores else math.inf
        )
        if (
            self._post_rescan_confident_margin > 0.0
            and confidence_margin >= self._post_rescan_confident_margin
        ):
            winner = selected[0]
            winner.best_params = copy.deepcopy(common_params)
            winner.best_score = top_score
            winner.best_analysis = copy.deepcopy(analyses[winner.candidate_id])
            winner.last_params = copy.deepcopy(common_params)
            winner.last_score = top_score
            winner.last_analysis = copy.deepcopy(analyses[winner.candidate_id])
            self._active_ids = [winner.candidate_id]
            self._post_rescan_branch_summaries.append(
                {
                    "race_index": len(self._post_rescan_branch_summaries),
                    "group_axis": self._post_rescan_group_axis,
                    "group_axes": list(self._post_rescan_effective_group_axes),
                    "budget_per_candidate": 0,
                    "strategy": "confident_winner_continuation",
                    "skipped_due_to_confident_margin": True,
                    "confidence_margin": confidence_margin,
                    "confidence_threshold": self._post_rescan_confident_margin,
                    "winner_candidate_id": winner.candidate_id,
                    "candidates": [
                        {
                            "candidate_id": branch.candidate_id,
                            "axes": copy.deepcopy(branch.candidate.get("axes", {})),
                            "best_fit_score": float(scores[branch.candidate_id]),
                            "proposals": 0,
                        }
                        for branch in selected
                    ],
                }
            )
            self._post_rescan_branch_done = True
            self._start_continuous_from_winner(
                winner,
                self._post_rescan_confident_continuous_config,
            )
            return

        race_bounds = {
            name: bounds
            for name, bounds in self._axis_bounds.items()
            if name in self._post_rescan_branch_search_names
        }
        self._active_ids = [branch.candidate_id for branch in selected]
        self._post_rescan_race_budget_limits = {
            branch.candidate_id: self._post_rescan_rank_budget(rank)
            for rank, branch in enumerate(selected)
        }
        self._post_rescan_ranking_evidence = {
            branch.candidate_id: self._post_rescan_branch_ranking_evidence(
                branch,
                scores,
            )
            for branch in selected
        }
        self._post_rescan_branch_cursor = 0
        for branch in selected:
            candidate_id = branch.candidate_id
            branch.best_params = copy.deepcopy(common_params)
            branch.best_score = float(scores[candidate_id])
            branch.best_analysis = copy.deepcopy(analyses[candidate_id])
            branch.last_params = copy.deepcopy(common_params)
            branch.last_score = float(scores[candidate_id])
            branch.last_analysis = copy.deepcopy(analyses[candidate_id])
            branch.proposals = 0
            branch.exhausted = False
            branch.round_seed_params = None
            branch.round_seed_pending = False
            branch.awaiting_seed_observation = False
            branch.race_seed = None
            branch.race_base_params = copy.deepcopy(common_params)
            branch.race_restart_index = 0
            branch.race_seeds = []
            branch.race_continuous_seeds = []
            for source in self._post_rescan_effective_continuous_seed_modes:
                if source == "initial":
                    branch.race_continuous_seeds.append(
                        {
                            "source": source,
                            "params": copy.deepcopy(self._initial_continuous_params),
                            "fit_score": None,
                            "analysis": None,
                        }
                    )
                else:
                    branch.race_continuous_seeds.append(
                        {
                            "source": source,
                            "params": copy.deepcopy(common_params),
                            "fit_score": float(scores[candidate_id]),
                            "analysis": copy.deepcopy(analyses[candidate_id]),
                        }
                    )
            branch.race_continuous_seed_index = 0
            branch.race_continuous_seed_history = []
            self._start_post_rescan_continuous_seed(
                branch,
                seed_index=0,
                race_bounds=race_bounds,
            )
        self._phase = "post_rescan_branch_race"

    @staticmethod
    def _post_rescan_group_axis_value(branch: _Branch, axis: str) -> Any:
        axes = branch.candidate.get("axes", {})
        if axis == "normal_activation":
            return axes.get("normal_mode") in {"normal", "normal_y_invert"}
        return axes.get(axis)

    def _post_rescan_group_representative(
        self,
        branches: list[_Branch],
        scores: dict[str, float],
    ) -> _Branch:
        raw_winner = max(
            branches,
            key=lambda branch: (
                self._post_rescan_branch_ranking_score(branch, scores),
                float(scores[branch.candidate_id]),
            ),
        )
        tolerance = self._post_rescan_complexity_score_tolerance
        eligible = [
            branch
            for branch in branches
            if (
                self._post_rescan_branch_ranking_score(raw_winner, scores)
                == self._post_rescan_branch_ranking_score(branch, scores)
                or self._post_rescan_branch_ranking_score(raw_winner, scores)
                - self._post_rescan_branch_ranking_score(branch, scores)
                <= tolerance
            )
        ]
        return min(
            eligible,
            key=lambda branch: (
                _candidate_define_complexity(branch.candidate),
                -self._post_rescan_branch_ranking_score(branch, scores),
                -float(scores[branch.candidate_id]),
                branch.candidate_id,
            ),
        )

    def _post_rescan_branch_ranking_score(
        self,
        branch: _Branch,
        scores: dict[str, float],
    ) -> float:
        if (
            self._post_rescan_effective_ranking_signal
            == "conditional_activation_peak"
            and any(
                math.isfinite(float(row["fit_score"]))
                for row in self._conditional_activation_results
            )
        ):
            activation_scores = [
                float(row["fit_score"])
                for row in self._conditional_activation_results
                if row.get("candidate_id") == branch.candidate_id
                and math.isfinite(float(row["fit_score"]))
            ]
            if activation_scores:
                return max(activation_scores)
            return -math.inf
        return float(scores[branch.candidate_id])

    def _post_rescan_branch_ranking_evidence(
        self,
        branch: _Branch,
        scores: dict[str, float],
    ) -> dict[str, Any]:
        activation_rows = [
            row
            for row in self._conditional_activation_results
            if row.get("candidate_id") == branch.candidate_id
            and math.isfinite(float(row["fit_score"]))
        ]
        if (
            self._post_rescan_effective_ranking_signal
            == "conditional_activation_peak"
            and any(
                math.isfinite(float(row["fit_score"]))
                for row in self._conditional_activation_results
            )
        ):
            if activation_rows:
                winner = max(
                    activation_rows,
                    key=lambda row: float(row["fit_score"]),
                )
                return {
                    "source": "conditional_activation_peak",
                    "fit_score": float(winner["fit_score"]),
                    "probe_name": str(winner["probe_name"]),
                    "normalized_value": float(winner["normalized_value"]),
                }
            return {
                "source": "conditional_activation_not_observed",
                "fit_score": None,
            }
        return {
            "source": "rescan_score",
            "fit_score": float(scores[branch.candidate_id]),
        }

    def _post_rescan_rank_budget(self, rank: int) -> int:
        if rank < len(self._post_rescan_effective_budgets_by_rank):
            return self._post_rescan_effective_budgets_by_rank[rank]
        return self._post_rescan_effective_branch_budget

    def _post_rescan_branch_budget_limit(self, branch: _Branch) -> int:
        return self._post_rescan_race_budget_limits.get(
            branch.candidate_id,
            self._post_rescan_effective_branch_budget,
        )

    def _start_post_rescan_continuous_seed(
        self,
        branch: _Branch,
        *,
        seed_index: int,
        race_bounds: dict[str, tuple[float, float]],
    ) -> None:
        seed = branch.race_continuous_seeds[seed_index]
        seed_params = copy.deepcopy(seed["params"])
        seed_score = seed.get("fit_score")
        seed_analysis = seed.get("analysis")
        branch.race_continuous_seed_index = seed_index
        branch.race_base_params = copy.deepcopy(seed_params)
        branch.race_restart_index = 0
        branch.exhausted = False
        branch.round_seed_params = None
        branch.round_seed_pending = False
        branch.awaiting_seed_observation = False
        branch.race_continuous_seed_history.append(
            {
                "source": str(seed["source"]),
                "proposal_start": branch.proposals,
                "seed_evaluation_required": seed_score is None,
            }
        )
        if seed_score is None:
            branch.round_seed_params = copy.deepcopy(seed_params)
            branch.round_seed_pending = True
            branch.last_params = copy.deepcopy(seed_params)
            branch.last_score = -math.inf
            branch.last_analysis = None
        else:
            branch.last_params = copy.deepcopy(seed_params)
            branch.last_score = float(seed_score)
            branch.last_analysis = copy.deepcopy(seed_analysis)

        if self._post_rescan_effective_branch_strategy == "material_jacobian_trust_region":
            branch.optimizer = MaterialJacobianTrustRegionStrategy(
                initial_params=copy.deepcopy(seed_params),
                shader_params=self._shader_params,
                search_param_names=self._post_rescan_branch_search_names,
                config=self._post_rescan_effective_jacobian_config,
            )
        elif self._post_rescan_effective_branch_strategy == "material_stage1_hybrid":
            branch.optimizer = MaterialStage1HybridStrategy(
                initial_params=copy.deepcopy(seed_params),
                shader_params=self._shader_params,
                search_param_names=self._post_rescan_branch_search_names,
                config=self._post_rescan_effective_hybrid_config,
            )
        else:
            self._restart_post_rescan_cma(branch, race_bounds)

    def _select_post_rescan_race_policy(self, scores: dict[str, float]) -> None:
        fallback = self._post_rescan_adaptive_fallback_config
        if not fallback:
            return
        trigger_axis = str(fallback.get("trigger_axis") or "normal_mode")
        preferred_value = fallback.get("preferred_value", "normal")
        winner_id = max(self._candidate_order, key=lambda candidate_id: scores[candidate_id])
        winner_value = self._branches[winner_id].candidate.get("axes", {}).get(trigger_axis)
        axis_best_scores: dict[Any, float] = {}
        for candidate_id in self._candidate_order:
            axis_value = self._branches[candidate_id].candidate.get("axes", {}).get(
                trigger_axis
            )
            axis_best_scores[axis_value] = max(
                axis_best_scores.get(axis_value, -math.inf),
                float(scores[candidate_id]),
            )
        preferred_score = axis_best_scores.get(preferred_value, -math.inf)
        competing_rows = [
            (axis_value, score)
            for axis_value, score in axis_best_scores.items()
            if axis_value != preferred_value
        ]
        competing_value, competing_score = max(
            competing_rows,
            key=lambda item: item[1],
            default=(None, -math.inf),
        )
        preferred_margin = preferred_score - competing_score
        minimum_preferred_margin = _nonnegative_float(
            fallback.get("minimum_preferred_margin"),
            0.0,
        )
        ambiguous_preferred_winner = (
            winner_value == preferred_value
            and preferred_margin < minimum_preferred_margin
        )
        winner_margin_over_preferred = (
            float(scores[winner_id]) - preferred_score
            if winner_value != preferred_value
            else preferred_margin
        )
        self._post_rescan_adaptive_trigger = {
            "axis": trigger_axis,
            "preferred_value": preferred_value,
            "observed_value": winner_value,
            "winner_candidate_id": winner_id,
            "preferred_score": preferred_score,
            "best_competing_value": competing_value,
            "best_competing_score": competing_score,
            "preferred_margin": preferred_margin,
            "minimum_preferred_margin": minimum_preferred_margin,
            "ambiguous_preferred_winner": ambiguous_preferred_winner,
            "winner_margin_over_preferred": winner_margin_over_preferred,
        }
        if winner_value == preferred_value and not ambiguous_preferred_winner:
            return

        fallback_variant = "nonpreferred_winner"
        selected_fallback = fallback
        confident_nonpreferred = fallback.get("confident_nonpreferred")
        minimum_nonpreferred_margin = _nonnegative_float(
            fallback.get("minimum_nonpreferred_margin"),
            math.inf,
        )
        confident_nonpreferred_triggered = (
            winner_value != preferred_value
            and winner_margin_over_preferred >= minimum_nonpreferred_margin
            and isinstance(confident_nonpreferred, dict)
        )
        mapped_trigger_values = fallback.get("mapped_normal_trigger_values")
        mapped_trigger_values = (
            tuple(mapped_trigger_values)
            if isinstance(mapped_trigger_values, (list, tuple, set))
            else ()
        )
        mapped_normal_config = fallback.get("mapped_normal_fallback")
        mapped_normal_triggered = ambiguous_preferred_winner or (
            winner_value in mapped_trigger_values
        )
        if confident_nonpreferred_triggered:
            fallback_variant = "confident_nonpreferred_winner"
            selected_fallback = copy.deepcopy(fallback)
            selected_fallback.pop("ambiguous_preferred", None)
            selected_fallback.pop("mapped_normal_fallback", None)
            selected_fallback.pop("confident_nonpreferred", None)
            selected_fallback.update(copy.deepcopy(confident_nonpreferred))
        elif mapped_normal_triggered and isinstance(mapped_normal_config, dict):
            fallback_variant = (
                "mapped_normal_ambiguous_preferred"
                if ambiguous_preferred_winner
                else "mapped_normal_observed_value"
            )
            selected_fallback = copy.deepcopy(fallback)
            selected_fallback.pop("ambiguous_preferred", None)
            selected_fallback.pop("mapped_normal_fallback", None)
            selected_fallback.update(copy.deepcopy(mapped_normal_config))
        elif ambiguous_preferred_winner:
            fallback_variant = "ambiguous_preferred_winner"
            ambiguous_config = fallback.get("ambiguous_preferred")
            if isinstance(ambiguous_config, dict):
                selected_fallback = copy.deepcopy(fallback)
                selected_fallback.pop("ambiguous_preferred", None)
                selected_fallback.update(copy.deepcopy(ambiguous_config))
        self._post_rescan_adaptive_trigger["fallback_variant"] = fallback_variant

        raw_group_axes = selected_fallback.get("group_axes")
        if isinstance(raw_group_axes, (list, tuple)):
            group_axes = tuple(
                str(axis).strip() for axis in raw_group_axes if str(axis).strip()
            )
        else:
            group_axes = self._post_rescan_group_axes
        if not group_axes:
            raise ValueError("adaptive post-rescan fallback requires group axes")
        strategy = str(
            selected_fallback.get("strategy") or self._post_rescan_branch_strategy
        )
        if strategy not in {
            "cmaes",
            "material_jacobian_trust_region",
            "material_stage1_hybrid",
        }:
            raise ValueError(f"unsupported adaptive post-rescan strategy: {strategy}")

        self._post_rescan_adaptive_fallback_applied = True
        self._post_rescan_effective_group_axes = group_axes
        self._post_rescan_effective_branch_width = max(
            int(selected_fallback.get("width", self._post_rescan_branch_width)), 1
        )
        self._post_rescan_effective_branch_budget = max(
            int(
                selected_fallback.get(
                    "budget_per_candidate", self._post_rescan_branch_budget
                )
            ),
            0,
        )
        self._post_rescan_effective_branch_sigma = _positive_float(
            selected_fallback.get("sigma"), self._post_rescan_branch_sigma
        )
        raw_seed_modes = selected_fallback.get(
            "continuous_seed_modes",
            self._post_rescan_branch_continuous_seed_modes,
        )
        if not isinstance(raw_seed_modes, (list, tuple)):
            raise ValueError(
                "adaptive post-rescan continuous_seed_modes must be a list"
            )
        self._post_rescan_effective_continuous_seed_modes = tuple(
            dict.fromkeys(str(value) for value in raw_seed_modes)
        )
        invalid_seed_modes = sorted(
            set(self._post_rescan_effective_continuous_seed_modes)
            - {"initial", "common_rescan"}
        )
        if invalid_seed_modes or not self._post_rescan_effective_continuous_seed_modes:
            raise ValueError(
                "adaptive post-rescan race has invalid continuous seed modes: "
                f"{invalid_seed_modes}"
            )
        self._post_rescan_effective_restart_count = max(
            int(
                selected_fallback.get(
                    "restart_count",
                    self._post_rescan_branch_restart_count,
                )
            ),
            1,
        )
        self._post_rescan_effective_restart_budget = max(
            int(
                selected_fallback.get(
                    "restart_budget",
                    self._post_rescan_branch_restart_budget,
                )
            ),
            1,
        )
        self._post_rescan_effective_branch_strategy = strategy
        self._post_rescan_effective_allowed_axis_values = _axis_value_filter(
            selected_fallback.get("allowed_axis_values")
        )
        raw_jacobian = selected_fallback.get("jacobian")
        self._post_rescan_effective_jacobian_config = (
            copy.deepcopy(raw_jacobian)
            if isinstance(raw_jacobian, dict)
            else copy.deepcopy(self._post_rescan_branch_jacobian_config)
        )
        raw_hybrid = selected_fallback.get("hybrid")
        self._post_rescan_effective_hybrid_config = (
            copy.deepcopy(raw_hybrid)
            if isinstance(raw_hybrid, dict)
            else copy.deepcopy(self._post_rescan_branch_hybrid_config)
        )
        final_continuous = selected_fallback.get("final_continuous")
        self._post_rescan_effective_final_continuous_config = (
            copy.deepcopy(final_continuous)
            if isinstance(final_continuous, dict)
            else copy.deepcopy(self._post_rescan_final_continuous_config)
        )
        raw_final_score_override = selected_fallback.get(
            "final_continuous_browser_score_override"
        )
        self._post_rescan_effective_final_score_override = (
            copy.deepcopy(raw_final_score_override)
            if isinstance(raw_final_score_override, dict)
            else {}
        )
        final_rescan = selected_fallback.get("final_grouped_rescan")
        if isinstance(final_rescan, dict) and final_rescan.get("enabled", False):
            raw_axes = final_rescan.get("group_axes")
            self._final_grouped_rescan_axes = tuple(
                str(axis).strip()
                for axis in raw_axes
                if str(axis).strip()
            ) if isinstance(raw_axes, (list, tuple)) else (trigger_axis,)
            after = int(final_rescan.get("after_continuous_proposals", 0))
            if after <= self._continuous_proposals:
                raise ValueError(
                    "final grouped rescan must follow the current continuous proposal count"
                )
            self._final_grouped_rescan_after = after
            self._next_rescan_at = after
            raw_score_override = final_rescan.get("browser_score_override")
            self._final_grouped_rescan_score_override = (
                copy.deepcopy(raw_score_override)
                if isinstance(raw_score_override, dict)
                else {}
            )
            self._final_grouped_rescan_override_applies_to_rescan = bool(
                final_rescan.get("apply_browser_score_override_to_rescan", True)
            )

    def _with_browser_score_override(self, params: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(params)
        if self._active_browser_score_override:
            result[BROWSER_SCORE_OVERRIDE_PARAM] = copy.deepcopy(
                self._active_browser_score_override
            )
        return result

    def _reset_score_domain(self, ctx: StrategyContext) -> None:
        self._best_fit_score = -math.inf
        self._best_analysis = {}
        ctx.state.best_score = math.inf
        ctx.state.best_params = {}
        ctx.state.best_fit_score = -math.inf
        ctx.state.best_fit_params = {}
        ctx.state.global_no_improve = 0

    def _next_post_rescan_branch(self) -> _Branch | None:
        if self._post_rescan_effective_allocation_order == "ranked_sequential":
            indices = range(len(self._active_ids))
        else:
            indices = (
                (self._post_rescan_branch_cursor + offset) % len(self._active_ids)
                for offset in range(len(self._active_ids))
            )
        for index in indices:
            branch = self._branches[self._active_ids[index]]
            branch_budget = self._post_rescan_branch_budget_limit(branch)
            seed_count = len(branch.race_continuous_seeds)
            seed_boundary = math.ceil(
                branch_budget
                * (branch.race_continuous_seed_index + 1)
                / max(seed_count, 1)
            )
            optimizer_stopped = bool(
                branch.optimizer is not None
                and branch.optimizer.stop_reason() is not None
            )
            if (
                (branch.proposals >= seed_boundary or optimizer_stopped)
                and branch.race_continuous_seed_index + 1 < seed_count
            ):
                race_bounds = {
                    name: bounds
                    for name, bounds in self._axis_bounds.items()
                    if name in self._post_rescan_branch_search_names
                }
                self._start_post_rescan_continuous_seed(
                    branch,
                    seed_index=branch.race_continuous_seed_index + 1,
                    race_bounds=race_bounds,
                )
                optimizer_stopped = False
            seed_proposal_start = (
                int(branch.race_continuous_seed_history[-1]["proposal_start"])
                if branch.race_continuous_seed_history
                else 0
            )
            seed_local_proposals = branch.proposals - seed_proposal_start
            if (
                self._post_rescan_effective_branch_strategy == "cmaes"
                and seed_local_proposals > 0
                and seed_local_proposals
                % self._post_rescan_effective_restart_budget
                == 0
                and branch.race_restart_index + 1
                < self._post_rescan_effective_restart_count
            ):
                race_bounds = {
                    name: bounds
                    for name, bounds in self._axis_bounds.items()
                    if name in self._post_rescan_branch_search_names
                }
                branch.race_restart_index += 1
                self._restart_post_rescan_cma(branch, race_bounds)
            if optimizer_stopped:
                branch.exhausted = True
            if branch.exhausted or branch.proposals >= branch_budget:
                continue
            if self._post_rescan_effective_allocation_order == "round_robin":
                self._post_rescan_branch_cursor = (index + 1) % len(self._active_ids)
            return branch
        return None

    def _restart_post_rescan_cma(
        self,
        branch: _Branch,
        race_bounds: dict[str, tuple[float, float]],
    ) -> None:
        if branch.race_base_params is None:
            raise RuntimeError("post-rescan CMA restart is missing its common seed")
        branch.race_seed = (
            self._seed
            + 12000
            + _semantic_branch_seed_offset(branch.candidate)
            + branch.race_restart_index * 1009
        )
        branch.race_seeds.append(branch.race_seed)
        branch.optimizer = CmaesStrategy(
            initial_params=copy.deepcopy(branch.race_base_params),
            shader_params=self._shader_params,
            config=CmaesStrategyConfig(
                mode="cold",
                population_size=self._population_size,
                sigma=self._post_rescan_effective_branch_sigma,
                seed=branch.race_seed,
                hint_bias_mix_ratio=0.0,
                allow_scene_lighting=True,
            ),
            param_whitelist=self._post_rescan_branch_search_names,
            axis_bounds=race_bounds,
        )
        branch.exhausted = False

    def _finish_post_rescan_branch_race(
        self,
        ctx: StrategyContext,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        ranked = sorted(
            (self._branches[candidate_id] for candidate_id in self._active_ids),
            key=lambda branch: branch.best_score,
            reverse=True,
        )
        raw_winner = ranked[0]
        score_tolerance = self._post_rescan_complexity_score_tolerance
        eligible = [
            branch
            for branch in ranked
            if raw_winner.best_score - branch.best_score <= score_tolerance
        ]
        winner = min(
            eligible,
            key=lambda branch: (
                _candidate_define_complexity(branch.candidate),
                -branch.best_score,
                branch.candidate_id,
            ),
        )
        self._post_rescan_branch_summaries.append(
            {
                "race_index": len(self._post_rescan_branch_summaries),
                "group_axis": self._post_rescan_group_axis,
                "group_axes": list(self._post_rescan_effective_group_axes),
                "budget_per_candidate": self._post_rescan_effective_branch_budget,
                "ranking_signal": self._post_rescan_effective_ranking_signal,
                "allocation_order": self._post_rescan_effective_allocation_order,
                "budgets_by_rank": list(
                    self._post_rescan_effective_budgets_by_rank
                ),
                "sigma": self._post_rescan_effective_branch_sigma,
                "continuous_seed_modes": list(
                    self._post_rescan_effective_continuous_seed_modes
                ),
                "restart_count": self._post_rescan_effective_restart_count,
                "restart_budget": self._post_rescan_effective_restart_budget,
                "strategy": self._post_rescan_effective_branch_strategy,
                "adaptive_fallback_applied": self._post_rescan_adaptive_fallback_applied,
                "raw_winner_candidate_id": raw_winner.candidate_id,
                "winner_candidate_id": winner.candidate_id,
                "complexity_regularization": {
                    "enabled": score_tolerance > 0.0,
                    "score_tolerance": score_tolerance,
                    "eligible_candidate_ids": [
                        branch.candidate_id for branch in eligible
                    ],
                    "changed_winner": winner.candidate_id != raw_winner.candidate_id,
                    "complexity_measure": "enabled_managed_define_count",
                },
                "candidates": [
                    {
                        "candidate_id": branch.candidate_id,
                        "axes": copy.deepcopy(branch.candidate.get("axes", {})),
                        "best_fit_score": branch.best_score,
                        "enabled_managed_define_count": (
                            _candidate_define_complexity(branch.candidate)
                        ),
                        "proposals": branch.proposals,
                        "budget_limit": self._post_rescan_branch_budget_limit(branch),
                        "ranking_evidence": copy.deepcopy(
                            self._post_rescan_ranking_evidence.get(branch.candidate_id, {})
                        ),
                        "seed": branch.race_seed,
                        "seeds": list(branch.race_seeds),
                        "continuous_seed_history": copy.deepcopy(
                            branch.race_continuous_seed_history
                        ),
                    }
                    for branch in ranked
                ],
            }
        )
        self._post_rescan_branch_done = True
        if self._post_rescan_effective_final_score_override:
            score_domain_params = copy.deepcopy(winner.best_params)
            self._active_browser_score_override = copy.deepcopy(
                self._post_rescan_effective_final_score_override
            )
            self._reset_score_domain(ctx)
            winner.best_score = -math.inf
            winner.best_analysis = None
            winner.last_params = copy.deepcopy(score_domain_params)
            winner.last_score = -math.inf
            winner.last_analysis = None
            self._winner_id = winner.candidate_id
            self._score_domain_warmup_continuous_config = copy.deepcopy(
                self._post_rescan_effective_final_continuous_config
            )
            self._phase = "continuous_score_domain_warmup"
            self._pending_branch_id = winner.candidate_id
            candidate = self._with_browser_score_override(
                attach_discrete_candidate(score_domain_params, winner.candidate)
            )
            return candidate, self._decision(
                {},
                candidate_id=winner.candidate_id,
                reset_global_score_domain=True,
            )
        self._start_continuous_from_winner(
            winner,
            self._post_rescan_effective_final_continuous_config,
        )
        return None


def _candidate_define_complexity(candidate: dict[str, Any]) -> int:
    defines = candidate.get("defines")
    if not isinstance(defines, dict):
        return 0
    managed = {str(name) for name in defines.get("managed", ())}
    enabled = {str(name) for name in defines.get("enabled", ())}
    return len(managed & enabled)
