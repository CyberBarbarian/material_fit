from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.laya import render_driver as render_driver_module  # noqa: E402


RenderDriver = render_driver_module.RenderDriver


def _poll_runtime_bridge_and_post(base_url: str, *, expected_nonce: str, expected_value: float) -> None:
    deadline = time.monotonic() + 3.0
    last_nonce = ""
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"{base_url}/material-fit/capture-command?last_nonce={last_nonce}",
            timeout=1.0,
        ) as response:
            command = json.loads(response.read().decode("utf-8"))
        if command.get("enabled") is False or command.get("nonce") == last_nonce:
            time.sleep(0.02)
            continue

        assert command["nonce"] == expected_nonce
        assert command["material_patch"]["target_name"] == "model"
        assert command["material_patch"]["values"]["u_Metallic"] == expected_value
        assert command["paramsPath"].endswith("params.json")
        payload = {
            "nonce": command["nonce"],
            "view_id": "v000_yaw0_pitch0",
            "file_name": "laya_v000_yaw0_pitch0.png",
            "png_base64": base64.b64encode(b"runtime-capture").decode("ascii"),
        }
        request = urllib.request.Request(
            command["post_url"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1.0) as response:
            assert response.status == 200
        return
    raise AssertionError("runtime bridge command was not observed")


def _serve_one_persistent_queue_request(state_dir: Path) -> None:
    queue_dir = state_dir / "queue"
    result_dir = state_dir / "results"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        requests = sorted(queue_dir.glob("*.request.json"))
        if not requests:
            time.sleep(0.02)
            continue
        request_path = requests[0]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        command = request["command"]
        assert "persistent_queue" not in command
        assert command["target_name"] == "model"
        assert command["material_patch"]["values"]["u_Metallic"] == 0.33
        assert command["alpha_source"] == "render_alpha"
        assert command["restore_animators_after_capture"] is False
        assert command["freeze_scene_scripts"] is True
        assert command["restore_scene_scripts_after_capture"] is False
        assert command["preserve_target_base_rotation"] is False
        assert command["target_base_roll"] == 0.0
        assert command["animation_freeze_settle_frames"] == 3
        output_dir = Path(command["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        if command.get("image_format") == "raw_rgba":
            capture_path = output_dir / "laya_v000_yaw0_pitch0.rgba"
            capture_path.write_bytes(b"\x00\x00\x00\x00")
            (output_dir / "laya_v000_yaw0_pitch0.rgba.json").write_text(
                json.dumps({"format": "raw_rgba", "width": 1, "height": 1}),
                encoding="utf-8",
            )
        else:
            capture_path = output_dir / "laya_v000_yaw0_pitch0.png"
            capture_path.write_bytes(b"persistent-queue-capture")
        result_path = result_dir / f"{request['request_id']}.result.json"
        result_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "total_ms": 123,
                    "browser_capture_ms": 100,
                    "png_count": 1,
                }
            ),
            encoding="utf-8",
        )
        request_path.unlink()
        return
    raise AssertionError("persistent queue request was not observed")


def _serve_one_persistent_queue_request_with_animator_restore(state_dir: Path) -> None:
    queue_dir = state_dir / "queue"
    result_dir = state_dir / "results"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        requests = sorted(queue_dir.glob("*.request.json"))
        if not requests:
            time.sleep(0.02)
            continue
        request_path = requests[0]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        command = request["command"]
        assert command["restore_animators_after_capture"] is True
        output_dir = Path(command["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "laya_v000_yaw0_pitch0.png").write_bytes(b"persistent-queue-capture")
        result_path = result_dir / f"{request['request_id']}.result.json"
        result_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "total_ms": 123,
                    "browser_capture_ms": 100,
                    "png_count": 1,
                    "capture_count": 1,
                    "missing": [],
                }
            ),
            encoding="utf-8",
        )
        return
    raise AssertionError("persistent queue request was not observed")


def _serve_one_persistent_browser_score_request(state_dir: Path) -> None:
    queue_dir = state_dir / "queue"
    result_dir = state_dir / "results"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        requests = sorted(queue_dir.glob("*.request.json"))
        if not requests:
            time.sleep(0.02)
            continue
        request_path = requests[0]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        command = request["command"]
        assert command["browser_score"]["enabled"] is True
        assert command["browser_score"]["reference_images"][0]["view_id"] == "v000_yaw0_pitch0"
        assert command["browser_score"]["reference_images"][0]["url"].startswith(
            "http://127.0.0.1:9999/material-fit/reference-image?path="
        )
        assert command["material_patch"]["values"]["u_Metallic"] == 0.42
        Path(command["output_dir"]).mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{request['request_id']}.result.json"
        result_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "total_ms": 77,
                    "browser_capture_ms": 70,
                    "capture_count": 1,
                    "png_count": 0,
                    "browser_score": {
                        "enabled": True,
                        "metric": "browser_fast_rgba_mae_v1",
                        "fit_score": 0.82,
                        "diff_score": 0.18,
                        "views": [
                            {
                                "view_id": "v000_yaw0_pitch0",
                                "fit_score": 0.82,
                                "diff_score": 0.18,
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        request_path.unlink()
        return
    raise AssertionError("persistent queue request was not observed")


def test_render_driver_worker_pool_routes_iterations_to_isolated_workers(tmp_path):
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=True,
        capture_config={
            "workers": [
                {
                    "name": "gpu0",
                    "output_dir": str(tmp_path / "worker_gpu0"),
                    "parallel_safe": True,
                },
                {
                    "name": "gpu1",
                    "output_dir": str(tmp_path / "worker_gpu1"),
                    "parallel_safe": True,
                },
            ],
        },
    )

    first = driver.render_candidate(0, {"u_Metallic": 0.1})
    second = driver.render_candidate(1, {"u_Metallic": 0.2})
    third = driver.capture_candidate(2, {"u_Metallic": 0.3})

    assert driver.parallel_safe is True
    assert driver.worker_count == 2
    assert first["worker"] == {"index": 0, "name": "gpu0"}
    assert second["worker"] == {"index": 1, "name": "gpu1"}
    assert third["worker"] == {"index": 0, "name": "gpu0"}
    assert Path(first["params_path"]).is_relative_to(tmp_path / "worker_gpu0")
    assert Path(second["params_path"]).is_relative_to(tmp_path / "worker_gpu1")
    assert Path(third["params_path"]).is_relative_to(tmp_path / "worker_gpu0")


def test_render_driver_worker_pool_requires_every_worker_marked_parallel_safe(tmp_path):
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=True,
        capture_config={
            "workers": [
                {
                    "name": "gpu0",
                    "output_dir": str(tmp_path / "worker_gpu0"),
                    "parallel_safe": True,
                },
                {
                    "name": "shared",
                    "output_dir": str(tmp_path / "worker_shared"),
                },
            ],
        },
    )

    assert driver.worker_count == 2
    assert driver.parallel_safe is False


def test_render_driver_can_capture_via_embedded_runtime_bridge(tmp_path):
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "runtime_bridge": {"enabled": True, "host": "127.0.0.1", "port": 0, "timeout_s": 3.0},
            "target_name": "model",
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "file_name": "laya_v000_yaw0_pitch0.png",
                }
            ],
        },
    )
    try:
        worker = threading.Thread(
            target=_poll_runtime_bridge_and_post,
            args=(driver.runtime_capture_base_url,),
            kwargs={"expected_nonce": "capture-0007", "expected_value": 0.42},
        )
        worker.start()
        result = driver.capture_candidate(7, {"u_Metallic": 0.42})
        worker.join(timeout=1.0)
    finally:
        driver.close()

    screenshot = tmp_path / "root" / "iterations" / "iter_0007" / "laya_multiview" / "laya_v000_yaw0_pitch0.png"
    assert result["status"] == "ok"
    assert result["screenshots"] == [str(screenshot)]
    assert result["candidate_overrides"]["v000_yaw0_pitch0"] == str(screenshot)
    assert screenshot.read_bytes() == b"runtime-capture"


def test_render_driver_can_render_via_persistent_queue(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "ready.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(state_dir),
                "timeout_s": 3.0,
                "poll_s": 0.01,
                "cap_port": 9999,
                "alpha_source": "render_alpha",
            },
            "image_format": "raw_rgba",
            "target_name": "model",
            "width": 320,
            "height": 240,
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "file_name": "laya_v000_yaw0_pitch0.rgba",
                }
            ],
        },
    )

    worker = threading.Thread(target=_serve_one_persistent_queue_request, args=(state_dir,))
    worker.start()
    result = driver.render_candidate(5, {"u_Metallic": 0.33})
    worker.join(timeout=1.0)

    screenshot = tmp_path / "root" / "iterations" / "iter_0005" / "laya_v000_yaw0_pitch0.rgba"
    assert result["status"] == "ok"
    assert result["screenshots"] == [str(screenshot)]
    assert result["candidate_overrides"]["v000_yaw0_pitch0"] == str(screenshot)
    assert result["persistent_result"]["browser_capture_ms"] == 100
    assert screenshot.read_bytes() == b"\x00\x00\x00\x00"


def test_render_driver_reset_persistent_queue_runs_stop_and_requires_ensure_again(tmp_path):
    state_dir = tmp_path / "state"
    ensure_count = tmp_path / "ensure_count.txt"
    stop_count = tmp_path / "stop_count.txt"
    ensure_script = tmp_path / "ensure.py"
    stop_script = tmp_path / "stop.py"
    ensure_script.write_text(
        (
            "import json, pathlib, sys\n"
            "state = pathlib.Path(sys.argv[1])\n"
            "count = pathlib.Path(sys.argv[2])\n"
            "state.mkdir(parents=True, exist_ok=True)\n"
            "(state / 'ready.json').write_text(json.dumps({'ok': True}), encoding='utf-8')\n"
            "value = int(count.read_text() or '0') if count.exists() else 0\n"
            "count.write_text(str(value + 1), encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )
    stop_script.write_text(
        (
            "import pathlib, sys\n"
            "count = pathlib.Path(sys.argv[1])\n"
            "value = int(count.read_text() or '0') if count.exists() else 0\n"
            "count.write_text(str(value + 1), encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(state_dir),
                "timeout_s": 3.0,
                "poll_s": 0.01,
                "cap_port": 9999,
                "alpha_source": "render_alpha",
                "ensure_command": [sys.executable, str(ensure_script), str(state_dir), str(ensure_count)],
                "stop_command": [sys.executable, str(stop_script), str(stop_count)],
            },
            "target_name": "model",
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "file_name": "laya_v000_yaw0_pitch0.png",
                }
            ],
        },
    )

    first_worker = threading.Thread(target=_serve_one_persistent_queue_request, args=(state_dir,))
    first_worker.start()
    first = driver.render_candidate(5, {"u_Metallic": 0.33})
    first_worker.join(timeout=1.0)

    assert first["status"] == "ok"
    assert ensure_count.read_text(encoding="utf-8") == "1"
    assert driver.reset_persistent_queue() is True
    assert stop_count.read_text(encoding="utf-8") == "1"

    second_worker = threading.Thread(target=_serve_one_persistent_queue_request, args=(state_dir,))
    second_worker.start()
    second = driver.render_candidate(6, {"u_Metallic": 0.33})
    second_worker.join(timeout=1.0)

    assert second["status"] == "ok"
    assert ensure_count.read_text(encoding="utf-8") == "2"


def test_render_driver_close_resets_persistent_queue(tmp_path):
    class FakePersistentQueue:
        def __init__(self) -> None:
            self.reset_calls = 0

        def reset(self) -> bool:
            self.reset_calls += 1
            return True

    driver = RenderDriver(output_dir=tmp_path / "root", dry_run=True)
    queue = FakePersistentQueue()
    driver._persistent_queue = queue  # type: ignore[attr-defined]

    driver.close()

    assert queue.reset_calls == 1
    assert driver._persistent_queue is None  # type: ignore[attr-defined]


def test_persistent_queue_reset_uses_sibling_stop_script_when_missing_stop_command(
    tmp_path,
    monkeypatch,
):
    state_dir = tmp_path / "state"
    stop_script = tmp_path / "bin" / "stop_persistent_multiview_daemon.sh"
    ensure_script = tmp_path / "bin" / "ensure_persistent_multiview_daemon.sh"
    stop_script.parent.mkdir(parents=True)
    ensure_script.write_text("", encoding="utf-8")
    stop_script.write_text("", encoding="utf-8")
    calls: list[dict] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(render_driver_module.subprocess, "run", fake_run)
    client = render_driver_module._PersistentQueueClient(
        {
            "state_dir": str(state_dir),
            "ensure_command": [str(ensure_script)],
            "environment": {"EXISTING": "1"},
        }
    )

    assert client.reset() is True
    assert calls[0]["command"] == [str(stop_script)]
    env = calls[0]["kwargs"]["env"]
    assert env["MATERIAL_FIT_PERSISTENT_STATE_DIR"] == str(state_dir)
    assert env["MATERIAL_FIT_PERSISTENT_LOG_DIR"] == str(state_dir / "logs")
    assert env["EXISTING"] == "1"


def test_persistent_queue_startup_settle_waits_once_and_after_reset(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "ready.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    sleep_calls: list[float] = []
    monkeypatch.setattr(render_driver_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    client = render_driver_module._PersistentQueueClient(
        {
            "state_dir": str(state_dir),
            "startup_settle_s": "2.5",
        }
    )

    client._ensure_ready()
    client._ensure_ready()

    assert sleep_calls == [2.5]
    assert client.reset() is False
    client._ensure_ready()
    assert sleep_calls == [2.5, 2.5]


def test_render_driver_can_restore_animators_when_explicitly_requested(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "ready.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(state_dir),
                "timeout_s": 3.0,
                "poll_s": 0.01,
                "cap_port": 9999,
                "restore_animators_after_capture": True,
            },
            "target_name": "model",
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "file_name": "laya_v000_yaw0_pitch0.png",
                }
            ],
        },
    )

    worker = threading.Thread(target=_serve_one_persistent_queue_request_with_animator_restore, args=(state_dir,))
    worker.start()
    result = driver.render_candidate(6, {"u_Metallic": 0.33})
    worker.join(timeout=1.0)

    assert result["status"] == "ok"
    assert result["persistent_result"]["browser_capture_ms"] == 100


def test_render_driver_accepts_browser_score_without_screenshots(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "ready.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    reference_path = tmp_path / "unity_v000_yaw0_pitch0.png"
    reference_path.write_bytes(b"reference")
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(state_dir),
                "timeout_s": 3.0,
                "poll_s": 0.01,
                "cap_port": 9999,
                "alpha_source": "render_alpha",
            },
            "browser_score": {
                "enabled": True,
                "reference_images": [
                    {
                        "view_id": "v000_yaw0_pitch0",
                        "path": str(reference_path),
                    }
                ],
            },
            "target_name": "model",
            "width": 320,
            "height": 240,
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "yaw": 0.0,
                    "pitch": 0.0,
                    "file_name": "laya_v000_yaw0_pitch0.png",
                }
            ],
        },
    )

    worker = threading.Thread(target=_serve_one_persistent_browser_score_request, args=(state_dir,))
    worker.start()
    result = driver.render_candidate(6, {"u_Metallic": 0.42})
    worker.join(timeout=1.0)

    assert result["status"] == "ok"
    assert result["screenshots"] == []
    assert result["candidate_overrides"] == {}
    assert result["persistent_result"]["browser_score"]["fit_score"] == pytest.approx(0.82)


def test_render_driver_select_persistent_oracle_adopts_best_attempt(tmp_path, monkeypatch):
    reset_states: list[str] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        state_name = self.state_dir.name
        score_by_state = {
            "attempt_00": 0.80,
            "attempt_01": 0.91,
            "attempt_02": 0.86,
        }
        score = score_by_state[state_name]
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": score,
                    "score": score,
                    "diff_score": 1.0 - score,
                },
            },
        }

    def fake_reset(self):
        reset_states.append(self.state_dir.name)
        return True

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", fake_reset)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
                "http_port": 9200,
                "environment": {"STATE_DIR": str(tmp_path / "state"), "CAP_PORT": "9100", "HTTP_PORT": "9200"},
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"u_Metallic": 0.42},
        attempts=3,
        output_subdir="oracle_stabilization",
    )

    assert summary["status"] == "ok"
    assert summary["selected_attempt"] == 1
    assert summary["selected_fit_score"] == pytest.approx(0.91)
    queue_cfg = driver.capture_config["persistent_queue"]
    assert Path(queue_cfg["state_dir"]).name == "attempt_01"
    assert queue_cfg["cap_port"] == 9110
    assert queue_cfg["environment"]["CAP_PORT"] == "9110"
    assert queue_cfg["environment"]["HTTP_PORT"] == "9210"
    assert Path(queue_cfg["environment"]["STATE_DIR"]).name == "attempt_01"
    assert Path(queue_cfg["environment"]["MATERIAL_FIT_PERSISTENT_STATE_DIR"]).name == "attempt_01"
    assert Path(queue_cfg["environment"]["MATERIAL_FIT_PERSISTENT_LOG_DIR"]).name == "logs"
    assert summary["selected_http_port"] == 9210
    assert reset_states == ["attempt_00", "attempt_02"]


def test_render_driver_select_persistent_oracle_scores_probe_portfolio(tmp_path, monkeypatch):
    reset_states: list[str] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        score_by_state_and_probe = {
            ("attempt_00", "zero"): 0.95,
            ("attempt_00", "prior"): 0.70,
            ("attempt_01", "zero"): 0.80,
            ("attempt_01", "prior"): 0.92,
        }
        score = score_by_state_and_probe[(self.state_dir.name, params["probe"])]
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": score,
                    "score": score,
                    "diff_score": 1.0 - score,
                },
            },
        }

    def fake_reset(self):
        reset_states.append(self.state_dir.name)
        return True

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", fake_reset)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"probe": "fallback"},
        probe_candidates=[
            {"label": "zero", "params": {"probe": "zero"}},
            {"label": "prior", "params": {"probe": "prior"}},
        ],
        attempts=2,
        output_subdir="oracle_stabilization",
    )

    assert summary["status"] == "ok"
    assert summary["selected_attempt"] == 1
    assert summary["selected_fit_score"] == pytest.approx(0.86)
    assert summary["selected_probe_scores"] == {"zero": pytest.approx(0.80), "prior": pytest.approx(0.92)}
    assert summary["records"][0]["selection_score"] == pytest.approx(0.825)
    assert summary["records"][1]["selection_score"] == pytest.approx(0.86)
    assert reset_states == ["attempt_00"]


def test_render_driver_select_persistent_oracle_can_select_median_attempt(tmp_path, monkeypatch):
    reset_states: list[str] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        score_by_state = {
            "attempt_00": 0.90,
            "attempt_01": 0.70,
            "attempt_02": 0.80,
        }
        score = score_by_state[self.state_dir.name]
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": score,
                    "score": score,
                    "diff_score": 1.0 - score,
                },
            },
        }

    def fake_reset(self):
        reset_states.append(self.state_dir.name)
        return True

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", fake_reset)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"u_Metallic": 0.42},
        attempts=3,
        selection_policy="median",
    )

    assert summary["status"] == "ok"
    assert summary["selection_policy"] == "median"
    assert summary["selected_attempt"] == 2
    assert summary["selected_fit_score"] == pytest.approx(0.80)
    assert driver.capture_config["persistent_queue"]["cap_port"] == 9120
    assert reset_states == ["attempt_00", "attempt_01"]


def test_render_driver_select_persistent_oracle_records_failed_probe_details(tmp_path, monkeypatch):
    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        if self.state_dir.name == "attempt_00":
            return {
                "status": "failed",
                "returncode": 4,
                "params_path": str(params_path),
                "screenshots": [],
                "persistent_result": {"ok": False},
            }
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": 0.9,
                    "score": 0.9,
                    "diff_score": 0.1,
                },
            },
        }

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", lambda self: True)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
            },
            "browser_score": {"enabled": True},
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"probe": "prior"},
        attempts=2,
    )

    assert summary["status"] == "ok"
    assert summary["selected_attempt"] == 1
    failed_record = summary["records"][0]
    assert failed_record["status"] == "failed"
    assert failed_record["probe_records"][0]["label"] == "probe_00"
    assert failed_record["probe_records"][0]["fit_score"] is None


def test_render_driver_select_persistent_oracle_uses_attempt_timeout(tmp_path, monkeypatch):
    observed_timeouts: list[float] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        observed_timeouts.append(self.timeout_s)
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": 0.8 + 0.01 * len(observed_timeouts),
                    "score": 0.8 + 0.01 * len(observed_timeouts),
                    "diff_score": 0.2,
                },
            },
        }

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", lambda self: True)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
                "timeout_s": 240.0,
                "oracle_selection_timeout_s": 45.0,
            },
            "browser_score": {"enabled": True},
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"probe": "prior"},
        attempts=2,
        selection_policy="median",
    )

    assert summary["status"] == "ok"
    assert observed_timeouts == [45.0, 45.0]


def test_render_driver_fresh_oracle_validation_uses_validation_timeout(tmp_path, monkeypatch):
    observed_timeouts: list[float] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        observed_timeouts.append(self.timeout_s)
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": 0.90,
                    "score": 0.90,
                    "diff_score": 0.10,
                },
            },
        }

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", lambda self: True)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
                "http_port": 9200,
                "timeout_s": 240.0,
                "oracle_selection_timeout_s": 45.0,
                "fresh_oracle_validation_timeout_s": 12.0,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.validate_persistent_oracle_stability_many(
        iteration=-3000,
        candidates=[{"candidate_id": "candidate_a", "params": {"u_Metallic": 0.42}}],
        attempts=2,
    )

    assert summary["status"] == "ok"
    assert observed_timeouts == [12.0, 12.0]


def test_render_driver_validates_candidate_across_fresh_oracles(tmp_path, monkeypatch):
    reset_states: list[str] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        score_by_state = {
            "attempt_00": 0.90,
            "attempt_01": 0.80,
            "attempt_02": 0.85,
        }
        score = score_by_state[self.state_dir.name]
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": score,
                    "score": score,
                    "diff_score": 1.0 - score,
                },
            },
        }

    def fake_reset(self):
        reset_states.append(self.state_dir.name)
        return True

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", fake_reset)

    original_state_dir = tmp_path / "state"
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(original_state_dir),
                "cap_port": 9100,
                "http_port": 9200,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.validate_persistent_oracle_stability(
        iteration=-2000,
        params={"u_Metallic": 0.42},
        attempts=3,
        output_subdir="fresh_oracle_validation",
    )

    assert summary["status"] == "ok"
    assert summary["score_policy"] == "fresh_oracle_min"
    assert summary["attempts_completed"] == 3
    assert summary["fit_score_min"] == pytest.approx(0.80)
    assert summary["fit_score_median"] == pytest.approx(0.85)
    assert summary["fit_score_max"] == pytest.approx(0.90)
    assert summary["fit_score_spread"] == pytest.approx(0.10)
    assert summary["conservative_fit_score"] == pytest.approx(0.80)
    assert summary["conservative_diff_score"] == pytest.approx(0.20)
    assert summary["diff_score_max"] == pytest.approx(0.20)
    assert [record["cap_port"] for record in summary["records"]] == [10100, 10110, 10120]
    assert [record["http_port"] for record in summary["records"]] == [10200, 10210, 10220]
    assert Path(driver.capture_config["persistent_queue"]["state_dir"]) == original_state_dir
    assert reset_states == ["attempt_00", "attempt_01", "attempt_02"]


def test_render_driver_fresh_oracle_validation_offsets_ports_from_selected_oracle(tmp_path, monkeypatch):
    observed_ports: list[tuple[int, int]] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        queue_cfg = capture_config["persistent_queue"]
        observed_ports.append((int(queue_cfg["cap_port"]), int(queue_cfg["http_port"])))
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": 0.90,
                    "score": 0.90,
                    "diff_score": 0.10,
                },
            },
        }

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", lambda self: True)

    selected_state_dir = tmp_path / "persistent_worker_state_oracle_selection" / "attempt_02"
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(selected_state_dir),
                "cap_port": 9120,
                "http_port": 9220,
                "oracle_validation_port_offset": 1000,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.validate_persistent_oracle_stability(
        iteration=-2000,
        params={"u_Metallic": 0.42},
        attempts=2,
    )

    assert summary["status"] == "ok"
    assert observed_ports == [(10120, 10220), (10130, 10230)]
    assert [record["cap_port"] for record in summary["records"]] == [10120, 10130]
    assert [record["http_port"] for record in summary["records"]] == [10220, 10230]


def test_render_driver_batch_validates_candidates_reusing_fresh_oracle_attempts(tmp_path, monkeypatch):
    reset_states: list[str] = []
    render_calls: list[tuple[str, str, int]] = []

    def fake_render(self, *, capture_config, iteration, params_path, iteration_dir, params):
        candidate_id = str(params["candidate_id"])
        render_calls.append((self.state_dir.name, candidate_id, iteration))
        scores = {
            ("attempt_00", "a"): 0.90,
            ("attempt_01", "a"): 0.70,
            ("attempt_00", "b"): 0.80,
            ("attempt_01", "b"): 0.86,
        }
        score = scores[(self.state_dir.name, candidate_id)]
        return {
            "status": "ok",
            "returncode": 0,
            "params_path": str(params_path),
            "screenshots": [],
            "persistent_result": {
                "ok": True,
                "browser_score": {
                    "enabled": True,
                    "fit_score": score,
                    "score": score,
                    "diff_score": 1.0 - score,
                },
            },
        }

    def fake_reset(self):
        reset_states.append(self.state_dir.name)
        return True

    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "render", fake_render)
    monkeypatch.setattr(render_driver_module._PersistentQueueClient, "reset", fake_reset)

    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
                "cap_port": 9100,
                "http_port": 9200,
            },
            "browser_score": {"enabled": True},
            "target_name": "model",
        },
    )

    summary = driver.validate_persistent_oracle_stability_many(
        iteration=-3000,
        candidates=[
            {"candidate_id": "candidate_a", "params": {"candidate_id": "a"}},
            {"candidate_id": "candidate_b", "params": {"candidate_id": "b"}},
        ],
        attempts=2,
        output_subdir="fresh_oracle_batch_validation",
    )

    assert summary["status"] == "ok"
    assert summary["candidate_count"] == 2
    assert summary["attempts_completed"] == 2
    assert reset_states == ["attempt_00", "attempt_01"]
    assert render_calls == [
        ("attempt_00", "a", -3000),
        ("attempt_00", "b", -2999),
        ("attempt_01", "a", -2000),
        ("attempt_01", "b", -1999),
    ]
    candidate_a, candidate_b = summary["candidates"]
    assert candidate_a["candidate_id"] == "candidate_a"
    assert candidate_a["fit_score_min"] == pytest.approx(0.70)
    assert candidate_a["fit_score_median"] == pytest.approx(0.80)
    assert candidate_b["candidate_id"] == "candidate_b"
    assert candidate_b["fit_score_min"] == pytest.approx(0.80)
    assert candidate_b["fit_score_median"] == pytest.approx(0.83)


def test_render_driver_select_persistent_oracle_skips_without_persistent_browser_score(tmp_path):
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=False,
        capture_config={
            "persistent_queue": {
                "enabled": True,
                "state_dir": str(tmp_path / "state"),
            },
            "target_name": "model",
        },
    )

    summary = driver.select_persistent_oracle(
        iteration=-1000,
        params={"u_Metallic": 0.42},
        attempts=3,
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "browser_score_disabled"


def test_render_driver_dry_run_does_not_start_runtime_bridge(tmp_path):
    driver = RenderDriver(
        output_dir=tmp_path / "root",
        dry_run=True,
        capture_config={
            "runtime_bridge": {"enabled": True, "host": "127.0.0.1", "port": 0, "timeout_s": 0.1},
            "views": [{"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0}],
        },
    )
    try:
        result = driver.capture_candidate(3, {"u_Metallic": 0.1})
    finally:
        driver.close()

    assert result["status"] == "dry_run"
    with pytest.raises(RuntimeError, match="runtime_bridge is not enabled"):
        _ = driver.runtime_capture_base_url
