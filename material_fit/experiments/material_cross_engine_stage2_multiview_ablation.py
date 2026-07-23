"""Compare one-view and eight-view PNG-only material fitting on the 1613 asset."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.assets.stage2_unity_references import resolve_stage2_unity_references
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)
from material_fit.vision.cross_engine_score import score_cross_engine_views_v3


ASSET_ID = "holiday_1613"
SINGLE_VIEW_ID = "v000_yaw0_pitch0"
OPTIMIZER_WIDTH = 720
OPTIMIZER_HEIGHT = 560
OPTIMIZER_METRIC = phase05.OPTIMIZATION_SCORE_METRIC
VALIDATION_METRIC = phase05.VALIDATION_SCORE_METRIC


def run_multiview_ablation(
    *,
    repo_root: Path,
    run_dir: Path,
    iterations: int = 300,
    target_score: float = 0.999,
    max_runtime_sec_per_variant: float = 900.0,
    node_modules: Path | None = None,
) -> dict[str, Any]:
    """Run matched-budget 0-degree and eight-view fits, then score both on eight views."""

    root = repo_root.resolve()
    output = run_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    asset = resolve_material_asset(root, ASSET_ID)
    references = resolve_stage2_unity_references(root, ASSET_ID)
    full_profile_path = asset.write_profile(output / "inputs" / "asset_profile.json")
    phase05._force_white_background(full_profile_path)
    full_views = phase05._profile_views(full_profile_path, expected_count=8)
    single_views = _select_views(full_views, (SINGLE_VIEW_ID,))
    _validate_frozen_camera(asset.profile)

    start_material_path = asset.target_material_path
    start_params = lmat_io.extract_params(lmat_io.load_lmat(start_material_path))
    missing = [name for name in STRUCTURED_MATERIAL_PARAM_NAMES if name not in start_params]
    if missing:
        raise ValueError(f"1613 start material is missing structured coordinates: {missing}")
    start_patch = material_patch_from_lmat(start_material_path)
    _write_json(output / "inputs" / "start_params.json", start_params)

    target_dir = output / "target_render"
    _copy_unity_targets(references, full_views, target_dir)
    optimizer_target_dir = output / "optimizer_target_render"
    _copy_unity_targets(
        references,
        full_views,
        optimizer_target_dir,
        output_size=(OPTIMIZER_WIDTH, OPTIMIZER_HEIGHT),
    )

    start_driver = phase05._build_artifact_capture_driver(
        profile_path=full_profile_path,
        output_root=output / "start_capture" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=VALIDATION_METRIC,
    )
    try:
        start_result = phase05._capture_artifact_set(
            driver=start_driver,
            artifact_dir=output / "start_render",
            params=start_params,
            views=full_views,
            iteration=0,
        )
    finally:
        start_driver.close()
    start_evaluation = _evaluation_payload(
        result=start_result,
        target_dir=target_dir,
        candidate_dir=output / "start_render",
        views=full_views,
    )

    variants: dict[str, Any] = {}
    for variant_id, views in (("single_view", single_views), ("eight_view", full_views)):
        variants[variant_id] = _run_variant(
            repo_root=root,
            run_dir=output / variant_id,
            asset=asset,
            full_profile_path=full_profile_path,
            full_views=full_views,
            optimization_views=views,
            start_material_path=start_material_path,
            start_params=start_params,
            start_patch=start_patch,
            optimizer_target_dir=optimizer_target_dir,
            target_dir=target_dir,
            iterations=int(iterations),
            target_score=float(target_score),
            max_runtime_sec=float(max_runtime_sec_per_variant),
            node_modules=node_modules,
        )

    contact_sheet = phase05._write_contact_sheet(
        views=full_views,
        columns=(
            ("Unity target", target_dir),
            ("Original Laya", output / "start_render"),
            ("0 deg optimized", Path(variants["single_view"]["best_render_dir"])),
            ("8-view optimized", Path(variants["eight_view"]["best_render_dir"])),
        ),
        output_path=output / "unity_start_single_eight_contact_sheet.png",
    )
    cleanup = phase05._cleanup_recorded_runtime(output)
    single_score = _python_score(variants["single_view"]["evaluation"])
    eight_score = _python_score(variants["eight_view"]["evaluation"])
    start_score = _python_score(start_evaluation)
    report = {
        "contract": "material_fit_stage2_multiview_ablation_v1",
        "asset_id": asset.asset_id,
        "run_dir": str(output),
        "hypothesis": "eight-view optimization improves held-out orientation robustness",
        "controlled_variables": {
            "proposal_budget_per_variant": int(iterations),
            "optimizer": phase05.OPTIMIZER_ID,
            "searchable_coordinates": list(STRUCTURED_MATERIAL_PARAM_NAMES),
            "scene_coordinates_fixed": list(STRUCTURED_SCENE_PARAM_NAMES),
            "camera_frozen": True,
            "discrete_state_fixed_from_start_material": True,
            "target_source": "tracked_unity_png_only",
        },
        "start_evaluation": start_evaluation,
        "variants": variants,
        "eight_view_python_score_delta_vs_single": eight_score - single_score,
        "single_view_python_score_gain_vs_start": single_score - start_score,
        "eight_view_python_score_gain_vs_start": eight_score - start_score,
        "eight_view_wins_full_eight_view_evaluation": eight_score > single_score,
        "contact_sheet": str(contact_sheet),
        "process_cleanup": cleanup,
    }
    _write_json(output / "stage2_multiview_ablation_report.json", report)
    return report


def _run_variant(
    *,
    repo_root: Path,
    run_dir: Path,
    asset: Any,
    full_profile_path: Path,
    full_views: list[dict[str, Any]],
    optimization_views: list[dict[str, Any]],
    start_material_path: Path,
    start_params: dict[str, Any],
    start_patch: dict[str, Any],
    optimizer_target_dir: Path,
    target_dir: Path,
    iterations: int,
    target_score: float,
    max_runtime_sec: float,
    node_modules: Path | None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=False)
    profile_path = _write_variant_profile(
        full_profile_path,
        run_dir / "inputs" / "optimizer_asset_profile.json",
        optimization_views,
        width=OPTIMIZER_WIDTH,
        height=OPTIMIZER_HEIGHT,
    )
    sanity_reference_dir = run_dir / "scorer_sanity" / "start_reference"
    sanity_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=run_dir / "scorer_sanity" / "reference_runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=None,
        node_modules=node_modules,
    )
    try:
        phase05._capture_artifact_set(
            driver=sanity_driver,
            artifact_dir=sanity_reference_dir,
            params=start_params,
            views=optimization_views,
            iteration=0,
        )
    finally:
        sanity_driver.close()
    repeat_driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=run_dir / "scorer_sanity" / "repeat_runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=sanity_reference_dir,
        node_modules=node_modules,
        score_metric=VALIDATION_METRIC,
    )
    try:
        repeat_result = phase05._capture_artifact_set(
            driver=repeat_driver,
            artifact_dir=run_dir / "scorer_sanity" / "start_repeat",
            params=start_params,
            views=optimization_views,
            iteration=0,
        )
    finally:
        repeat_driver.close()
    repeat_score = phase05._browser_fit_score(repeat_result)
    if repeat_score is None or repeat_score < 0.995:
        raise RuntimeError(f"same-parameter scorer sanity failed: {repeat_score}")

    config = phase05._build_fit_config(
        asset=asset,
        profile_path=profile_path,
        run_dir=run_dir,
        start_material_path=start_material_path,
        target_dir=optimizer_target_dir,
        target_defines=start_patch["defines"],
        target_render_states=start_patch["render_states"],
        target_score=target_score,
        node_modules=node_modules,
        views=optimization_views,
    )
    config["material_jacobian_trust_region"]["shader_default_anchor_enabled"] = False
    config["browser_score_objective"] = {"mode": "mean"}
    config["stage2_optimizer_contract"] = {
        "phase": "cross_engine_stage2_multiview_ablation",
        "view_ids": [str(view["view_id"]) for view in optimization_views],
        "target_source": "tracked_unity_png_only",
        "target_material_visible": False,
        "target_params_visible": False,
        "camera_searchable": False,
        "scene_coordinates_searchable": False,
        "searchable_coordinate_count": len(STRUCTURED_MATERIAL_PARAM_NAMES),
        "browser_aggregation": "0.70*mean + 0.20*p10 + 0.10*min",
    }
    config_path = run_dir / "fit_config.json"
    _write_json(config_path, config)
    fit_started = time.perf_counter()
    returncode = phase05._run_fit_owned(
        repo_root=repo_root,
        run_dir=run_dir,
        config_path=config_path,
        iterations=iterations,
        target_score=target_score,
        max_runtime_sec=max_runtime_sec,
    )
    fit_elapsed_s = time.perf_counter() - fit_started
    if returncode != 0:
        raise RuntimeError(f"{run_dir.name} fit exited with {returncode}; see {run_dir / 'logs'}")

    best_params_path = run_dir / "output" / "auto_adjust" / "best" / "params.json"
    best_params = json.loads(best_params_path.read_text(encoding="utf-8"))
    full_driver = phase05._build_artifact_capture_driver(
        profile_path=full_profile_path,
        output_root=run_dir / "final_capture" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=VALIDATION_METRIC,
    )
    try:
        best_result = phase05._capture_artifact_set(
            driver=full_driver,
            artifact_dir=run_dir / "best_render",
            params=best_params,
            views=full_views,
            iteration=0,
        )
    finally:
        full_driver.close()
    lmat_io.write_candidate_lmat(
        start_material_path,
        run_dir / "best_material.lmat",
        best_params,
        allow_missing_keys=True,
    )
    timing = phase05._timing_report(
        run_dir / "output" / "auto_adjust" / "iteration_series.json",
        speed_gate_ms=500.0,
    )
    online_score_progress = _optimizer_score_progress(
        run_dir / "output" / "auto_adjust" / "iteration_series.json"
    )
    cleanup = phase05._cleanup_recorded_runtime(run_dir)
    evaluation = _evaluation_payload(
        result=best_result,
        target_dir=target_dir,
        candidate_dir=run_dir / "best_render",
        views=full_views,
    )
    result = {
        "optimization_view_ids": [str(view["view_id"]) for view in optimization_views],
        "optimization_view_count": len(optimization_views),
        "iterations_requested": iterations,
        "fit_elapsed_s": fit_elapsed_s,
        "same_parameter_scorer_sanity": repeat_score,
        "online_score_progress": online_score_progress,
        "timing": timing,
        "evaluation": evaluation,
        "best_params_path": str(best_params_path),
        "best_material_path": str(run_dir / "best_material.lmat"),
        "best_render_dir": str(run_dir / "best_render"),
        "process_cleanup": cleanup,
    }
    _write_json(run_dir / "variant_report.json", result)
    return result


def _select_views(
    views: list[dict[str, Any]],
    view_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not view_ids:
        raise ValueError("at least one view is required")
    if len(set(view_ids)) != len(view_ids):
        raise ValueError(f"requested views contain duplicates: {view_ids}")
    available = {str(view["view_id"]): view for view in views}
    missing = [view_id for view_id in view_ids if view_id not in available]
    if missing:
        raise ValueError(f"requested views are unavailable: {missing}")
    return [copy.deepcopy(available[view_id]) for view_id in view_ids]


def _validate_frozen_camera(profile: dict[str, Any]) -> None:
    calibration = profile.get("camera_calibration")
    camera = profile.get("runtime", {}).get("camera", {})
    if not isinstance(calibration, dict) or calibration.get("alignment_passed") is not True:
        raise ValueError("1613 camera calibration is not frozen and accepted")
    if float(camera.get("orthographic_vertical_size", 0.0)) != float(
        calibration.get("orthographic_vertical_size", -1.0)
    ):
        raise ValueError("1613 runtime orthographic size differs from frozen calibration")
    if camera.get("center_offset") != calibration.get("center_offset"):
        raise ValueError("1613 runtime center offset differs from frozen calibration")


def _write_variant_profile(
    source_path: Path,
    output_path: Path,
    views: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> Path:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["width"] = int(width)
    payload["height"] = int(height)
    payload.setdefault("capture_defaults", {})["views"] = copy.deepcopy(views)
    _write_json(output_path, payload)
    return output_path


def _copy_unity_targets(
    references: Any,
    views: list[dict[str, Any]],
    output_dir: Path,
    *,
    output_size: tuple[int, int] | None = None,
) -> None:
    by_id = {str(view["view_id"]): view for view in references.views}
    output_dir.mkdir(parents=True, exist_ok=True)
    for view in views:
        source_view = by_id[str(view["view_id"])]
        source = references.root / str(source_view["reference_file_name"])
        destination = output_dir / str(view["file_name"])
        if output_size is None:
            shutil.copy2(source, destination)
            continue
        with Image.open(source) as image:
            image.convert("RGBA").resize(output_size, Image.Resampling.LANCZOS).save(destination)


def _evaluation_payload(
    *,
    result: dict[str, Any],
    target_dir: Path,
    candidate_dir: Path,
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    python_score = score_cross_engine_views_v3(
        reference_dir=target_dir,
        candidate_dir=candidate_dir,
        views=views,
    )
    if not isinstance(python_score, dict) or python_score.get("status") != "ok":
        raise RuntimeError(f"independent eight-view score failed: {python_score}")
    browser = result.get("browser_score")
    if not isinstance(browser, dict):
        browser = result.get("report", {}).get("browser_score")
    if not isinstance(browser, dict):
        raise RuntimeError("artifact capture did not return a browser score")
    return {
        "python_cross_engine_v3": python_score,
        "browser_cross_engine_v4": browser,
    }


def _python_score(evaluation: dict[str, Any]) -> float:
    return float(evaluation["python_cross_engine_v3"]["score"])


def _optimizer_score_progress(path: Path) -> dict[str, float | int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("iterations", [])
    scores = [
        float(row["fit_score_before"])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("fit_score_before"), (int, float))
    ]
    if not scores:
        raise ValueError(f"optimizer series has no fit scores: {path}")
    return {
        "scored_material_count": len(scores),
        "initial_fit_score": scores[0],
        "best_fit_score": max(scores),
        "online_score_gain": max(scores) - scores[0],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--target-score", type=float, default=0.999)
    parser.add_argument("--max-runtime-sec-per-variant", type=float, default=900.0)
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else repo_root / "artifacts"
    )
    run_name = args.run_name or (
        f"stage2_1613_single_vs_eight_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = output_root / run_name
    try:
        report = run_multiview_ablation(
            repo_root=repo_root,
            run_dir=run_dir,
            iterations=args.iterations,
            target_score=args.target_score,
            max_runtime_sec_per_variant=args.max_runtime_sec_per_variant,
            node_modules=(
                Path(args.node_modules).expanduser().resolve()
                if args.node_modules
                else None
            ),
        )
    finally:
        if run_dir.exists():
            phase05._cleanup_recorded_runtime(run_dir)
    print(
        json.dumps(
            {
                "run_dir": report["run_dir"],
                "start_python_score": _python_score(report["start_evaluation"]),
                "single_view_python_score": _python_score(
                    report["variants"]["single_view"]["evaluation"]
                ),
                "eight_view_python_score": _python_score(
                    report["variants"]["eight_view"]["evaluation"]
                ),
                "eight_view_delta_vs_single": report[
                    "eight_view_python_score_delta_vs_single"
                ],
                "contact_sheet": report["contact_sheet"],
                "report": str(run_dir / "stage2_multiview_ablation_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_multiview_ablation"]
