from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from material_fit.assets.material_phase05 import MaterialAssetSpec
from material_fit.experiments.material_phase05_recovery import (
    OPTIMIZER_ID,
    _build_fit_config,
    _discrete_state_report,
    _optimizer_boundary_report,
    _profile_resolution,
    _timing_report,
    _write_optimizer_profile,
)
from material_fit.experiments.material_phase05_multistart import (
    _build_report,
    _matrix,
    _payload_sha256,
)
from material_fit.experiments import material_phase05_multistart as multistart_module
from material_fit.experiments import material_phase05_recovery as recovery_module
from material_fit.optimizer.material_recovery import (
    material_parameter_distance,
    perturb_material_params,
)
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
    structured_material_coordinates,
)


def _params() -> dict:
    return {
        "u_GammaPower": 1.0,
        "u_Saturation": 1.0,
        "u_Contrast": 1.0,
        "u_HueShift": 0.5,
        "u_TexPower": 1.0,
        "u_AoPower": 0.5,
        "u_EmissionPow": 1.0,
        "u_IndirectStrength": 1.0,
        "u_NormalScale": 0.6,
        "u_ShadowSmoothness": 0.5,
        "u_ShadowThreshold1": 0.5,
        "u_SpecularIntensity": 1.0,
        "u_SpecularPower": 20.0,
        "u_SpecularThreshold": 0.5,
        "u_SpecularSmoothness": 0.5,
        "u_RimIntensity": 1.0,
        "u_RimWidth": 1.0,
        "u_Color": [1.0, 1.0, 1.0, 1.0],
        "u_ReflectColor": [0.5, 0.5, 0.5, 1.0],
        "u_ShadowColor1": [0.5, 0.5, 0.5, 1.0],
        "u_SpecularColor": [0.5, 0.5, 0.5, 1.0],
        "u_RimColor": [0.5, 0.5, 0.5, 1.0],
        "u_SpeOffet": [0.0, 0.0, 0.0, 0.0],
        "u_RimOffet": [0.0, 0.0, 0.0, 0.0],
        **{name: 15.0 for name in STRUCTURED_SCENE_PARAM_NAMES},
    }


def test_cleanup_report_replaces_stale_status_for_same_pid_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = tmp_path / "runtime_renderer_pid.json"
    record.write_text(json.dumps({"pid": 12345}), encoding="utf-8")
    (tmp_path / "process_cleanup_report.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "pid": 12345,
                        "record": str(record),
                        "before": True,
                        "after": True,
                        "owned_renderer": True,
                        "action": "terminated_owned_tree",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recovery_module, "_pid_exists", lambda _pid: False)
    monkeypatch.setattr(recovery_module, "_process_command_line", lambda _pid: "")

    report = recovery_module._cleanup_recorded_runtime(tmp_path)

    assert report["remaining_owned_pid_count"] == 0
    assert len(report["checks"]) == 1
    assert report["checks"][0]["action"] == "already_stopped"


def test_cleanup_stops_owned_fit_before_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_dir = tmp_path / "cases" / "joint"
    case_dir.mkdir(parents=True)
    (case_dir / "fit.pid").write_text("101\n", encoding="ascii")
    runtime_dir = case_dir / "runtime_renderer"
    runtime_dir.mkdir()
    (runtime_dir / "runtime_renderer_pid.json").write_text(
        json.dumps({"pid": 202}),
        encoding="utf-8",
    )
    alive = {101: True, 202: True}
    terminated: list[int] = []

    monkeypatch.setattr(
        recovery_module,
        "_pid_exists",
        lambda pid: alive.get(pid, False),
    )
    monkeypatch.setattr(
        recovery_module,
        "_process_command_line",
        lambda pid: (
            f"python -m material_fit.fit_material --config {tmp_path}/config.json"
            if pid == 101
            else "node material_fit/laya_capture/run_runtime_renderer.js"
        ),
    )

    def terminate(pid: int) -> None:
        terminated.append(pid)
        alive[pid] = False

    monkeypatch.setattr(recovery_module, "_terminate_recorded_process", terminate)

    report = recovery_module._cleanup_recorded_runtime(tmp_path)

    assert terminated == [101, 202]
    assert report["remaining_owned_pid_count"] == 0


def test_shared_perturbation_changes_40_material_coordinates_only() -> None:
    target = _params()
    start, report = perturb_material_params(target, preset="medium", seed=17)

    assert len(structured_material_coordinates(target, material_only=True)) == 40
    assert report["changed_coordinate_count"] == 40
    assert report["scene_alignment_perturbed"] is False
    assert all(start[name] == target[name] for name in STRUCTURED_SCENE_PARAM_NAMES)

    start_distance, _ = material_parameter_distance(target, start)
    exact_distance, _ = material_parameter_distance(target, target)
    assert start_distance["mean_normalized_abs_error"] > 0
    assert exact_distance["mean_normalized_abs_error"] == 0


def test_optimizer_profile_uses_fast_surrogate_without_changing_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "artifact_profile.json"
    output = tmp_path / "optimizer_profile.json"
    source.write_text(
        json.dumps({"width": 900, "height": 700, "capture_defaults": {"views": []}}),
        encoding="utf-8",
    )

    _write_optimizer_profile(source, output, width=720, height=560)

    assert _profile_resolution(source) == [900, 700]
    assert _profile_resolution(output) == [720, 560]
    optimizer = json.loads(output.read_text(encoding="utf-8"))
    assert optimizer["online_score_surrogate"] == {
        "enabled": True,
        "role": "proposal_ranking_only",
        "final_artifacts_use_source_profile": True,
    }


def test_unbounded_emission_range_preserves_high_valid_values_in_tiny_probe() -> None:
    target = _params()
    target["u_EmissionPow"] = 25.791

    coordinates = {
        coordinate.coordinate_id: coordinate
        for coordinate in structured_material_coordinates(target, material_only=True)
    }
    emission = coordinates["u_EmissionPow"]
    perturbed, report = perturb_material_params(target, preset="tiny", seed=20260713)
    emission_change = next(
        row for row in report["changed_coordinates"] if row["coordinate"] == "u_EmissionPow"
    )

    assert emission.low == 0.0
    assert emission.high == 64.0
    assert emission.initial_step == 4.0
    assert abs(perturbed["u_EmissionPow"] - target["u_EmissionPow"]) == pytest.approx(0.0004)
    assert abs(emission_change["delta"]) == pytest.approx(0.0004)
    assert emission_change["bounds"] == [0.0, 64.0]


def test_fit_config_is_asset_independent_and_png_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scene = project / "scene.ls"
    shader = project / "shader.shader"
    material = project / "material.lmat"
    profile = tmp_path / "profile.json"
    start = tmp_path / "start.json"
    target_dir = tmp_path / "target"
    for path in (scene, shader, material, profile, start):
        path.write_text("{}", encoding="utf-8")
    target_dir.mkdir()
    views = [
        {
            "view_id": f"v{i:03d}",
            "file_name": f"view_{i}.png",
            "yaw": i * 45,
            "pitch": 0,
        }
        for i in range(8)
    ]
    asset = MaterialAssetSpec(
        asset_id="arbitrary_asset",
        project_root=project,
        scene_path=scene,
        shader_path=shader,
        target_material_path=material,
        profile={},
    )
    config = _build_fit_config(
        asset=asset,
        profile_path=profile,
        run_dir=tmp_path / "run",
        start_material_path=start,
        target_dir=target_dir,
        target_defines={"managed": ["NORMALMAP"], "enabled": ["NORMALMAP"]},
        target_score=0.995,
        node_modules=None,
        views=views,
    )

    assert config["optimizer_contract"] == "structured_material_v1"
    assert config["structured_material_contract"]["asset_independent"] is True
    assert config["structured_material_contract"]["runtime_optimizer_id"] == "material_jacobian_trust_region"
    assert (
        config["structured_material_contract"]["optimization_score_metric"]
        == "cross_engine_foreground_components_v3"
    )
    assert (
        config["laya_capture"]["browser_score"]["metric"]
        == "cross_engine_foreground_components_v3"
    )
    assert config["search_param_names"] == list(STRUCTURED_MATERIAL_PARAM_NAMES)
    assert not set(config["search_param_names"]) & set(STRUCTURED_SCENE_PARAM_NAMES)
    assert config["optimizer"] == "material_jacobian_trust_region"
    assert config["material_jacobian_trust_region"]["difference_mode"] == "forward"
    assert config["material_jacobian_trust_region"]["solve_mode"] == "full_least_squares"
    assert config["material_jacobian_trust_region"]["shader_default_anchor_enabled"] is True
    assert config["material_jacobian_trust_region"]["probe_step"] == 0.025
    assert config["material_jacobian_trust_region"]["ridge"] == 0.10
    assert config["material_jacobian_trust_region"]["trust_radius"] == 0.12
    assert config["material_jacobian_trust_region"]["line_search_scales"] == [1.0, 0.5, 0.25, 0.125]
    assert config["material_jacobian_trust_region"]["target_params_visible"] is False
    assert config["laya_capture"]["return_images"] is False
    assert config["laya_capture"]["material_patch"]["defines"]["enabled"] == ["NORMALMAP"]
    assert config["laya_material_path"] == str(start)
    assert "initial_params_override_path" not in config
    assert all("target_params" not in item["path"] for item in config["laya_capture"]["browser_score"]["reference_images"])

    boundary = _optimizer_boundary_report(config, private_dir=tmp_path / "run/private_audit")
    assert boundary["passed"] is True
    config["leak"] = str(tmp_path / "run/private_audit/target_params.json")
    assert _optimizer_boundary_report(config, private_dir=tmp_path / "run/private_audit")["passed"] is False


def test_timing_gate_uses_stable_iteration_total(tmp_path: Path) -> None:
    path = tmp_path / "iteration_series.json"
    path.write_text(
        json.dumps(
            [
                {"iteration": 0, "timing": {"iteration_total_ms": 4000}},
                {"iteration": 1, "timing": {"iteration_total_ms": 420}},
                {"iteration": 2, "timing": {"iteration_total_ms": 480}},
            ]
        ),
        encoding="utf-8",
    )

    report = _timing_report(path, 500.0)
    assert report["count"] == 2
    assert report["mean_ms"] == pytest.approx(450.0)
    assert report["gate_passed"] is True


def test_discrete_state_audit_rejects_locked_or_define_drift() -> None:
    target = _params()
    start, _ = perturb_material_params(target, preset="medium", seed=17)
    patch = {"defines": {"managed": ["NORMALMAP"], "enabled": ["NORMALMAP"]}}

    report = _discrete_state_report(
        target_params=target,
        start_params=start,
        target_patch=patch,
        start_patch=patch,
    )
    assert report["passed"] is True

    start[STRUCTURED_SCENE_PARAM_NAMES[0]] += 1.0
    drift = _discrete_state_report(
        target_params=target,
        start_params=start,
        target_patch=patch,
        start_patch={"defines": {"managed": ["NORMALMAP"], "enabled": []}},
    )
    assert drift["passed"] is False
    assert drift["defines_match"] is False
    assert drift["scene_coordinate_differences"] == [STRUCTURED_SCENE_PARAM_NAMES[0]]


def test_multistart_matrix_crosses_assets_presets_and_seeds() -> None:
    rows = _matrix(["fish", "turtle"], ["mild", "strong"], [11, 12])
    assert len(rows) == 8
    assert len({row["run_name"] for row in rows}) == 8
    assert {row["asset"] for row in rows} == {"fish", "turtle"}


def test_multistart_report_enforces_explicit_runtime_audits(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/fish_mild_seed11"
    (run_dir / "inputs").mkdir(parents=True)
    start_params = {"u_GammaPower": 0.5}
    (run_dir / "inputs/start_params.json").write_text(
        json.dumps(start_params, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    phase_report = {
        "accepted": True,
        "start_score": 0.8,
        "best_score": 0.99,
        "score_gain": 0.19,
        "parameter_recovery": {
            "improved": True,
            "start": {"mean_normalized_abs_error": 0.1},
            "best": {"mean_normalized_abs_error": 0.01},
        },
        "timing": {"mean_ms": 450.0, "p95_ms": 480.0, "gate_passed": True},
        "scorer_sanity": {"passed": True},
        "process_cleanup": {"remaining_owned_pid_count": 0},
        "asset_contract_passed": True,
        "discrete_state_audit_passed": True,
        "optimizer_input_boundary_passed": True,
        "view_counts": {"target": 8, "start": 8, "best": 8},
        "optimizer": "structured_material_v1",
        "optimizer_runtime_id": OPTIMIZER_ID,
    }
    (run_dir / "phase05_report.json").write_text(
        json.dumps(phase_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    matrix = [{"asset": "fish", "preset": "mild", "seed": 11, "run_name": run_dir.name}]
    plan = {"runs": [{**matrix[0], "planned_start_params_sha256": _payload_sha256(start_params)}]}
    launch_rows = [{**matrix[0], "returncode": 0, "gpu": 0, "run_dir": str(run_dir)}]

    report = _build_report(
        batch_dir=tmp_path,
        matrix=matrix,
        plan=plan,
        launch_rows=launch_rows,
        wall_elapsed_s=1.0,
    )
    assert report["accepted"] is True

    phase_report["view_counts"]["best"] = 7
    (run_dir / "phase05_report.json").write_text(
        json.dumps(phase_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rejected = _build_report(
        batch_dir=tmp_path,
        matrix=matrix,
        plan=plan,
        launch_rows=launch_rows,
        wall_elapsed_s=1.0,
    )
    assert rejected["accepted"] is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-signal contract")
def test_multistart_sigterm_cancels_queued_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launched: list[object] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.pid = 900_000 + len(launched)
            self.returncode: int | None = None

        def wait(self) -> int:
            while self.returncode is None:
                time.sleep(0.01)
            return self.returncode

        def poll(self) -> int | None:
            return self.returncode

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        process = FakeProcess()
        launched.append(process)
        return process

    def fake_terminate(process: FakeProcess) -> None:
        process.returncode = 143

    monkeypatch.setattr(multistart_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(multistart_module, "_terminate", fake_terminate)
    matrix = [
        {"asset": "fish", "preset": "mild", "seed": seed, "run_name": f"run_{seed}"}
        for seed in range(5)
    ]
    for directory in (tmp_path / "runs", tmp_path / "logs", tmp_path / "pids"):
        directory.mkdir()
    timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt, match="received signal"):
            multistart_module._run_matrix(
                repo_root=tmp_path,
                runs_dir=tmp_path / "runs",
                logs_dir=tmp_path / "logs",
                pids_dir=tmp_path / "pids",
                matrix=matrix,
                gpus=[0],
                max_parallel=1,
                iterations=1,
                target_score=0.9,
                success_score=0.8,
                speed_gate_ms=500.0,
                max_runtime_sec=10.0,
                node_modules="",
                engine_libs="",
            )
    finally:
        timer.cancel()

    assert len(launched) == 1


def test_multistart_resume_skips_complete_accepted_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    logs_dir = tmp_path / "logs"
    pids_dir = tmp_path / "pids"
    run_dir = runs_dir / "fish_mild_seed7"
    (run_dir / "inputs").mkdir(parents=True)
    logs_dir.mkdir()
    pids_dir.mkdir()
    (run_dir / "inputs" / "start_params.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "phase05_report.json").write_text(
        json.dumps(
            {
                "contract": "shared_material_phase05_recovery_v1",
                "accepted": True,
                "process_cleanup": {"remaining_owned_pid_count": 0},
                "view_counts": {"target": 8, "start": 8, "best": 8},
            }
        ),
        encoding="utf-8",
    )

    def unexpected_popen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a complete accepted run must not relaunch")

    monkeypatch.setattr(multistart_module.subprocess, "Popen", unexpected_popen)
    rows = multistart_module._run_matrix(
        repo_root=tmp_path,
        runs_dir=runs_dir,
        logs_dir=logs_dir,
        pids_dir=pids_dir,
        matrix=[
            {
                "asset": "fish",
                "preset": "mild",
                "seed": 7,
                "run_name": "fish_mild_seed7",
            }
        ],
        gpus=[1],
        max_parallel=1,
        iterations=1,
        target_score=0.9,
        success_score=0.8,
        speed_gate_ms=500.0,
        max_runtime_sec=10.0,
        node_modules="",
        engine_libs="",
        resume_existing=True,
    )

    assert rows == [
        {
            "asset": "fish",
            "preset": "mild",
            "seed": 7,
            "run_name": "fish_mild_seed7",
            "gpu": None,
            "returncode": 0,
            "elapsed_s": 0.0,
            "run_dir": str(run_dir),
            "log_path": str(logs_dir / "fish_mild_seed7.log"),
            "resumed": True,
        }
    ]


def test_multistart_transient_renderer_failure_classification(tmp_path: Path) -> None:
    transient = tmp_path / "transient.log"
    deterministic = tmp_path / "deterministic.log"
    transient.write_text(
        "RuntimeError: runtime renderer exited with 1: statefirst\n",
        encoding="utf-8",
    )
    deterministic.write_text("assertion failed: score below gate\n", encoding="utf-8")

    assert multistart_module._is_transient_renderer_failure(transient) is True
    assert multistart_module._is_transient_renderer_failure(deterministic) is False
