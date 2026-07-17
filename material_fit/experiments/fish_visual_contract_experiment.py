"""Validate fish alignment and scorer behavior with controlled real renders."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.fish_scene import resolve_fish_scene_assets
from material_fit.experiments import fish_core_experiment as core
from material_fit.laya.lmat_io import extract_params, load_lmat
from material_fit.laya.render_driver import RenderDriver
from material_fit.vision.cross_engine_score import score_cross_engine_views


PERTURBATION_LEVELS = (
    ("same_a", 0.0),
    ("same_b", 0.0),
    ("tiny", 0.02),
    ("mild", 0.10),
    ("medium", 0.30),
    ("strong", 0.60),
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    run_name = args.run_name or f"fish_visual_contract_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = (Path(args.output_root) if args.output_root else repo_root / "artifacts") / run_name
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)

    assets = resolve_fish_scene_assets(repo_root)
    selected = core._select_assets_for_mode(assets, "material", "active")
    cap_port = core._find_free_port()
    http_port = core._find_free_port(exclude={cap_port})
    engine_root = core._resolve_engine_root(str(args.engine_root or ""))
    core._require_laya_engine(engine_root)
    core._ensure_playwright_chromium(repo_root)

    working_material = run_dir / "1504_new_test_visual_contract.lmat"
    shutil.copy2(selected["baseline_material_path"], working_material)
    config = core._build_config(
        repo_root=repo_root,
        assets=assets,
        selected=selected,
        run_dir=run_dir,
        mode="material",
        working_material=working_material,
        cap_port=cap_port,
        width=int(args.width),
        height=int(args.height),
        http_port=http_port,
        render_backend="runtime",
        oracle_base=None,
        external_render_command="",
        optimizer="pattern16",
        target_score=0.999,
        search_param_space="",
        initial_params_override="",
    )
    settle_frames = max(0, int(args.settle_frames))
    capture_config = config["laya_capture"]
    capture_config["settle_frames"] = settle_frames
    capture_config["animation_freeze_settle_frames"] = settle_frames
    persistent_queue = capture_config["persistent_queue"]
    persistent_queue["settle_frames"] = settle_frames
    persistent_queue["animation_freeze_settle_frames"] = settle_frames
    core._write_json(run_dir / "fit_config.json", config)

    material_params = extract_params(load_lmat(selected["baseline_material_path"]))
    base_params = {
        key: copy.deepcopy(value)
        for key, value in material_params.items()
        if isinstance(value, (int, float, bool, list))
    }
    base_params_path = run_dir / "base_params.json"
    core._write_json(base_params_path, base_params)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NODE_PATH"] = str((repo_root / "artifacts/real_laya_run/node_modules").resolve())
    queue_proc = None
    renderer_proc = None
    bootstrap_driver: RenderDriver | None = None
    driver: RenderDriver | None = None
    try:
        queue_proc = core._start_queue(repo_root=repo_root, run_dir=run_dir, cap_port=cap_port, env=env)
        renderer_proc = core._start_renderer(
            repo_root=repo_root,
            run_dir=run_dir,
            cap_port=cap_port,
            width=int(args.width),
            height=int(args.height),
            engine_root=engine_root,
            selected=selected,
            env=env,
            headed=bool(args.headed),
        )
        bootstrap_capture = copy.deepcopy(config["laya_capture"])
        bootstrap_capture["browser_score"]["emit_artifacts"] = "always"
        bootstrap_driver = RenderDriver(
            run_dir / "bootstrap_eval",
            command=[],
            dry_run=False,
            capture_config=bootstrap_capture,
        )
        bootstrap_started = time.perf_counter()
        bootstrap_driver.render_candidate(0, base_params)
        bootstrap_wall_ms = (time.perf_counter() - bootstrap_started) * 1000.0
        bootstrap_driver.render_candidate(1, base_params)
        target_dir = run_dir / "bootstrap_eval" / "iterations" / "iter_0001"
        bootstrap_driver.close()
        bootstrap_driver = None

        capture_config = copy.deepcopy(config["laya_capture"])
        capture_config["browser_score"]["reference_images"] = [
            {"view_id": view["view_id"], "path": str(target_dir / view["file_name"])}
            for view in core.FISH_VIEWS
        ]
        capture_config["browser_score"]["emit_artifacts"] = "always"
        driver = RenderDriver(run_dir / "browser_eval", command=[], dry_run=False, capture_config=capture_config)

        warmup_started = time.perf_counter()
        warmup_result = driver.render_candidate(0, base_params)
        warmup_wall_ms = (time.perf_counter() - warmup_started) * 1000.0
        warmup_persistent = warmup_result.get("persistent_result") if isinstance(warmup_result, dict) else None
        warmup_browser = warmup_persistent.get("browser_score") if isinstance(warmup_persistent, dict) else None
        records = []
        for index, (name, strength) in enumerate(PERTURBATION_LEVELS, start=1):
            candidate_params = _perturb_params(base_params, strength)
            started = time.perf_counter()
            result = driver.render_candidate(index, candidate_params)
            wall_ms = (time.perf_counter() - started) * 1000.0
            persistent = result.get("persistent_result") if isinstance(result, dict) else None
            browser_score = persistent.get("browser_score") if isinstance(persistent, dict) else None
            candidate_dir = run_dir / "browser_eval" / "iterations" / f"iter_{index:04d}"
            python_score = score_cross_engine_views(
                reference_dir=target_dir,
                candidate_dir=candidate_dir,
                views=core.FISH_VIEWS,
            )
            records.append(
                {
                    "name": name,
                    "strength": strength,
                    "browser_score": browser_score.get("fit_score") if isinstance(browser_score, dict) else None,
                    "browser_summary": browser_score.get("summary") if isinstance(browser_score, dict) else None,
                    "python_score": python_score.get("score") if isinstance(python_score, dict) else None,
                    "python_components": python_score.get("components") if isinstance(python_score, dict) else None,
                    "wall_ms_with_png_artifacts": wall_ms,
                    "candidate_dir": str(candidate_dir),
                }
            )
    finally:
        if driver is not None:
            driver.close()
        if bootstrap_driver is not None:
            bootstrap_driver.close()
        core._terminate_process(renderer_proc, pid_file=run_dir / "renderer.pid")
        core._terminate_process(queue_proc, pid_file=run_dir / "queue.pid")

    report = _build_report(
        run_dir=run_dir,
        assets=assets,
        selected=selected,
        target_dir=target_dir,
        records=records,
        warmup={
            "bootstrap_target_warmup": {
                "excluded_from_acceptance": True,
                "wall_ms_with_png_artifacts": bootstrap_wall_ms,
                "candidate_dir": str(run_dir / "bootstrap_eval" / "iterations" / "iter_0000"),
            },
            "evaluation_warmup": {
            "excluded_from_acceptance": True,
            "browser_score": warmup_browser.get("fit_score") if isinstance(warmup_browser, dict) else None,
            "wall_ms_with_png_artifacts": warmup_wall_ms,
            "candidate_dir": str(run_dir / "browser_eval" / "iterations" / "iter_0000"),
            },
        },
        settle_frames=settle_frames,
    )
    report_path = run_dir / "scorer_sanity_report.json"
    core._write_json(report_path, report)
    contact_sheet = _write_contact_sheet(run_dir, report)
    summary = {
        "ok": bool(report["passed"]),
        "run_dir": str(run_dir),
        "report": str(report_path),
        "contact_sheet": str(contact_sheet) if contact_sheet is not None else None,
        "same_browser_min": report["same_browser_min"],
        "same_python_min": report["same_python_min"],
        "browser_monotonic": report["browser_monotonic"],
        "python_monotonic": report["python_monotonic"],
    }
    core._write_json(run_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--engine-root", default="")
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=700)
    parser.add_argument("--settle-frames", type=int, default=0)
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args(argv)


def _perturb_params(base: dict[str, Any], strength: float) -> dict[str, Any]:
    params = copy.deepcopy(base)
    params["u_GammaPower"] = float(base["u_GammaPower"]) + 1.2 * strength
    params["u_Saturation"] = max(0.2, float(base["u_Saturation"]) - 0.7 * strength)
    params["u_TexPower"] = float(base["u_TexPower"]) + strength
    params["u_EmissionPow"] = float(base["u_EmissionPow"]) + 0.8 * strength
    params["u_SpecularIntensity"] = float(base["u_SpecularIntensity"]) + 0.8 * strength
    return params


def _build_report(
    *,
    run_dir: Path,
    assets: Any,
    selected: dict[str, Any],
    target_dir: Path,
    records: list[dict[str, Any]],
    warmup: dict[str, Any],
    settle_frames: int,
) -> dict[str, Any]:
    browser_monotonic = all(records[index]["browser_score"] > records[index + 1]["browser_score"] for index in range(1, len(records) - 1))
    python_monotonic = all(records[index]["python_score"] > records[index + 1]["python_score"] for index in range(1, len(records) - 1))
    same_browser_min = min(records[0]["browser_score"], records[1]["browser_score"])
    same_python_min = min(records[0]["python_score"], records[1]["python_score"])
    return {
        "version": "cross_engine_scorer_sanity_v3",
        "passed": browser_monotonic and python_monotonic and same_browser_min >= 0.995 and same_python_min >= 0.995,
        "run_dir": str(run_dir),
        "asset_set": selected["asset_set_name"],
        "scene_path": str(selected["scene_path"]),
        "baseline_material_path": str(selected["baseline_material_path"]),
        "unity_reference_dir": str(assets.unity_reference_dir),
        "reference_contract_id": assets.reference_contract_id,
        "target_render_dir": str(target_dir),
        "browser_metric": "cross_engine_foreground_components_v2",
        "python_metric": "cross_engine_material_score_v2",
        "animation_mode": core.CANONICAL_ANIMATION_MODE,
        "capture_settle_frames": settle_frames,
        "animation_freeze_settle_frames": settle_frames,
        "same_browser_min": same_browser_min,
        "same_python_min": same_python_min,
        "browser_monotonic": browser_monotonic,
        "python_monotonic": python_monotonic,
        "warmup": warmup,
        "records": records,
        "notes": [
            "The target and candidates are independent real Laya renders; this is not a directory self-comparison.",
            "One bootstrap render is excluded before target capture, and one evaluation warmup is excluded before the two same-params stability captures.",
            "PNG artifact timing is diagnostic and is not the <=0.50s optimization-loop benchmark.",
            "Nonzero settle frames are limited to this source-runtime visual-contract check and do not change the maintained optimization fast path.",
        ],
    }


def _write_contact_sheet(run_dir: Path, report: dict[str, Any]) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    columns = [("target", Path(report["target_render_dir"]))]
    columns.extend((item["name"], Path(item["candidate_dir"])) for item in report["records"])
    cell_width, cell_height, label_height = 220, 170, 26
    sheet = Image.new("RGB", (len(columns) * cell_width, len(core.FISH_VIEWS) * (cell_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for column_index, (label, directory) in enumerate(columns):
        for row_index, view in enumerate(core.FISH_VIEWS):
            x = column_index * cell_width
            y = row_index * (cell_height + label_height)
            draw.text((x + 5, y + 5), f"{label} {view['view_id']}", fill="black")
            with Image.open(directory / view["file_name"]) as source:
                image = core._image_on_background(source, (255, 255, 255))
                image.thumbnail((cell_width, cell_height))
                sheet.paste(image, (x + (cell_width - image.width) // 2, y + label_height + (cell_height - image.height) // 2))
    path = run_dir / "scorer_sanity_contact_sheet.png"
    sheet.save(path)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
