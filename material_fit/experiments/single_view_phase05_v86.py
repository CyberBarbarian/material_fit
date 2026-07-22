"""Controlled single-view parameter recovery with the maintained V86 optimizer."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.experiments import material_phase05_recovery as legacy_phase05
from material_fit.experiments.material_human_reference_stage1 import (
    STAGE1_SCORE_READBACK_HEIGHT,
    STAGE1_SCORE_READBACK_WIDTH,
    run_stage1,
)
from material_fit.experiments.stage1_fit_config import (
    STAGE1_OPTIMIZATION_SCORE_METRIC,
)
from material_fit.experiments.single_view_recovery_matrix import (
    RecoveryStart,
    build_identifiability_recovery_matrix,
)
from material_fit.experiments.stage1_profiles import JOINT_PROFILE_V30, JOINT_PROFILE_V86
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    build_legal_discrete_candidates,
    find_candidate_for_patch,
    split_discrete_candidate,
    write_candidate_lmat_with_discrete_state,
)
from material_fit.optimizer.material_recovery import material_parameter_distance


CONTROLLED_RECOVERY_TARGET_SCORE = 0.99999


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if args.engine_libs:
        os.environ["LAYA_ENGINE_LIBS"] = str(
            Path(args.engine_libs).expanduser().resolve()
        )
    run_name = args.run_name or (
        f"single_view_phase05_v86_{args.asset}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else root / "artifacts"
    )
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] | None = None
    try:
        report = run_phase05_v86_campaign(
            repo_root=root,
            run_dir=run_dir,
            asset_id=args.asset,
            case_ids=args.case,
            iterations=args.iterations,
            target_score=args.target_score,
            success_score=args.success_score,
            max_runtime_sec=args.max_runtime_sec,
            speed_gate_ms=args.speed_gate_ms,
            freeze_start_discrete=args.freeze_start_discrete,
            node_modules=(
                Path(args.node_modules).expanduser().resolve()
                if args.node_modules
                else root / "node_modules"
            ),
        )
    finally:
        cleanup = legacy_phase05._cleanup_recorded_runtime(run_dir)
        if report is not None:
            report["process_cleanup"] = cleanup
            report["accepted"] = bool(
                report.get("accepted")
                and cleanup.get("remaining_owned_pid_count") == 0
            )
            _write_json(run_dir / "phase05_v86_campaign_report.json", report)
    assert report is not None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="turtle", choices=("fish", "turtle", "crocodile"))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--iterations", type=int, default=1499)
    parser.add_argument("--target-score", type=float, default=0.9999)
    parser.add_argument("--success-score", type=float, default=0.9999)
    parser.add_argument("--max-runtime-sec", type=float, default=1200.0)
    parser.add_argument("--speed-gate-ms", type=float, default=500.0)
    parser.add_argument("--freeze-start-discrete", action="store_true")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--engine-libs", default="")
    return parser.parse_args(argv)


def run_phase05_v86_campaign(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str,
    case_ids: Sequence[str],
    iterations: int,
    target_score: float,
    success_score: float,
    max_runtime_sec: float,
    speed_gate_ms: float,
    node_modules: Path,
    freeze_start_discrete: bool = False,
) -> dict[str, Any]:
    asset = resolve_material_asset(repo_root, asset_id)
    target_payload = lmat_io.load_lmat(asset.target_material_path)
    target_params = lmat_io.extract_params(target_payload)
    target_patch = material_patch_from_lmat(asset.target_material_path)
    legal_candidates = build_legal_discrete_candidates(target_patch)
    target_candidate = find_candidate_for_patch(legal_candidates, target_patch)
    matrix = build_identifiability_recovery_matrix(
        target_params,
        target_candidate=target_candidate,
        legal_candidates=legal_candidates,
    )
    selected = _select_cases(matrix, case_ids)

    _write_json(run_dir / "inputs" / "asset_manifest.json", asset.manifest())
    _write_json(
        run_dir / "inputs" / "experiment_contract.json",
        {
            "contract": "single_view_phase05_v86_campaign_v1",
            "view_ids": ["v000_yaw0_pitch0"],
            "optimizer": {
                "controlled_axis_and_group": "material_coordinate_pattern",
                "blind_joint_and_hard_state": JOINT_PROFILE_V86,
            },
            "continuous_coordinates": 40,
            "scene_coordinates_searchable": False,
            "legal_hard_states": len(legal_candidates),
            "target_input_to_optimizer": "one target PNG only",
            "target_material_or_params_visible": False,
            "known_target_params_use": "private post-run identifiability audit only",
            "known_perturbation_scope_visible": (
                "only for controlled single-axis and group calibration cases"
            ),
            "case_ids": [case.case_id for case in selected],
            "freeze_start_discrete": bool(freeze_start_discrete),
            "max_proposals_per_case": int(iterations),
        },
    )
    private = run_dir / "private_audit"
    private.mkdir(parents=True, exist_ok=True)
    _write_json(private / "target_params.json", target_params)
    _write_json(private / "target_discrete_candidate.json", target_candidate)

    reports: list[dict[str, Any]] = []
    for case in selected:
        case_dir = run_dir / "cases" / case.case_id
        start_material = case_dir / "inputs" / "start_material.lmat"
        write_candidate_lmat_with_discrete_state(
            asset.target_material_path,
            start_material,
            case.params,
        )
        _write_json(case_dir / "inputs" / "start_manifest.json", case.manifest())
        stage_report: dict[str, Any] | None = None
        try:
            controlled_names = _controlled_search_param_names(case)
            controlled_case = controlled_names is not None
            effective_target_score = _case_target_score(
                case,
                requested_target_score=target_score,
            )
            stage_report = run_stage1(
                repo_root=repo_root,
                run_dir=case_dir,
                asset_id=asset_id,
                profile_path=None,
                start_material_path=start_material,
                target_material_path=asset.target_material_path,
                shader_path=asset.shader_path,
                iterations=int(iterations),
                optimizer=(
                    "material_coordinate_pattern"
                    if controlled_case
                    else (
                        "material_stage1_hybrid"
                        if freeze_start_discrete
                        else "material_discrete_joint"
                    )
                ),
                warmup_iterations=1000,
                block_iterations=400,
                block_population_size=16,
                refine_iterations=800,
                jacobian_search_scope="material",
                target_score=effective_target_score,
                success_score=float(success_score),
                max_runtime_sec=float(max_runtime_sec),
                speed_gate_ms=float(speed_gate_ms),
                node_modules=node_modules,
                joint_profile=(JOINT_PROFILE_V30 if controlled_case else JOINT_PROFILE_V86),
                score_metric=STAGE1_OPTIMIZATION_SCORE_METRIC,
                score_width=STAGE1_SCORE_READBACK_WIDTH,
                score_height=STAGE1_SCORE_READBACK_HEIGHT,
                single_view=True,
                target_label="Known material target",
                search_param_names_override=controlled_names,
                restrict_discrete_candidates_to_start=controlled_case,
                pattern_initial_grid_points=17 if controlled_case else 0,
            )
        finally:
            legacy_phase05._cleanup_recorded_runtime(case_dir)
        if stage_report is None:
            raise RuntimeError(f"Phase 0.5 case produced no report: {case.case_id}")
        audit = _private_case_audit(
            case=case,
            target_params=target_params,
            best_params=_read_json(case_dir / "best_continuous_params.json"),
            stage_report=stage_report,
            success_score=success_score,
            hard_state_recovery_override=(
                _frozen_start_matches_target_state(case, target_candidate)
                if freeze_start_discrete
                else None
            ),
        )
        _write_json(case_dir / "private_audit" / "phase05_recovery.json", audit)
        case_report = {
            "contract": "single_view_phase05_v86_case_v1",
            "case_id": case.case_id,
            "family": case.family,
            "optimizer_runtime_id": stage_report.get("optimizer_runtime_id"),
            "accepted": audit["accepted"],
            "start_score": stage_report.get("start_score"),
            "best_score": stage_report.get("best_score"),
            "score_gain": stage_report.get("score_gain"),
            "known_coordinate_recovery_passed": audit[
                "known_coordinate_recovery_passed"
            ],
            "parameter_identity_required": audit["parameter_identity_required"],
            "hard_state_recovery_passed": audit["hard_state_recovery_passed"],
            "timing": stage_report.get("timing"),
            "contact_sheet": stage_report.get("contact_sheet"),
            "best_material": stage_report.get("best_material_path"),
            "requested_target_score": float(target_score),
            "effective_target_score": effective_target_score,
        }
        _write_json(case_dir / "phase05_case_report.json", case_report)
        reports.append(case_report)

    return {
        "contract": "single_view_phase05_v86_campaign_v1",
        "accepted": bool(reports and all(report["accepted"] for report in reports)),
        "asset_id": asset.asset_id,
        "run_dir": str(run_dir),
        "case_count": len(reports),
        "cases": reports,
    }


def _private_case_audit(
    *,
    case: RecoveryStart,
    target_params: dict[str, Any],
    best_params: dict[str, Any],
    stage_report: dict[str, Any],
    success_score: float,
    hard_state_recovery_override: bool | None = None,
) -> dict[str, Any]:
    start_continuous = {
        key: value for key, value in case.params.items() if not key.startswith("__")
    }
    start_summary, start_rows = material_parameter_distance(target_params, start_continuous)
    best_summary, best_rows = material_parameter_distance(target_params, best_params)
    changed_ids = [
        str(row["coordinate"])
        for row in case.perturbation.get("changed_coordinates", [])
    ]
    start_changed = [
        float(start_rows[name]["normalized_abs_error"])
        for name in changed_ids
        if name in start_rows
    ]
    best_changed = [
        float(best_rows[name]["normalized_abs_error"])
        for name in changed_ids
        if name in best_rows
    ]
    start_changed_mean = _mean(start_changed)
    best_changed_mean = _mean(best_changed)
    parameter_identity_required = case.family in {"single_axis", "identifiable_group"}
    known_recovery_passed = bool(
        not parameter_identity_required
        or best_changed_mean <= max(0.20 * start_changed_mean, 0.005)
    )
    hard_state_passed = (
        bool(hard_state_recovery_override)
        if hard_state_recovery_override is not None
        else bool(
            stage_report.get(
                "discrete_state_recovery_passed",
                stage_report.get("discrete_recovery_passed"),
            )
        )
    )
    start_score = stage_report.get("start_score")
    best_score = stage_report.get("best_score")
    image_passed = bool(
        isinstance(start_score, (int, float))
        and isinstance(best_score, (int, float))
        and float(best_score) >= float(success_score)
        and float(best_score) >= float(start_score)
    )
    timing = stage_report.get("timing", {})
    speed_passed = bool(timing.get("gate_passed"))
    accepted = bool(
        image_passed and known_recovery_passed and hard_state_passed and speed_passed
    )
    return {
        "contract": "single_view_phase05_private_parameter_audit_v1",
        "accepted": accepted,
        "optimizer_visible": False,
        "family": case.family,
        "parameter_identity_required": parameter_identity_required,
        "known_changed_coordinate_ids": changed_ids,
        "known_coordinate_start_mean_normalized_error": start_changed_mean,
        "known_coordinate_best_mean_normalized_error": best_changed_mean,
        "known_coordinate_recovery_passed": known_recovery_passed,
        "joint_case_note": (
            "A single image does not uniquely identify all 40 coordinates; joint cases "
            "are accepted by image equivalence and report parameter distance as audit only."
        ),
        "start_parameter_distance": start_summary,
        "best_parameter_distance": best_summary,
        "image_recovery_passed": image_passed,
        "hard_state_recovery_passed": hard_state_passed,
        "hard_state_recovery_source": (
            "frozen_start_private_audit"
            if hard_state_recovery_override is not None
            else "optimizer_result"
        ),
        "speed_gate_passed": speed_passed,
    }


def _select_cases(matrix: Sequence[RecoveryStart], case_ids: Sequence[str]) -> list[RecoveryStart]:
    if not case_ids:
        return list(matrix)
    by_id = {case.case_id: case for case in matrix}
    missing = sorted(set(case_ids) - set(by_id))
    if missing:
        raise ValueError(f"unknown Phase 0.5 cases: {missing}")
    return [by_id[case_id] for case_id in case_ids]


def _frozen_start_matches_target_state(
    case: RecoveryStart,
    target_candidate: dict[str, Any],
) -> bool:
    start_candidate = case.discrete_candidate
    if start_candidate is None:
        _continuous, start_candidate = split_discrete_candidate(case.params)
    return bool(
        start_candidate is not None
        and start_candidate["candidate_id"] == target_candidate["candidate_id"]
    )


def _controlled_search_param_names(case: RecoveryStart) -> list[str] | None:
    if case.family not in {"single_axis", "identifiable_group"}:
        return None
    names = [
        str(row["name"])
        for row in case.perturbation.get("changed_coordinates", [])
        if row.get("name")
    ]
    return list(dict.fromkeys(names))


def _case_target_score(
    case: RecoveryStart,
    *,
    requested_target_score: float,
) -> float:
    if case.family not in {"single_axis", "identifiable_group"}:
        return float(requested_target_score)
    return max(float(requested_target_score), CONTROLLED_RECOVERY_TARGET_SCORE)


def _mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
