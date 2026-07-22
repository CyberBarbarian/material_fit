"""Canonical Stage 2 scoring helpers and pre-run sanity checks."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from material_fit.experiments.stage2_io import read_json, sha256_file, write_json
from material_fit.laya.render_driver import RenderDriver
from material_fit.optimizer.material_discrete_space import attach_discrete_candidate
from material_fit.optimizer.material_recovery import perturb_material_params
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_METRIC,
    ForegroundDISTSAlignedRGBScorer,
)


def _load_acceptance_scorer_sanity(output: Path) -> dict[str, Any]:
    current = output / "stage2_scorer_sanity.json"
    if current.is_file():
        return read_json(current)
    return read_json(output / "frozen_confidence_scorer_sanity.json")


def _aggregate_score(payload: dict[str, Any]) -> float:
    if payload.get("status") != "ok":
        raise RuntimeError(f"initial Stage 2 score failed: {payload}")
    score = float(payload["score"])
    if not 0.0 <= score <= 1.0:
        raise RuntimeError(f"initial Stage 2 score is outside [0, 1]: {score}")
    return score


def _acceptance_score_summary(
    scorer: ForegroundDISTSAlignedRGBScorer,
    reference_path: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    payload = scorer.score_paths(reference_path, candidate_path).as_dict()
    payload.pop("residual_features", None)
    payload["status"] = "ok"
    return payload


def _comparison_label(label: str, score_report: dict[str, Any]) -> str:
    """Format the independently evaluated DISTS score used in evidence sheets."""

    return f"{label} | DISTS {_aggregate_score(score_report):.6f}"


def _run_acceptance_scorer_sanity(
    *,
    run_dir: Path,
    capture_config: dict[str, Any],
    start_params: dict[str, Any],
    start_candidate: dict[str, Any],
) -> dict[str, Any]:
    sanity_capture = copy.deepcopy(capture_config)
    sanity_capture["return_images"] = True
    sanity_capture["browser_score"]["emit_artifacts"] = "always"
    tiny_params, tiny_perturbation = perturb_material_params(
        start_params,
        preset="tiny",
        seed=20260719,
    )
    mild_params, mild_perturbation = perturb_material_params(
        start_params,
        preset="mild",
        seed=20260719,
    )
    candidates = (
        ("same_a", start_params),
        ("same_b", start_params),
        ("tiny", tiny_params),
        ("mild", mild_params),
    )
    driver = RenderDriver(
        output_dir=run_dir / "scorer_sanity" / "runtime",
        dry_run=False,
        capture_config=sanity_capture,
    )
    rows: list[dict[str, Any]] = []
    try:
        for iteration, (name, params) in enumerate(candidates):
            result = driver.render_candidate(
                iteration,
                attach_discrete_candidate(params, start_candidate),
            )
            screenshots = result.get("screenshots") or []
            if result.get("status") != "ok" or len(screenshots) != 1:
                raise RuntimeError(f"Stage 2 scorer sanity render {name} failed: {result}")
            browser_score = result.get("browser_score") or {}
            rows.append(
                {
                    "name": name,
                    "path": str(screenshots[0]),
                    "sha256": sha256_file(Path(screenshots[0])),
                    "unity_target_browser_fit_score": browser_score.get("fit_score"),
                }
            )
    finally:
        driver.close()

    acceptance_scorer = ForegroundDISTSAlignedRGBScorer()
    for row in rows:
        score = acceptance_scorer.score_paths(
            rows[0]["path"],
            row["path"],
        ).as_dict()
        row["same_start_material_score"] = score["score"]
        row["same_start_material_score_payload"] = {
            key: value for key, value in score.items() if key != "residual_features"
        }
        row["status"] = "ok"

    by_name = {str(row["name"]): row for row in rows}
    same_a = float(by_name["same_a"]["same_start_material_score"])
    same_b = float(by_name["same_b"]["same_start_material_score"])
    tiny = float(by_name["tiny"]["same_start_material_score"])
    mild = float(by_name["mild"]["same_start_material_score"])
    checks = {
        "same_params_near_one": min(same_a, same_b) >= 0.9999,
        "same_params_deterministic": abs(same_a - same_b) <= 1.0e-9,
        "tiny_perturbation_continuous": tiny >= 0.98,
        "mild_perturbation_distinguishable": mild <= tiny - 1.0e-4,
        "perturbation_order": same_b >= tiny > mild,
    }
    report = {
        "contract": "material_fit_stage2_dists_sanity_v1",
        "metric": DISTS_ALIGNED_RGB_METRIC,
        "passed": all(checks.values()),
        "checks": checks,
        "rows": rows,
        "tiny_perturbation": tiny_perturbation,
        "mild_perturbation": mild_perturbation,
        "target_material_or_params_visible": False,
    }
    write_json(run_dir / "stage2_scorer_sanity.json", report)
    return report


__all__: list[str] = []
