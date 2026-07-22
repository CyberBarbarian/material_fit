"""Final Stage 2 captures, independent scores, and acceptance evidence."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.single_view_runtime import build_single_view_driver
from material_fit.experiments.stage2_io import (
    image_size,
    iteration_count,
    sha256_file,
    write_json,
)
from material_fit.experiments.stage2_scoring import (
    _acceptance_score_summary,
    _comparison_label,
    _load_acceptance_scorer_sanity,
)
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    split_discrete_candidate,
    write_candidate_lmat_with_discrete_state,
)
from material_fit.vision.cross_engine_score import (
    score_cross_engine_views_v3,
    score_cross_engine_views_v4,
)
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_METRIC,
    ForegroundDISTSAlignedRGBScorer,
)
from material_fit.vision.stage2_confidence import (
    score_pair_with_frozen_confidence,
    score_pair_with_frozen_confidence_blend,
)
from material_fit.vision.stage2_registration import apply_frozen_stage2_registration


@dataclass(frozen=True)
class Stage2FinalizationContext:
    output: Path
    spec: Any
    reference_view: dict[str, Any]
    optimizer_view: dict[str, Any]
    registration: dict[str, Any]
    profile_path: Path
    target_dir: Path
    target_path: Path
    source_target: Path
    start_material: Path
    start_params: dict[str, Any]
    start_patch: dict[str, Any]
    best_params: dict[str, Any]
    acceptance_rerank: dict[str, Any]
    registered_pattern: dict[str, Any]
    iterations: int
    fit_elapsed_s: float | None
    resolved_width: int
    resolved_height: int
    constraints: dict[str, Any]
    route_report: dict[str, Any]
    start_candidate: dict[str, Any]
    confidence_mask_path: Path
    node_modules: Path
    optimizer_id: str
    joint_profile: str
    maximum_acceptance_distance_ratio: float


def finalize_stage2_single_view(context: Stage2FinalizationContext) -> dict[str, Any]:
    c = context
    best_continuous_params, best_candidate = split_discrete_candidate(c.best_params)
    if best_candidate is None:
        raise RuntimeError("full V86 best params are missing the selected discrete state")
    start_render_params = attach_discrete_candidate(c.start_params, c.start_candidate)
    best_render_params = attach_discrete_candidate(best_continuous_params, best_candidate)
    write_candidate_lmat_with_discrete_state(
        c.start_material,
        c.output / "best_material.lmat",
        best_render_params,
    )

    raw_root = c.output / "final_capture" / "raw"
    final_driver = _artifact_driver(
        profile_path=c.profile_path,
        output_root=c.output / "final_capture" / "runtime",
        patch=c.start_patch,
        node_modules=c.node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=raw_root / "start",
            params=start_render_params,
            views=[c.optimizer_view],
            iteration=0,
        )
        phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=raw_root / "best",
            params=best_render_params,
            views=[c.optimizer_view],
            iteration=1,
        )
    finally:
        final_driver.close()

    # The human material is offline evidence. It is loaded only after the
    # optimizer renderer has stopped and cannot affect routing or proposals.
    human_material = c.spec.asset.target_material_path
    human_params = lmat_io.extract_params(lmat_io.load_lmat(human_material))
    human_patch = material_patch_from_lmat(human_material)
    human_driver = _artifact_driver(
        profile_path=c.profile_path,
        output_root=c.output / "final_capture" / "human_runtime",
        patch=human_patch,
        node_modules=c.node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=human_driver,
            artifact_dir=raw_root / "human",
            params=human_params,
            views=[c.optimizer_view],
            iteration=0,
        )
    finally:
        human_driver.close()

    stage2_view = [copy.deepcopy(c.reference_view)]
    for role in ("start", "human", "best"):
        apply_frozen_stage2_registration(
            raw_dir=raw_root / role,
            output_dir=c.output / f"{role}_render",
            views=stage2_view,
            registration=c.registration,
        )

    roles = ("start", "human", "best")
    legacy_scores = {
        role: score_cross_engine_views_v3(
            reference_dir=c.target_dir,
            candidate_dir=c.output / f"{role}_render",
            views=[c.optimizer_view],
        )
        for role in roles
    }
    texture_detail_scores = {
        role: score_cross_engine_views_v4(
            reference_dir=c.target_dir,
            candidate_dir=c.output / f"{role}_render",
            views=[c.optimizer_view],
        )
        for role in roles
    }
    acceptance_scorer = ForegroundDISTSAlignedRGBScorer()
    acceptance_scores = {
        role: _acceptance_score_summary(
            acceptance_scorer,
            c.target_path,
            c.output / f"{role}_render" / str(c.optimizer_view["file_name"]),
        )
        for role in roles
    }
    robust_scores: dict[str, Any] = {}
    blended_scores: dict[str, Any] = {}
    with Image.open(c.target_path) as reference, Image.open(
        c.confidence_mask_path
    ) as confidence:
        for role in roles:
            with Image.open(
                c.output / f"{role}_render" / str(c.optimizer_view["file_name"])
            ) as candidate:
                robust_scores[role] = score_pair_with_frozen_confidence(
                    reference,
                    candidate,
                    confidence,
                )
                blended_scores[role] = score_pair_with_frozen_confidence_blend(
                    reference,
                    candidate,
                    confidence,
                )
    write_json(
        c.output / "stage2_image_score_report.json",
        {
            "legacy_python_v3": legacy_scores,
            "texture_detail_python_v4": texture_detail_scores,
            "dists_foreground": acceptance_scores,
            "frozen_confidence_python_v4": robust_scores,
            "frozen_confidence_blend_python_v5": blended_scores,
            "optimization_acceptance_score": "dists_foreground",
        },
    )

    iteration_series = c.output / "output" / "auto_adjust" / "iteration_series.json"
    timing = phase05._timing_report(iteration_series, 500.0)
    proposals_observed = iteration_count(iteration_series)
    registered_proposals = int(c.registered_pattern.get("new_material_proposals", 0))
    unique_scored_materials = 1 + proposals_observed + registered_proposals
    write_json(c.output / "iteration_timing_report.json", timing)
    contact_sheet = phase05._write_contact_sheet(
        views=[c.optimizer_view],
        columns=(
            ("Unity reference", c.target_dir),
            (
                _comparison_label("Original Laya start", acceptance_scores["start"]),
                c.output / "start_render",
            ),
            (
                _comparison_label("Human-adjusted Laya", acceptance_scores["human"]),
                c.output / "human_render",
            ),
            (
                _comparison_label("Optimized Laya best", acceptance_scores["best"]),
                c.output / "best_render",
            ),
        ),
        output_path=c.output / "unity_start_human_best_back_view_full_v86.png",
    )
    cleanup = phase05._cleanup_recorded_runtime(c.output)
    start_distance = float(acceptance_scores["start"]["dists_distance"])
    best_distance = float(acceptance_scores["best"]["dists_distance"])
    distance_ratio = best_distance / max(start_distance, 1.0e-12)
    scorer_sanity = _load_acceptance_scorer_sanity(c.output)
    acceptance_checks = {
        "dists_distance_improved_by_at_least_15_percent": (
            distance_ratio <= c.maximum_acceptance_distance_ratio
        ),
        "decision_speed_gate_passed": bool(timing.get("gate_passed")),
        "material_budget_respected": unique_scored_materials <= 1500,
        "scorer_sanity_passed": bool(scorer_sanity.get("passed")),
        "owned_process_cleanup_passed": (
            int(cleanup.get("remaining_owned_pid_count", -1)) == 0
        ),
    }
    report = {
        "contract": "material_fit_stage2_single_view_full_v86_dists_v14",
        "accepted": all(acceptance_checks.values()),
        "asset_id": c.spec.asset.asset_id,
        "view_id": str(c.optimizer_view["view_id"]),
        "optimizer": c.optimizer_id,
        "joint_profile": c.joint_profile,
        "selected_child_profile": c.route_report["selected_joint_profile"],
        "selected_route_id": c.route_report["route_id"],
        "iterations_requested": int(c.iterations),
        "proposals_observed": proposals_observed,
        "registered_pattern_proposals": registered_proposals,
        "unique_scored_materials": unique_scored_materials,
        "maximum_unique_scored_materials": 1500,
        "timed_decision_iterations": int(timing.get("count", 0)),
        "fit_elapsed_s": c.fit_elapsed_s,
        "decision_elapsed_s": (
            float(timing["mean_ms"]) * int(timing["count"]) / 1000.0
            if timing.get("count") and timing.get("mean_ms")
            else None
        ),
        "resumed_evidence_only": c.fit_elapsed_s is None,
        "score_resolution": [c.resolved_width, c.resolved_height],
        "artifact_resolution": list(image_size(c.target_path)),
        "scores": legacy_scores,
        "texture_detail_scores": texture_detail_scores,
        "dists_scores": acceptance_scores,
        "robust_scores": robust_scores,
        "blended_scores": blended_scores,
        "acceptance_rerank": c.acceptance_rerank,
        "registered_pattern": c.registered_pattern,
        "timing": timing,
        "best_material": str(c.output / "best_material.lmat"),
        "contact_sheet": str(contact_sheet),
        "human_adjusted_reference": {
            "material_path": str(human_material),
            "used_by_optimizer": False,
            "captured_after_optimization": True,
            "dists_score": acceptance_scores["human"]["score"],
        },
        "acceptance": {
            "metric": DISTS_ALIGNED_RGB_METRIC,
            "start_distance": start_distance,
            "best_distance": best_distance,
            "distance_ratio": distance_ratio,
            "maximum_distance_ratio": c.maximum_acceptance_distance_ratio,
            "human_material_used_for_acceptance": False,
            "checks": acceptance_checks,
        },
        "discrete_state": {
            "start_candidate": c.start_candidate,
            "best_candidate": best_candidate,
        },
        "target_provenance": {
            "source": str(c.source_target),
            "sha256": sha256_file(c.source_target),
        },
        "constraints": c.constraints,
        "confidence_mask_audit": str(c.confidence_mask_path),
        "scorer_sanity": scorer_sanity,
        "cleanup": cleanup,
    }
    write_json(c.output / "stage2_single_view_report.json", report)
    return report


def _artifact_driver(
    *,
    profile_path: Path,
    output_root: Path,
    patch: dict[str, Any],
    node_modules: Path,
):
    return build_single_view_driver(
        profile_path=profile_path,
        output_root=output_root,
        material_patch={
            "target_name": "model",
            "defines": copy.deepcopy(patch["defines"]),
            "render_states": copy.deepcopy(patch["render_states"]),
        },
        node_modules=node_modules,
        reference_path=None,
        return_images=True,
    )


__all__ = ["Stage2FinalizationContext", "finalize_stage2_single_view"]
