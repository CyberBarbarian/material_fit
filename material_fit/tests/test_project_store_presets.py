from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit_ui.backend import job_manager  # noqa: E402
from tools.material_fit_ui.backend.case_loader import LoaderConfig  # noqa: E402
from tools.material_fit_ui.backend.project_store import create_project, derive_fit_config, patch_project  # noqa: E402


def test_persistent_queue_lifecycle_scripts_are_packaged() -> None:
    checkout_root = Path(__file__).resolve().parents[2]
    scripts_dir = checkout_root / "scripts"

    for name in (
        "ensure_persistent_laya_queue.ps1",
        "stop_persistent_laya_queue.ps1",
        "ensure_persistent_laya_queue.sh",
        "stop_persistent_laya_queue.sh",
    ):
        assert (scripts_dir / name).is_file(), f"missing UI persistent-queue lifecycle script: {name}"


def test_default_project_derives_fast_persistent_browser_score_path(tmp_path):
    config = LoaderConfig(
        project_root=tmp_path,
        image_root=tmp_path,
        output_dir=tmp_path / "output",
    )
    reference_dir = tmp_path / "unity_refs"
    reference_dir.mkdir()
    reference_path = reference_dir / "unity_ref_v000_yaw0_pitch0.png"
    reference_path.write_bytes(b"reference")
    project = create_project(project_id="fast_default", name="Fast Default", config=config)
    patch_project(
        project["id"],
        {
            "inputs": {
                "laya_shader_path": str(tmp_path / "shader.fs"),
                "laya_material_lmat_path": str(tmp_path / "material.lmat"),
                "unity_reference_dir_path": str(reference_dir),
            },
        },
        config=config,
    )

    fit_config = derive_fit_config(project["id"], config=config)

    assert fit_config["laya_editor_capture"]["enabled"] is False
    assert fit_config["laya_capture"]["persistent_queue"]["enabled"] is True
    assert fit_config["laya_capture"]["persistent_queue"]["cap_port"] == 8787
    assert fit_config["laya_capture"]["persistent_queue"]["width"] == 900
    assert fit_config["laya_capture"]["persistent_queue"]["height"] == 700
    assert fit_config["laya_capture"]["persistent_queue"]["alpha_source"] == "render_alpha"
    assert fit_config["laya_capture"]["persistent_queue"]["animation_mode"] == "disabled"
    assert "fixed_animation_state" not in fit_config["laya_capture"]["persistent_queue"]
    assert Path(fit_config["laya_capture"]["persistent_queue"]["state_dir"]).name == "persistent_queue"
    assert fit_config["laya_capture"]["persistent_queue"]["ensure_command"]
    assert fit_config["laya_capture"]["persistent_queue"]["stop_command"]
    assert fit_config["laya_capture"]["browser_score"]["enabled"] is True
    assert fit_config["laya_capture"]["browser_score"]["metric"] == "browser_fast_rgba_mae_v1"
    assert fit_config["optimizer"] == "pattern16"
    assert fit_config["laya_capture"]["browser_score"]["reference_images"] == [
        {
            "view_id": "v000_yaw0_pitch0",
            "path": str(reference_path.resolve()),
        }
    ]
    assert fit_config["browser_score_context_render"]["enabled"] is True
    assert fit_config["capture_screen_after_apply"] is False


def test_editor_capture_override_disables_fast_laya_capture(tmp_path):
    config = LoaderConfig(
        project_root=tmp_path,
        image_root=tmp_path,
        output_dir=tmp_path / "output",
    )
    project = create_project(project_id="editor_override", name="Editor Override", config=config)
    patch_project(
        project["id"],
        {
            "inputs": {
                "laya_shader_path": str(tmp_path / "shader.fs"),
                "laya_material_lmat_path": str(tmp_path / "material.lmat"),
            },
            "algorithm_config": {
                "use_laya_editor_capture": True,
            },
        },
        config=config,
    )

    fit_config = derive_fit_config(project["id"], config=config)

    assert fit_config["laya_editor_capture"]["enabled"] is True
    assert fit_config["laya_capture"] == {}
    assert fit_config["browser_score_context_render"]["enabled"] is False


def test_cma_mature_default_preset_derives_recommended_optimizer_stack(tmp_path):
    config = LoaderConfig(
        project_root=tmp_path,
        image_root=tmp_path,
        output_dir=tmp_path / "output",
    )
    project = create_project(project_id="preset_case", name="Preset Case", config=config)
    patch_project(
        project["id"],
        {
            "inputs": {
                "laya_shader_path": str(tmp_path / "shader.fs"),
                "laya_material_lmat_path": str(tmp_path / "material.lmat"),
            },
            "algorithm_config": {
                "optimizer_preset": "cma_mature_default",
                "max_iterations": 10000,
                "target_score": 0.98,
            },
        },
        config=config,
    )

    fit_config = derive_fit_config(project["id"], config=config)

    assert fit_config["optimizer_preset"] == "cma_mature_default"
    assert fit_config["optimizer"] == "cma_warm"
    assert fit_config["auto_adjust_target_score"] == 0.98
    assert fit_config["cma_es"]["warm_start_source"] == "elite_archive_first"
    assert fit_config["cma_es"]["restart_center_mode"] == "alternate"
    assert fit_config["cma_es"]["restart_population_schedule"] == "bipop"
    assert fit_config["cma_es"]["restart_population_multiplier"] == 2.0
    assert fit_config["cma_es"]["stagnation_stop_after_restarts"] is False
    assert fit_config["cma_es"]["initial_design_samples"] == 16
    assert fit_config["cma_es"]["initial_design_method"] == "latin_hypercube"
    assert fit_config["cma_es"]["initial_design_include_current"] is True
    assert fit_config["analysis_performance"]["evaluation_batch_size"] == 8
    assert fit_config["analysis_performance"]["full_rerank_top_k"] == 1
    assert fit_config["analysis_performance"]["best_full_validation"] is True
    assert fit_config["analysis_performance"]["target_full_validation"] is True
    assert fit_config["analysis_performance"]["stability_validation_repeats"] == 2
    assert fit_config["analysis_performance"]["stability_validation_restart_renderer"] is True


def test_start_job_records_raw_and_effective_algorithm_config_for_presets(monkeypatch, tmp_path):
    config = LoaderConfig(
        project_root=tmp_path,
        image_root=tmp_path,
        output_dir=tmp_path / "output",
    )
    project = create_project(project_id="preset_job", name="Preset Job", config=config)
    patch_project(
        project["id"],
        {
            "inputs": {
                "laya_shader_path": str(tmp_path / "shader.fs"),
                "laya_material_lmat_path": str(tmp_path / "material.lmat"),
            },
            "algorithm_config": {
                "optimizer_preset": "cma_mature_default",
            },
        },
        config=config,
    )

    class DummyProcess:
        pid = 12345

    class DummyThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(job_manager, "_new_job_id", lambda: "job_preset")
    monkeypatch.setattr(job_manager.subprocess, "Popen", lambda *args, **kwargs: DummyProcess())
    monkeypatch.setattr(job_manager.threading, "Thread", DummyThread)

    result = job_manager.start_job(project["id"], config=config)
    job_config_path = Path(result["run_dir"]) / "job_config.json"
    job_config = job_manager.json.loads(job_config_path.read_text(encoding="utf-8"))

    assert job_config["algorithm_config"]["optimizer_preset"] == "cma_mature_default"
    assert job_config["algorithm_config"]["optimizer"] == "pattern16"
    assert job_config["effective_algorithm_config"]["optimizer"] == "cma_warm"
    assert job_config["effective_algorithm_config"]["analysis_performance"]["best_full_validation"] is True
    assert job_config["effective_algorithm_config"]["analysis_performance"]["stability_validation_repeats"] == 2
    assert job_config["fit_config"]["optimizer_preset"] == "cma_mature_default"
    assert job_config["fit_config"]["optimizer"] == "cma_warm"
    assert job_config["fit_config"]["cma_es"]["warm_start_source"] == "elite_archive_first"
    assert len(job_config["fit_config_sha256"]) == 64
