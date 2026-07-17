from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_fit.assets.fish_scene import FishSceneAssets
from material_fit.experiments.fish_core_experiment import (
    FISH_VIEWS,
    _build_config,
    _parse_args,
    _resolve_best_render_dir,
    _resolve_node_executable,
    _select_assets_for_mode,
    _write_eight_view_alignment_report,
)


def test_node_executable_can_be_configured_explicitly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = tmp_path / "node"
    node.write_bytes(b"")
    monkeypatch.setenv("MATERIAL_FIT_NODE", str(node))

    assert _resolve_node_executable() == str(node.resolve())


def test_missing_configured_node_fails_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing-node"
    monkeypatch.setenv("MATERIAL_FIT_NODE", str(missing))

    with pytest.raises(FileNotFoundError, match="configured Node executable"):
        _resolve_node_executable()


def test_linux_runtime_defaults_are_documented_in_runner_source() -> None:
    source = Path(__file__).resolve().parents[1] / "experiments" / "fish_core_experiment.py"
    text = source.read_text(encoding="utf-8")

    assert "--use-gl=egl" in text
    assert 'renderer_env.setdefault("CUDA_VISIBLE_DEVICES", "0")' in text


def test_linux_entrypoints_use_the_repository_playwright_runtime() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_stage1.sh").read_text(encoding="utf-8")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))

    assert '--node-modules "$REPO_ROOT/node_modules"' in runner
    assert package["dependencies"]["playwright"] == "1.61.1"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_rect_png(path: Path, *, xy: tuple[int, int, int, int]) -> None:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(xy, fill="black")
    image.save(path)


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


def test_write_eight_view_alignment_report_records_per_view_metrics(tmp_path: Path) -> None:
    unity_dir = tmp_path / "unity_refs"
    initial_dir = tmp_path / "output/iterations/iter_-001"
    best_dir = tmp_path / "output/best_render"
    for view in FISH_VIEWS:
        _write_rect_png(unity_dir / view["file_name"], xy=(16, 20, 42, 44))
        _write_rect_png(initial_dir / view["file_name"], xy=(18, 20, 44, 44))
        _write_rect_png(best_dir / view["file_name"], xy=(16, 20, 42, 44))

    summary = {
        "unity_reference_dir": str(unity_dir),
        "initial_render_dir": str(initial_dir),
        "best_render_dir": str(best_dir),
    }
    report_path = _write_eight_view_alignment_report(run_dir=tmp_path, summary=summary)

    assert report_path == tmp_path / "eight_view_alignment_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["initial_render"]["view_count"] == 8
    assert report["initial_render"]["mean_foreground_iou"] < 1.0
    assert report["initial_render"]["max_abs_centroid_dx"] == 2.0
    assert report["best_render"]["mean_foreground_iou"] == 1.0
    assert report["best_render"]["views"][0]["view_id"] == "v000_yaw0_pitch0"


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
        human_adjusted_material_path=tmp_path / "material_fit/assets/material_starts/1504/human_adjusted/1504_body.lmat",
        source_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        shader_path=tmp_path / "laya/assets/resources/shader/Custom_low.shader",
        scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        source_scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        baseline_material_name="fish_jxs_test.lmat",
        human_adjusted_material_name="1504_body.lmat",
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
    assert "human_target" not in config
    assert "human_adjusted_material_path" not in config["asset_set"]
    assert "human_adjusted_material_name" not in config["asset_set"]
    assert config["auto_adjust_target_score"] == 0.98
    assert config["browser_score_objective"] == {"mode": "mean"}
    assert queue["width"] == 900
    assert queue["height"] == 700
    assert queue["alpha_source"] == "silhouette_mask"
    assert queue["animation_mode"] == "disabled"
    assert "fixed_animation_state" not in queue
    assert "fixed_animation_time" not in queue
    assert queue["settle_frames"] == 0
    assert queue["animation_freeze_settle_frames"] == 0
    assert browser_score["metric"] == "cross_engine_foreground_components_v2"
    assert browser_score["rgb_weight"] == 0.85
    assert browser_score["alpha_weight"] == 0.15
    assert config["laya_capture"]["preserve_artifact_alpha"] is True
    assert len(browser_score["reference_images"]) == 8


def test_fish_core_selects_active_finetune_start_but_source_zero_start(tmp_path: Path) -> None:
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
        baseline_material_path=tmp_path / "material_fit/assets/material_starts/1504/active/1504_new_test.lmat",
        human_adjusted_material_path=tmp_path / "material_fit/assets/material_starts/1504/human_adjusted/1504_body.lmat",
        source_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        shader_path=tmp_path / "laya/assets/resources/shader/Custom_low.shader",
        scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        source_scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        baseline_material_name="1504_new_test.lmat",
        human_adjusted_material_name="1504_body.lmat",
        source_scene_material_name="fish_jxs_test.lmat",
    )

    finetune = _select_assets_for_mode(assets, "material")
    zero = _select_assets_for_mode(assets, "zero_searchable")
    source_finetune = _select_assets_for_mode(assets, "material", "source")

    assert finetune["baseline_material_path"] == assets.baseline_material_path
    assert finetune["baseline_material_name"] == "1504_new_test.lmat"
    assert zero["baseline_material_path"] == assets.source_material_path
    assert zero["baseline_material_name"] == "fish_jxs_test.lmat"
    assert source_finetune["baseline_material_path"] == assets.source_material_path


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
        human_adjusted_material_path=tmp_path / "material_fit/assets/material_starts/1504/human_adjusted/1504_body.lmat",
        source_material_path=tmp_path / "laya/assets/resources/model/1504/mat/fish_jxs_test.lmat",
        shader_path=tmp_path / "laya/assets/resources/shader/Custom_low.shader",
        scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        source_scene_material_uuid="4adc3c2d-41bc-4cad-87df-77ecfb84a558",
        baseline_material_name="fish_jxs_test.lmat",
        human_adjusted_material_name="1504_body.lmat",
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
