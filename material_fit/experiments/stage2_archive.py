"""Stage 2 full-resolution refinement and archive reranking."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.single_view_runtime import build_single_view_driver
from material_fit.experiments.stage2_io import read_json, write_json
from material_fit.laya.render_driver import RenderDriver
from material_fit.optimizer.material_discrete_space import (
    attach_discrete_candidate,
    split_discrete_candidate,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_ONLY_COORDINATES,
)
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_METRIC,
    ForegroundDISTSAlignedRGBScorer,
)
from material_fit.vision.stage2_registration import apply_frozen_stage2_registration

from material_fit.experiments.stage2_scoring import _acceptance_score_summary


FINAL_ACCEPTANCE_RERANK_TOP_K = 20
FINAL_REGISTERED_PATTERN_MAX_PROPOSALS = 80


def _refine_with_registered_browser_score(
    *,
    output: Path,
    capture_config: dict[str, Any],
    full_resolution_profile_path: Path,
    target_path: Path,
    registration: dict[str, Any],
    initial_params: dict[str, Any],
    max_proposals: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Spend the reserved tail budget on a registered full-canvas pattern sweep."""

    refine_root = output / "registered_pattern_refine"
    report_path = refine_root / "report.json"
    selected_params_path = refine_root / "selected_params.json"
    if report_path.is_file() and selected_params_path.is_file():
        return read_json(selected_params_path), read_json(report_path)
    budget = max(0, min(int(max_proposals), FINAL_REGISTERED_PATTERN_MAX_PROPOSALS))
    if budget == 0:
        report = {
            "contract": "material_fit_stage2_registered_pattern_refine_v1",
            "status": "skipped",
            "reason": "no proposal budget remained",
            "new_material_proposals": 0,
            "target_material_or_params_visible": False,
            "human_adjusted_material_or_params_visible": False,
        }
        write_json(selected_params_path, initial_params)
        write_json(report_path, report)
        return copy.deepcopy(initial_params), report

    local_capture = copy.deepcopy(capture_config)
    runtime = local_capture["runtime_bridge"]
    runtime["state_dir"] = str(refine_root / "runtime_renderer")
    runtime["asset_profile"] = str(full_resolution_profile_path.resolve())
    browser_score = local_capture["browser_score"]
    full_profile = read_json(full_resolution_profile_path)
    full_width = int(full_profile["width"])
    full_height = int(full_profile["height"])
    browser_score.update(
        {
            "readback_width": full_width,
            "readback_height": full_height,
            "render_width": full_width,
            "render_height": full_height,
        }
    )
    references = browser_score.get("reference_images")
    if not isinstance(references, list) or len(references) != 1:
        raise RuntimeError("registered pattern refinement requires one reference")
    references[0]["path"] = str(target_path)
    references[0].pop("url", None)
    browser_score["candidate_registration"] = copy.deepcopy(registration)
    browser_score["emit_artifacts"] = "never"
    local_capture["return_images"] = False
    local_capture["persist_browser_score"] = False

    driver = RenderDriver(
        output_dir=refine_root / "runtime",
        dry_run=False,
        capture_config=local_capture,
    )
    best_params = copy.deepcopy(initial_params)
    rows: list[dict[str, Any]] = []
    render_times_ms: list[float] = []
    seen = {_params_identity(best_params)}

    try:
        started = time.perf_counter()
        initial_result = driver.render_candidate(0, best_params)
        render_times_ms.append((time.perf_counter() - started) * 1000.0)
        initial_browser_score = _browser_fit_score(initial_result)
        best_score = initial_browser_score
        proposal_index = 0
        for coordinate in STRUCTURED_MATERIAL_ONLY_COORDINATES:
            if proposal_index >= budget:
                break
            center = copy.deepcopy(best_params)
            center_value = coordinate.read(center)
            local: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
            for direction in (-1.0, 1.0):
                if proposal_index >= budget:
                    break
                candidate = coordinate.write(
                    center,
                    center_value + direction * coordinate.initial_step / 16.0,
                )
                identity = _params_identity(candidate)
                if identity in seen:
                    continue
                seen.add(identity)
                proposal_index += 1
                started = time.perf_counter()
                result = driver.render_candidate(proposal_index, candidate)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                render_times_ms.append(elapsed_ms)
                score = _browser_fit_score(result)
                row = {
                    "proposal": proposal_index,
                    "coordinate": coordinate.coordinate_id,
                    "direction": direction,
                    "value": coordinate.read(candidate),
                    "registered_browser_score": score,
                    "elapsed_ms": elapsed_ms,
                }
                rows.append(row)
                local.append((score, candidate, row))
            if local:
                score, candidate, row = max(local, key=lambda item: item[0])
                if score > best_score:
                    best_score = score
                    best_params = candidate
                    row["accepted"] = True
    finally:
        driver.close()

    decision_times = sorted(render_times_ms[1:])
    decision_mean_ms = (
        sum(decision_times) / len(decision_times) if decision_times else None
    )
    decision_p95_ms = (
        decision_times[min(len(decision_times) - 1, int(0.95 * len(decision_times)))]
        if decision_times
        else None
    )
    write_json(selected_params_path, best_params)
    report = {
        "contract": "material_fit_stage2_registered_pattern_refine_v1",
        "status": "ok",
        "metric": DISTS_ALIGNED_RGB_METRIC,
        "candidate_registration": copy.deepcopy(registration),
        "score_resolution": [full_width, full_height],
        "role": "full_resolution_tail_refine",
        "step_policy": "structured_coordinate_initial_step_div_16_single_greedy_sweep",
        "initial_registered_browser_score": initial_browser_score,
        "best_registered_browser_score": best_score,
        "new_material_proposals": len(rows),
        "maximum_new_material_proposals": budget,
        "decision_mean_ms": decision_mean_ms,
        "decision_p95_ms": decision_p95_ms,
        "target_source": str(target_path),
        "target_material_or_params_visible": False,
        "human_adjusted_material_or_params_visible": False,
        "scene_or_geometry_coordinates_changed": False,
        "rows": rows,
    }
    write_json(report_path, report)
    return best_params, report


def _browser_fit_score(result: dict[str, Any]) -> float:
    if result.get("status") != "ok":
        raise RuntimeError(f"registered browser scoring failed: {result}")
    browser_score = result.get("browser_score")
    if not isinstance(browser_score, dict):
        report = result.get("report")
        browser_score = report.get("browser_score") if isinstance(report, dict) else None
    if not isinstance(browser_score, dict) or browser_score.get("status", "ok") != "ok":
        raise RuntimeError(f"registered browser score missing: {result}")
    score = float(browser_score["fit_score"])
    if not 0.0 <= score <= 1.0:
        raise RuntimeError(f"registered browser score outside [0, 1]: {score}")
    return score


def _rerank_optimizer_archive(
    *,
    output: Path,
    profile_path: Path,
    target_path: Path,
    optimizer_view: dict[str, Any],
    reference_view: dict[str, Any],
    registration: dict[str, Any],
    start_patch: dict[str, Any],
    optimizer_best_params: dict[str, Any],
    node_modules: Path,
    top_k: int = FINAL_ACCEPTANCE_RERANK_TOP_K,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-score already proposed elites with the canonical full-resolution scorer."""

    rerank_root = output / "acceptance_rerank"
    report_path = rerank_root / "report.json"
    selected_params_path = rerank_root / "selected_params.json"
    if report_path.is_file() and selected_params_path.is_file():
        return read_json(selected_params_path), read_json(report_path)

    archive_path = output / "output" / "auto_adjust" / "optimizer_candidate_archive.json"
    candidates = _load_archive_rerank_candidates(
        archive_path,
        optimizer_best_params=optimizer_best_params,
        top_k=top_k,
    )
    raw_root = rerank_root / "raw"
    registered_root = rerank_root / "registered"
    driver = build_single_view_driver(
        profile_path=profile_path,
        output_root=rerank_root / "runtime",
        material_patch={
            "target_name": "model",
            "defines": copy.deepcopy(start_patch["defines"]),
            "render_states": copy.deepcopy(start_patch["render_states"]),
        },
        node_modules=node_modules,
        reference_path=None,
        return_images=True,
    )
    rows: list[dict[str, Any]] = []
    acceptance_scorer = ForegroundDISTSAlignedRGBScorer()
    try:
        for index, candidate in enumerate(candidates):
            candidate_id = f"candidate_{index:02d}"
            params = candidate["params"]
            candidate_raw_dir = raw_root / candidate_id
            candidate_registered_dir = registered_root / candidate_id
            phase05._capture_artifact_set(
                driver=driver,
                artifact_dir=candidate_raw_dir,
                params=params,
                views=[optimizer_view],
                iteration=index,
            )
            apply_frozen_stage2_registration(
                raw_dir=candidate_raw_dir,
                output_dir=candidate_registered_dir,
                views=[copy.deepcopy(reference_view)],
                registration=registration,
            )
            registered_path = candidate_registered_dir / str(optimizer_view["file_name"])
            score = _acceptance_score_summary(
                acceptance_scorer,
                target_path,
                registered_path,
            )
            params_path = rerank_root / "params" / f"{candidate_id}.json"
            write_json(params_path, params)
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "archive_rank": candidate["archive_rank"],
                    "archive_iteration": candidate["archive_iteration"],
                    "online_fit_score": candidate["online_fit_score"],
                    "canonical_score": float(score["score"]),
                    "canonical_score_payload": score,
                    "params_path": str(params_path),
                    "registered_render": str(registered_path),
                    "params_sha256": hashlib.sha256(
                        _params_identity(params).encode("utf-8")
                    ).hexdigest(),
                }
            )
    finally:
        driver.close()

    rows.sort(
        key=lambda row: (
            -float(row["canonical_score"]),
            int(row["archive_rank"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["canonical_rank"] = rank
    selected = rows[0]
    selected_params = read_json(Path(selected["params_path"]))
    write_json(selected_params_path, selected_params)
    report = {
        "contract": "material_fit_stage2_canonical_acceptance_rerank_v1",
        "selection_metric": DISTS_ALIGNED_RGB_METRIC,
        "archive_path": str(archive_path),
        "archive_top_k_requested": int(top_k),
        "unique_existing_materials_rescored": len(rows),
        "new_material_proposals": 0,
        "target_material_or_params_visible": False,
        "human_adjusted_material_or_params_visible": False,
        "selected": copy.deepcopy(selected),
        "candidates": rows,
    }
    write_json(report_path, report)
    return selected_params, report


def _load_archive_rerank_candidates(
    archive_path: Path,
    *,
    optimizer_best_params: dict[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    def evidence_params(raw: dict[str, Any]) -> dict[str, Any]:
        continuous, discrete = split_discrete_candidate(raw)
        if discrete is None:
            raise RuntimeError(
                "optimizer archive candidate is missing its discrete material state"
            )
        return attach_discrete_candidate(continuous, discrete)

    archive = read_json(archive_path)
    raw_candidates = archive.get("candidates", []) if isinstance(archive, dict) else []
    candidates: list[dict[str, Any]] = [
        {
            "archive_rank": 0,
            "archive_iteration": None,
            "online_fit_score": None,
            "params": evidence_params(optimizer_best_params),
        }
    ]
    for item in raw_candidates[: max(0, int(top_k))]:
        if not isinstance(item, dict):
            continue
        params = item.get("scored_params") or item.get("candidate_params")
        if not isinstance(params, dict):
            continue
        candidates.append(
            {
                "archive_rank": int(item.get("rank") or len(candidates)),
                "archive_iteration": item.get("iteration"),
                "online_fit_score": item.get("fit_score"),
                "params": evidence_params(params),
            }
        )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = _params_identity(candidate["params"])
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
    if not unique:
        raise RuntimeError("optimizer archive did not contain any rerankable material")
    return unique


def _params_identity(params: dict[str, Any]) -> str:
    return json.dumps(
        params,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "FINAL_ACCEPTANCE_RERANK_TOP_K",
    "FINAL_REGISTERED_PATTERN_MAX_PROPOSALS",
]
