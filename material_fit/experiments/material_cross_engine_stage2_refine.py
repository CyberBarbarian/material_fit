"""Refine one fixed hard-state material against eight external Unity PNGs."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.assets.stage2_unity_references import resolve_stage2_unity_references
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.material_cross_engine_stage2_multiview_ablation import (
    _copy_unity_targets,
    _evaluation_payload,
    _validate_frozen_camera,
    _write_json,
)
from material_fit.experiments.material_cross_engine_stage2_multiview_v86 import (
    _rerank_archive,
    _run_same_parameter_sanity,
)
from material_fit.experiments.stage1_reporting import _write_optimizer_profile
from material_fit.laya import lmat_io
from material_fit.laya.shader_parser import parse_laya_shader
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_EXTENDED_MATERIAL_PARAM_NAMES,
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
)


OPTIMIZER_WIDTH = 720
OPTIMIZER_HEIGHT = 560


def _write_enabled_define_variant(
    *,
    source_path: Path,
    output_path: Path,
    shader_path: Path,
    define_name: str,
) -> Path:
    """Write a material variant only when the shipped shader declares the define."""

    shader = parse_laya_shader(shader_path)
    declared = {define.name for define in shader.defines}
    if define_name not in declared:
        raise ValueError(f"shader does not declare {define_name}: {shader_path}")
    payload = lmat_io.load_lmat(source_path)
    props = lmat_io.get_props(payload)
    if define_name == "USE_SECOND_LEVELS":
        first_color = props.get("u_ShadowColor1")
        second_color = props.get("u_ShadowColor2")
        if (
            isinstance(first_color, list)
            and isinstance(second_color, list)
            and len(first_color) >= 3
            and len(second_color) >= 3
        ):
            # Target-independent neutral initialization: activating the second
            # ramp must not change the image until its four added coordinates
            # are deliberately moved by the optimizer.
            props["u_ShadowColor2"] = [
                *first_color[:3],
                *second_color[3:],
            ]
    enabled = list(dict.fromkeys(str(value) for value in props.get("defines", ()) if str(value)))
    if define_name not in enabled:
        enabled.append(define_name)
    props["defines"] = enabled
    lmat_io.save_lmat(payload, output_path)
    return output_path.resolve()


def run_continuous_refinement(
    *,
    repo_root: Path,
    run_dir: Path,
    start_material_path: Path,
    iterations: int = 1000,
    target_score: float = 0.995,
    max_runtime_sec: float = 1800.0,
    node_modules: Path | None = None,
    final_rerank_count: int = 24,
    difference_mode: str = "central",
    accept_improving_probes: bool = True,
    optimizer_width: int = OPTIMIZER_WIDTH,
    optimizer_height: int = OPTIMIZER_HEIGHT,
    enable_second_levels: bool = False,
    optimizer: str = "jacobian",
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = run_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    asset = resolve_material_asset(root, "holiday_1613")
    _validate_frozen_camera(asset.profile)
    references = resolve_stage2_unity_references(root, "holiday_1613")
    full_profile_path = asset.write_profile(output / "inputs" / "asset_profile.json")
    phase05._force_white_background(full_profile_path)
    views = phase05._profile_views(full_profile_path, expected_count=8)
    target_dir = output / "target_render"
    _copy_unity_targets(references, views, target_dir)
    optimizer_profile_path = _write_optimizer_profile(
        full_profile_path,
        output / "inputs" / "optimizer_asset_profile.json",
        width=int(optimizer_width),
        height=int(optimizer_height),
    )
    optimizer_target_dir = output / "optimizer_target_render"
    _copy_unity_targets(
        references,
        views,
        optimizer_target_dir,
        output_size=(int(optimizer_width), int(optimizer_height)),
    )

    start_path = start_material_path.expanduser().resolve()
    if enable_second_levels:
        start_path = _write_enabled_define_variant(
            source_path=start_path,
            output_path=output / "inputs" / "start_second_levels_enabled.lmat",
            shader_path=asset.shader_path,
            define_name="USE_SECOND_LEVELS",
        )
    start_params = lmat_io.extract_params(lmat_io.load_lmat(start_path))
    start_patch = material_patch_from_lmat(start_path)
    _write_json(output / "inputs" / "start_params.json", start_params)
    _run_same_parameter_sanity(
        run_dir=output,
        profile_path=optimizer_profile_path,
        views=views,
        start_params=start_params,
        start_patch=start_patch,
        node_modules=node_modules,
    )
    config = phase05._build_fit_config(
        asset=asset,
        profile_path=optimizer_profile_path,
        run_dir=output,
        start_material_path=start_path,
        target_dir=optimizer_target_dir,
        target_defines=start_patch["defines"],
        target_render_states=start_patch["render_states"],
        target_score=target_score,
        node_modules=node_modules,
        views=views,
    )
    if optimizer == "jacobian":
        config["optimizer"] = "material_jacobian_trust_region"
        config["material_jacobian_trust_region"]["shader_default_anchor_enabled"] = False
        config["material_jacobian_trust_region"]["difference_mode"] = str(difference_mode)
        config["material_jacobian_trust_region"]["accept_improving_probes"] = bool(
            accept_improving_probes
        )
    elif optimizer == "cma_es":
        config["optimizer"] = "cma_cold"
        config["cma_es"] = {
            "mode": "cold",
            "population_size": 20,
            "sigma": 0.12,
            "seed": 1613,
            "hint_bias_mix_ratio": 0.0,
            "stagnation_patience": 400,
            "stagnation_min_delta": 0.0001,
            "stagnation_min_evaluations": 400,
            "stagnation_max_restarts": 2,
            "stagnation_stop_after_restarts": False,
            "restart_center_mode": "best",
            "restart_population_multiplier": 1.5,
            "restart_population_schedule": "ipop",
            "restart_max_population_size": 48,
            "initial_design_samples": 40,
            "initial_design_method": "latin_hypercube",
            "initial_design_include_current": True,
            "initial_design_local_step_ratio": 0.08,
        }
    else:
        raise ValueError(f"unsupported optimizer: {optimizer}")
    search_param_names = (
        STRUCTURED_EXTENDED_MATERIAL_PARAM_NAMES
        if enable_second_levels
        else STRUCTURED_MATERIAL_PARAM_NAMES
    )
    config["search_param_names"] = list(search_param_names)
    config["search_param_space"] = (
        "structured_material_stage2_scene_frozen_44_second_levels_v1"
        if enable_second_levels
        else "structured_material_stage2_scene_frozen_40_v1"
    )
    config["browser_score_objective"] = {"mode": "mean"}
    config["stage2_optimizer_contract"] = {
        "phase": "cross_engine_stage2_scene_frozen_refinement",
        "target_source": "tracked_unity_png_only",
        "target_material_visible": False,
        "target_params_visible": False,
        "hard_state_fixed_from_start_material": True,
        "camera_searchable": False,
        "scene_coordinates_searchable": False,
        "scene_coordinates": list(STRUCTURED_SCENE_PARAM_NAMES),
        "material_coordinate_count": 44 if enable_second_levels else 40,
        "material_param_names": list(search_param_names),
        "optional_shader_define_enabled": (
            "USE_SECOND_LEVELS" if enable_second_levels else None
        ),
        "difference_mode": str(difference_mode),
        "accept_improving_probes": bool(accept_improving_probes),
        "optimizer": str(optimizer),
    }
    config_path = output / "fit_config.json"
    _write_json(config_path, config)
    started = time.perf_counter()
    returncode = phase05._run_fit_owned(
        repo_root=root,
        run_dir=output,
        config_path=config_path,
        iterations=int(iterations),
        target_score=float(target_score),
        max_runtime_sec=float(max_runtime_sec),
    )
    elapsed_s = time.perf_counter() - started
    if returncode != 0:
        raise RuntimeError(f"continuous refinement exited with {returncode}")
    rerank = _rerank_archive(
        run_dir=output,
        profile_path=full_profile_path,
        target_dir=target_dir,
        views=views,
        start_patch=start_patch,
        node_modules=node_modules,
        limit=max(1, int(final_rerank_count)),
        baseline_params=start_params,
    )
    best_params = rerank["best_params"]
    _write_json(output / "best_params_full_resolution_reranked.json", best_params)
    lmat_io.write_candidate_lmat(
        start_path,
        output / "best_material.lmat",
        best_params,
        allow_missing_keys=True,
    )
    final_driver = phase05._build_artifact_capture_driver(
        profile_path=full_profile_path,
        output_root=output / "final_capture" / "runtime",
        defines=start_patch["defines"],
        render_states=start_patch["render_states"],
        references=target_dir,
        node_modules=node_modules,
        score_metric=phase05.VALIDATION_SCORE_METRIC,
    )
    try:
        start_result = phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=output / "start_render",
            params=start_params,
            views=views,
            iteration=0,
        )
        best_result = phase05._capture_artifact_set(
            driver=final_driver,
            artifact_dir=output / "best_render",
            params=best_params,
            views=views,
            iteration=1,
        )
    finally:
        final_driver.close()
    start_eval = _evaluation_payload(
        result=start_result,
        target_dir=target_dir,
        candidate_dir=output / "start_render",
        views=views,
    )
    best_eval = _evaluation_payload(
        result=best_result,
        target_dir=target_dir,
        candidate_dir=output / "best_render",
        views=views,
    )
    start_score = float(start_eval["python_cross_engine_v3"]["score"])
    best_score = float(best_eval["python_cross_engine_v3"]["score"])
    cleanup = phase05._cleanup_recorded_runtime(output)
    contact_sheet = phase05._write_contact_sheet(
        views=views,
        columns=(
            ("Unity target", target_dir),
            ("Refine start", output / "start_render"),
            ("Refine best", output / "best_render"),
        ),
        output_path=output / "unity_start_refined_eightview.png",
    )
    report = {
        "contract": "material_fit_stage2_external_png_continuous_refine_v1",
        "accepted": best_score >= 0.98 and cleanup["remaining_owned_pid_count"] == 0,
        "run_dir": str(output),
        "start_material_path": str(start_path),
        "iterations": int(iterations),
        "elapsed_s": elapsed_s,
        "start_score": start_score,
        "best_score": best_score,
        "score_gain": best_score - start_score,
        "difference_mode": str(difference_mode),
        "accept_improving_probes": bool(accept_improving_probes),
        "optimizer_resolution": [int(optimizer_width), int(optimizer_height)],
        "second_levels_enabled": bool(enable_second_levels),
        "optimizer": str(optimizer),
        "start_evaluation": start_eval,
        "best_evaluation": best_eval,
        "rerank": {key: value for key, value in rerank.items() if key != "best_params"},
        "process_cleanup": cleanup,
        "best_material_path": str(output / "best_material.lmat"),
        "best_render_dir": str(output / "best_render"),
        "contact_sheet": str(contact_sheet),
    }
    _write_json(output / "stage2_refine_report.json", report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-material", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--max-runtime-sec", type=float, default=1800.0)
    parser.add_argument("--final-rerank-count", type=int, default=24)
    parser.add_argument("--optimizer-width", type=int, default=OPTIMIZER_WIDTH)
    parser.add_argument("--optimizer-height", type=int, default=OPTIMIZER_HEIGHT)
    parser.add_argument("--enable-second-levels", action="store_true")
    parser.add_argument("--optimizer", choices=("jacobian", "cma_es"), default="jacobian")
    parser.add_argument(
        "--difference-mode",
        choices=("forward", "central"),
        default="central",
    )
    parser.add_argument(
        "--no-accept-improving-probes",
        action="store_true",
    )
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
    run_dir = output_root / (
        args.run_name
        or f"stage2_1613_refine_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        report = run_continuous_refinement(
            repo_root=repo_root,
            run_dir=run_dir,
            start_material_path=Path(args.start_material),
            iterations=args.iterations,
            target_score=args.target_score,
            max_runtime_sec=args.max_runtime_sec,
            node_modules=(
                Path(args.node_modules).expanduser().resolve()
                if args.node_modules
                else None
            ),
            final_rerank_count=args.final_rerank_count,
            difference_mode=args.difference_mode,
            accept_improving_probes=not args.no_accept_improving_probes,
            optimizer_width=args.optimizer_width,
            optimizer_height=args.optimizer_height,
            enable_second_levels=args.enable_second_levels,
            optimizer=args.optimizer,
        )
    finally:
        if run_dir.exists():
            phase05._cleanup_recorded_runtime(run_dir)
    print(json.dumps({key: report[key] for key in ("accepted", "run_dir", "start_score", "best_score", "contact_sheet")}, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_continuous_refinement"]
