from __future__ import annotations

import json
from pathlib import Path

from material_fit.assets.fish_scene import FishSceneAssets
from material_fit.experiments.fish_core_experiment import (
    FISH_VIEWS,
    _build_config,
    _parse_args,
    _resolve_best_render_dir,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_best_render_dir_uses_initial_render_when_best_params_match_initial(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    initial_params = {"u_Color": [0.84, 1.0, 1.0, 1.0], "u_RimWidth": 0}
    candidate_params = {"u_Color": [0.85, 0.85, 0.85, 1.0], "u_RimWidth": 4.319}

    _write_json(output_dir / "initial_params.json", initial_params)
    _write_json(output_dir / "auto_adjust/best/params.json", initial_params)
    _write_json(output_dir / "iterations/iter_-001/params.json", initial_params)
    _write_json(output_dir / "iterations/iter_0000/params.json", candidate_params)

    best_dir = _resolve_best_render_dir(output_dir=output_dir, fallback_iteration=0)

    assert best_dir == output_dir / "iterations/iter_-001"


def test_best_render_dir_matches_candidate_params_when_candidate_is_best(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    initial_params = {"u_Color": [0.84, 1.0, 1.0, 1.0], "u_RimWidth": 0}
    candidate_params = {"u_Color": [0.85, 0.85, 0.85, 1.0], "u_RimWidth": 4.319}

    _write_json(output_dir / "initial_params.json", initial_params)
    _write_json(output_dir / "auto_adjust/best/params.json", candidate_params)
    _write_json(output_dir / "iterations/iter_-001/params.json", initial_params)
    _write_json(output_dir / "iterations/iter_0000/params.json", candidate_params)

    best_dir = _resolve_best_render_dir(output_dir=output_dir, fallback_iteration=0)

    assert best_dir == output_dir / "iterations/iter_0000"


def test_best_render_dir_does_not_fallback_to_mismatched_iteration(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    initial_params = {"u_Color": [0.84, 1.0, 1.0, 1.0], "u_RimWidth": 0}
    best_params = {"u_Color": [0.74, 0.9, 0.9, 1.0], "u_RimWidth": 0.8}
    next_candidate_params = {"u_Color": [0.1, 0.1, 1.0, 1.0], "u_RimWidth": 4.319}

    _write_json(output_dir / "initial_params.json", initial_params)
    _write_json(output_dir / "auto_adjust/best/params.json", best_params)
    _write_json(output_dir / "iterations/iter_-001/params.json", initial_params)
    _write_json(output_dir / "iterations/iter_0079/params.json", next_candidate_params)

    best_dir = _resolve_best_render_dir(output_dir=output_dir, fallback_iteration=79)

    assert best_dir is None


def test_best_render_dir_prefers_explicit_best_render(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    explicit = output_dir / "best_render"
    explicit.mkdir(parents=True)

    best_dir = _resolve_best_render_dir(
        output_dir=output_dir,
        fallback_iteration=79,
        explicit_best_render_dir=explicit,
    )

    assert best_dir == explicit


def test_fish_core_defaults_to_reproduced_pattern16_mainline() -> None:
    args = _parse_args(["--mode", "finetune"])

    assert args.optimizer == "pattern16"
    assert args.iterations == 120
    assert args.target_score == 0.98
    assert args.width == 900
    assert args.height == 700
    assert [view["view_id"] for view in FISH_VIEWS] == [
        "v000_yaw0_pitch0",
        "v001_yaw45_pitch0",
        "v002_yaw90_pitch0",
        "v003_yaw135_pitch0",
        "v004_yaw180_pitch0",
        "v005_yaw225_pitch0",
        "v006_yaw270_pitch0",
        "v007_yaw315_pitch0",
    ]


def test_fish_core_config_uses_historical_pattern16_capture_contract(tmp_path: Path) -> None:
    assets = FishSceneAssets(
        asset_set_name="fish_test",
        repo_root=tmp_path,
        source_archive_dir=tmp_path / "archives",
        laya_zip=tmp_path / "archives/laya.zip",
        unity_zip=tmp_path / "archives/unity.zip",
        extract_root=tmp_path / "extract",
        source_laya_project_dir=tmp_path / "laya",
        source_scene_path=tmp_path / "laya/assets/resources/game.ls",
        laya_project_dir=tmp_path / "laya",
        unity_reference_dir=tmp_path / "refs",
        scene_path=tmp_path / "laya/assets/resources/game.ls",
        baseline_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        source_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        shader_path=tmp_path / "laya/assets/resources/shader/Custom_low.shader",
        scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        source_scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        baseline_material_name="fish_jxs_test.lmat",
        source_scene_material_name="fish_jxs_test.lmat",
    )
    selected = {
        "asset_set_name": "fish_1504_default_finetune_from_original_zip_20260612",
        "laya_project_dir": assets.source_laya_project_dir,
        "scene_path": assets.source_scene_path,
        "baseline_material_path": assets.source_material_path,
        "scene_material_uuid": assets.source_scene_material_uuid,
        "baseline_material_name": assets.source_scene_material_name,
    }

    config = _build_config(
        repo_root=tmp_path,
        assets=assets,
        selected=selected,
        run_dir=tmp_path / "run",
        mode="material",
        working_material=tmp_path / "run/fish_jxs_test_finetune_working.lmat",
        cap_port=8787,
        width=900,
        height=700,
        optimizer="pattern16",
        target_score=0.98,
    )

    queue = config["laya_capture"]["persistent_queue"]
    browser_score = config["laya_capture"]["browser_score"]
    assert config["optimizer"] == "pattern16"
    assert config["auto_adjust_target_score"] == 0.98
    assert config["browser_score_objective"] == {"mode": "mean"}
    assert queue["width"] == 900
    assert queue["height"] == 700
    assert queue["alpha_source"] == "render_alpha"
    assert queue["fixed_animation_state"] == "idle1"
    assert queue["fixed_animation_time"] == 0.0
    assert browser_score["metric"] == "browser_fast_rgba_mae_v1"
    assert browser_score["rgb_weight"] == 0.85
    assert browser_score["alpha_weight"] == 0.15
    assert len(browser_score["reference_images"]) == 8


def test_fish_zero_start_uses_silhouette_mask_for_blank_start_scoring(tmp_path: Path) -> None:
    assets = FishSceneAssets(
        asset_set_name="fish_test",
        repo_root=tmp_path,
        source_archive_dir=tmp_path / "archives",
        laya_zip=tmp_path / "archives/laya.zip",
        unity_zip=tmp_path / "archives/unity.zip",
        extract_root=tmp_path / "extract",
        source_laya_project_dir=tmp_path / "laya",
        source_scene_path=tmp_path / "laya/assets/resources/game.ls",
        laya_project_dir=tmp_path / "laya",
        unity_reference_dir=tmp_path / "refs",
        scene_path=tmp_path / "laya/assets/resources/game.ls",
        baseline_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        source_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        shader_path=tmp_path / "laya/assets/resources/shader/Custom_low.shader",
        scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        source_scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        baseline_material_name="fish_jxs_test.lmat",
        source_scene_material_name="fish_jxs_test.lmat",
    )
    selected = {
        "asset_set_name": "fish_1504_zero_searchable_from_original_zip_20260612",
        "laya_project_dir": assets.source_laya_project_dir,
        "scene_path": assets.source_scene_path,
        "baseline_material_path": assets.source_material_path,
        "scene_material_uuid": assets.source_scene_material_uuid,
        "baseline_material_name": assets.source_scene_material_name,
    }

    config = _build_config(
        repo_root=tmp_path,
        assets=assets,
        selected=selected,
        run_dir=tmp_path / "run",
        mode="zero_searchable",
        working_material=tmp_path / "run/fish_jxs_test_zero_searchable_working.lmat",
        cap_port=8787,
        width=900,
        height=700,
        optimizer="pattern16",
        target_score=0.98,
    )

    queue = config["laya_capture"]["persistent_queue"]
    assert queue["alpha_source"] == "silhouette_mask"
    assert config["browser_score_objective"] == {
        "mode": "reference_foreground_mae",
        "foreground_threshold": 3.0,
    }
