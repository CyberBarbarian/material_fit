"""Validate target-independent discrete-state recovery with real Laya renders."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.material_stage1 import resolve_material_stage1_asset
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.material_human_reference_stage1 import (
    STAGE1_OPTIMIZATION_SCORE_METRIC,
    STAGE1_SCORE_READBACK_HEIGHT,
    STAGE1_SCORE_READBACK_WIDTH,
    _write_optimizer_profile,
    _write_profile,
)
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    find_candidate_for_patch,
)


DEFAULT_CASE_IDS = (
    "normal=flat|rim=0|blend_src=0",
    "normal=legacy_y_invert_only|rim=1|blend_src=0",
    "normal=normal|rim=1|blend_src=1",
    "normal=normal_y_invert|rim=1|blend_src=0",
)
VISUAL_EQUIVALENCE_TOLERANCE = 1.0e-6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, choices=("fish", "turtle", "crocodile"))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--engine-libs", default="")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    if args.engine_libs:
        os.environ["LAYA_ENGINE_LIBS"] = str(Path(args.engine_libs).expanduser().resolve())
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else repo_root / "artifacts"
    )
    run_name = args.run_name or (
        f"discrete_drift_{args.asset}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        report = run_validation(
            repo_root=repo_root,
            run_dir=run_dir,
            asset_id=args.asset,
            node_modules=args.node_modules or None,
        )
    finally:
        phase05._cleanup_recorded_runtime(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


def run_validation(
    *,
    repo_root: Path,
    run_dir: Path,
    asset_id: str,
    node_modules: str | Path | None,
) -> dict[str, Any]:
    asset = resolve_material_stage1_asset(repo_root, asset_id)
    profile = _write_profile(asset, run_dir / "inputs/asset_profile.json")
    phase05._force_white_background(profile)
    optimizer_profile = _write_optimizer_profile(
        profile,
        run_dir / "inputs/optimizer_asset_profile.json",
        width=STAGE1_SCORE_READBACK_WIDTH,
        height=STAGE1_SCORE_READBACK_HEIGHT,
    )
    views = phase05._profile_views(optimizer_profile)
    params = lmat_io.extract_params(lmat_io.load_lmat(asset.start_material_path))
    start_patch = material_patch_from_lmat(asset.start_material_path)
    candidates = build_legal_discrete_candidates(start_patch)
    start_candidate = find_candidate_for_patch(candidates, start_patch)
    by_id = {str(row["candidate_id"]): row for row in candidates}
    missing = [candidate_id for candidate_id in DEFAULT_CASE_IDS if candidate_id not in by_id]
    if missing:
        raise RuntimeError(f"discrete validation cases are outside the legal space: {missing}")

    case_reports: list[dict[str, Any]] = []
    shared_driver = phase05._build_artifact_capture_driver(
        profile_path=optimizer_profile,
        output_root=run_dir / "shared_runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        for case_index, target_id in enumerate(DEFAULT_CASE_IDS):
            target_candidate = by_id[target_id]
            case_dir = run_dir / f"case_{case_index:02d}_{_safe_name(target_id)}"
            target_dir = case_dir / "target_render"
            shared_driver.capture_config["return_images"] = True
            shared_driver.capture_config["browser_score"] = {"enabled": False}
            phase05._capture_artifact_set(
                driver=shared_driver,
                artifact_dir=target_dir,
                params=attach_discrete_candidate(params, target_candidate),
                views=views,
                iteration=case_index * 1000,
            )
            shared_driver.capture_config["return_images"] = False
            shared_driver.capture_config["persist_browser_score"] = False
            shared_driver.capture_config["browser_score"] = {
                "enabled": True,
                "metric": STAGE1_OPTIMIZATION_SCORE_METRIC,
                "rgb_weight": 1.0,
                "alpha_weight": 0.0,
                "emit_artifacts": "never",
                "residual_grid_size": 16,
                "reference_images": phase05._reference_images(target_dir, views),
            }
            rows: list[dict[str, Any]] = []
            for candidate_index, candidate in enumerate(candidates):
                result = shared_driver.render_candidate(
                    case_index * 1000 + 100 + candidate_index,
                    attach_discrete_candidate(params, candidate),
                )
                if result.get("status") != "ok":
                    raise RuntimeError(
                        f"discrete validation render failed: {target_id}/{candidate['candidate_id']}"
                    )
                browser = result.get("browser_score")
                if not isinstance(browser, dict):
                    raise RuntimeError("discrete validation render returned no browser score")
                patch = browser.get("material_patch")
                patch = patch if isinstance(patch, dict) else {}
                rows.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "axes": copy.deepcopy(candidate["axes"]),
                        "fit_score": float(browser.get("fit_score", browser.get("score"))),
                        "enabled_defines": patch.get(
                            "enabled_defines",
                            patch.get("enabledDefines", []),
                        ),
                        "applied_render_states": patch.get(
                            "applied_render_states",
                            patch.get("appliedRenderStates", {}),
                        ),
                    }
                )
            rows.sort(key=lambda row: (-float(row["fit_score"]), str(row["candidate_id"])))
            best_score = float(rows[0]["fit_score"])
            equivalence_tolerance = VISUAL_EQUIVALENCE_TOLERANCE
            equivalence_ids = [
                str(row["candidate_id"])
                for row in rows
                if best_score - float(row["fit_score"]) <= equivalence_tolerance
            ]
            target_row = next(row for row in rows if row["candidate_id"] == target_id)
            start_row = next(
                row for row in rows if row["candidate_id"] == start_candidate["candidate_id"]
            )
            case_reports.append(
                {
                    "case_id": target_id,
                    "passed": target_id in equivalence_ids
                    and float(target_row["fit_score"]) >= 0.99999,
                    "target_candidate_private_test_fixture": copy.deepcopy(target_candidate),
                    "start_candidate_id": start_candidate["candidate_id"],
                    "start_score": start_row["fit_score"],
                    "target_score": target_row["fit_score"],
                    "best_score": best_score,
                    "best_candidate_id": rows[0]["candidate_id"],
                    "best_visual_equivalence_class": equivalence_ids,
                    "equivalence_tolerance": equivalence_tolerance,
                    "candidate_count": len(rows),
                    "rows": rows,
                    "target_render_dir": str(target_dir),
                }
            )
    finally:
        shared_driver.close()

    cleanup = phase05._cleanup_recorded_runtime(run_dir)
    report = {
        "contract": "material_discrete_drift_validation_v1",
        "accepted": all(row["passed"] for row in case_reports)
        and cleanup["remaining_owned_pid_count"] == 0,
        "asset_id": asset.asset_id,
        "candidate_count": len(candidates),
        "case_count": len(case_reports),
        "cases_passed": sum(bool(row["passed"]) for row in case_reports),
        "optimizer_visible_target_state": False,
        "continuous_params_identical_across_target_and_candidates": True,
        "cases": case_reports,
        "process_cleanup": cleanup,
    }
    (run_dir / "discrete_drift_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
