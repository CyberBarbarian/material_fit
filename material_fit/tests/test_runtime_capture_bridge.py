from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.laya_capture.runtime_bridge import RuntimeCaptureBridge  # noqa: E402


def _poll_and_post_one_capture(base_url: str, expected_nonce: str, *, view_id: str, file_name: str) -> None:
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
        assert command["post_url"] == f"{base_url}/material-fit/capture-result"
        payload = {
            "nonce": command["nonce"],
            "view_id": view_id,
            "file_name": file_name,
            "png_base64": base64.b64encode(b"fake-png-bytes").decode("ascii"),
        }
        request = urllib.request.Request(
            f"{base_url}/material-fit/capture-result",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1.0) as response:
            assert response.status == 200
        return
    raise AssertionError("Laya simulator did not observe a capture command")


def _poll_and_post_one_raw_capture(base_url: str, expected_nonce: str, *, view_id: str, file_name: str) -> None:
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
        assert command["server_base_url"] == base_url
        assert command["image_format"] == "raw_rgba"
        raw_pixels = bytes(
            [
                255,
                0,
                0,
                255,
                0,
                255,
                0,
                128,
            ]
        )
        params = urllib.parse.urlencode(
            {
                "nonce": command["nonce"],
                "view_id": view_id,
                "file_name": file_name,
                "width": "2",
                "height": "1",
                "yaw": "0",
                "pitch": "0",
            }
        )
        request = urllib.request.Request(
            f"{base_url}/material-fit/capture-raw-rgba?{params}",
            data=raw_pixels,
            headers={"Content-Type": "application/octet-stream"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1.0) as response:
            assert response.status == 200
        return
    raise AssertionError("Laya simulator did not observe a raw capture command")


def _poll_reference_and_post_browser_score(base_url: str, expected_nonce: str, *, expected_reference: bytes) -> None:
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
        score_cfg = command["browser_score"]
        reference_url = score_cfg["reference_images"][0]["url"]
        with urllib.request.urlopen(reference_url, timeout=1.0) as response:
            assert response.read() == expected_reference

        payload = {
            "nonce": command["nonce"],
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
        request = urllib.request.Request(
            f"{base_url}/material-fit/capture-score",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1.0) as response:
            assert response.status == 200
        return
    raise AssertionError("Laya simulator did not observe a browser-score command")


def test_runtime_capture_bridge_reuses_one_server_for_multiple_capture_jobs(tmp_path: Path):
    views = [{"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0, "file_name": "laya_v000_yaw0_pitch0.png"}]

    with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
        first_thread = threading.Thread(
            target=_poll_and_post_one_capture,
            args=(bridge.base_url, "iter-0001"),
            kwargs={"view_id": "v000_yaw0_pitch0", "file_name": "laya_v000_yaw0_pitch0.png"},
        )
        first_thread.start()
        first = bridge.capture(
            {"nonce": "iter-0001", "views": views, "material_patch": {"target_name": "model", "values": {"u_Metallic": 0.1}}},
            output_dir=tmp_path / "first",
            timeout_s=3.0,
        )
        first_thread.join(timeout=1.0)

        second_thread = threading.Thread(
            target=_poll_and_post_one_capture,
            args=(bridge.base_url, "iter-0002"),
            kwargs={"view_id": "v000_yaw0_pitch0", "file_name": "laya_v000_yaw0_pitch0.png"},
        )
        second_thread.start()
        second = bridge.capture(
            {"nonce": "iter-0002", "views": views, "material_patch": {"target_name": "model", "values": {"u_Metallic": 0.2}}},
            output_dir=tmp_path / "second",
            timeout_s=3.0,
        )
        second_thread.join(timeout=1.0)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["screenshots"] == [str(tmp_path / "first" / "laya_v000_yaw0_pitch0.png")]
    assert second["screenshots"] == [str(tmp_path / "second" / "laya_v000_yaw0_pitch0.png")]
    assert first["candidate_overrides"]["v000_yaw0_pitch0"] == first["screenshots"][0]
    assert second["candidate_overrides"]["v000_yaw0_pitch0"] == second["screenshots"][0]
    assert Path(first["screenshots"][0]).read_bytes() == b"fake-png-bytes"
    assert Path(second["screenshots"][0]).read_bytes() == b"fake-png-bytes"


def test_runtime_capture_bridge_accepts_raw_rgba_payload(tmp_path: Path):
    views = [{"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0, "file_name": "laya_v000_yaw0_pitch0.png"}]

    with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
        capture_thread = threading.Thread(
            target=_poll_and_post_one_raw_capture,
            args=(bridge.base_url, "iter-raw"),
            kwargs={"view_id": "v000_yaw0_pitch0", "file_name": "laya_v000_yaw0_pitch0.rgba"},
        )
        capture_thread.start()
        result = bridge.capture(
            {
                "nonce": "iter-raw",
                "views": views,
                "image_format": "raw_rgba",
                "material_patch": {"target_name": "model", "values": {"u_Metallic": 0.1}},
            },
            output_dir=tmp_path / "raw",
            timeout_s=3.0,
        )
        capture_thread.join(timeout=1.0)

    raw_path = tmp_path / "raw" / "laya_v000_yaw0_pitch0.rgba"
    assert result["status"] == "ok"
    assert result["screenshots"] == [str(raw_path)]
    assert result["candidate_overrides"]["v000_yaw0_pitch0"] == str(raw_path)
    assert raw_path.read_bytes() == bytes([255, 0, 0, 255, 0, 255, 0, 128])
    sidecar = json.loads(raw_path.with_suffix(".rgba.json").read_text(encoding="utf-8"))
    assert sidecar["format"] == "raw_rgba"
    assert sidecar["width"] == 2
    assert sidecar["height"] == 1


def test_runtime_capture_bridge_accepts_browser_score_without_images(tmp_path: Path):
    views = [{"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0, "file_name": "laya_v000_yaw0_pitch0.png"}]
    reference_path = tmp_path / "unity_v000_yaw0_pitch0.png"
    reference_bytes = b"reference-png"
    reference_path.write_bytes(reference_bytes)

    with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
        capture_thread = threading.Thread(
            target=_poll_reference_and_post_browser_score,
            args=(bridge.base_url, "iter-score"),
            kwargs={"expected_reference": reference_bytes},
        )
        capture_thread.start()
        result = bridge.capture(
            {
                "nonce": "iter-score",
                "views": views,
                "browser_score": {
                    "enabled": True,
                    "reference_images": [
                        {
                            "view_id": "v000_yaw0_pitch0",
                            "path": str(reference_path),
                        }
                    ],
                },
            },
            output_dir=tmp_path / "score",
            timeout_s=3.0,
        )
        capture_thread.join(timeout=1.0)

    assert result["status"] == "ok"
    assert result["screenshots"] == []
    assert result["candidate_overrides"] == {}
    assert result["browser_score"]["fit_score"] == 0.82
    assert (tmp_path / "score" / "browser_score.json").exists()
