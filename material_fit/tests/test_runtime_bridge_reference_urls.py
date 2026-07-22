import json
from http.client import HTTPConnection
from urllib.parse import urlparse

import pytest

from material_fit.laya_capture.runtime_bridge import (
    RuntimeCaptureBridge,
    _perceptual_scorer_class,
    _reference_for_view,
    _with_reference_image_urls,
)
from material_fit.vision.dists_score import (
    ForegroundDISTSAlignedRGBScorer,
    ForegroundDISTSScorer,
    ForegroundDISTSMaterialScorer,
)


def test_runtime_bridge_rewrites_target_and_confidence_mask_urls() -> None:
    command = {
        "browser_score": {
            "reference_images": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "path": "C:/run/target.png",
                    "confidence_mask_path": "C:/run/confidence.png",
                }
            ]
        }
    }

    rewritten = _with_reference_image_urls(command, "http://127.0.0.1:8123")
    reference = rewritten["browser_score"]["reference_images"][0]

    assert "target.png" in reference["url"]
    assert "confidence.png" in reference["confidence_mask_url"]


def test_runtime_bridge_selects_reference_by_view_without_asset_metadata() -> None:
    score_config = {
        "reference_images": [
            {"view_id": "v000_yaw0_pitch0", "path": "C:/run/front.png"},
            {"view_id": "v004_yaw180_pitch0", "path": "C:/run/back.png"},
        ]
    }

    selected = _reference_for_view(score_config, "v004_yaw180_pitch0")

    assert selected == {"view_id": "v004_yaw180_pitch0", "path": "C:/run/back.png"}


def test_runtime_bridge_selects_one_server_scorer_from_metric() -> None:
    assert _perceptual_scorer_class("foreground_dists_v1") is ForegroundDISTSScorer
    assert (
        _perceptual_scorer_class("foreground_dists_material_v1")
        is ForegroundDISTSMaterialScorer
    )
    assert (
        _perceptual_scorer_class("foreground_dists_aligned_rgb_v4")
        is ForegroundDISTSAlignedRGBScorer
    )
    assert (
        _perceptual_scorer_class("foreground_dists_aligned_rgb_v5")
        is ForegroundDISTSAlignedRGBScorer
    )
    assert (
        _perceptual_scorer_class("foreground_dists_aligned_rgb_v6")
        is ForegroundDISTSAlignedRGBScorer
    )
    with pytest.raises(ValueError, match="unsupported server-side perceptual metric"):
        _perceptual_scorer_class("foreground_aligned_pyramid_dists_v1")


def test_runtime_bridge_reuses_http11_connection_for_long_polling() -> None:
    with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
        bridge_url = urlparse(bridge.base_url)
        connection = HTTPConnection(str(bridge_url.hostname), int(bridge_url.port or 80), timeout=5)
        local_ports: set[int] = set()
        for _ in range(2_000):
            connection.request("GET", "/material-fit/capture-command?last_nonce=")
            response = connection.getresponse()
            assert response.status == 200
            assert response.version == 11
            assert response.read()
            assert connection.sock is not None
            local_ports.add(connection.sock.getsockname()[1])
        connection.close()

    assert len(local_ports) == 1


def test_runtime_bridge_ignores_error_log_from_superseded_nonce() -> None:
    with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
        with bridge._state.condition:
            bridge._state.active_nonce = "current"
            bridge._state.logs = []
            bridge._state.errors = []
        bridge_url = urlparse(bridge.base_url)
        connection = HTTPConnection(
            str(bridge_url.hostname), int(bridge_url.port or 80), timeout=5
        )
        payload = json.dumps(
            {"nonce": "superseded", "level": "error", "message": "late failure"}
        ).encode("utf-8")
        connection.request(
            "POST",
            "/material-fit/capture-log",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert body == {
            "ok": True,
            "ignored": True,
            "reason": "stale capture nonce",
        }
        with bridge._state.condition:
            assert bridge._state.logs == []
            assert bridge._state.errors == []
