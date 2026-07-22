from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_fit.experiments import single_view_runtime
from material_fit.experiments.single_view_runtime import (
    build_single_view_driver,
    render_score,
)


class _Driver:
    def render_candidate(self, _evaluation_index: int, _params: dict[str, object]) -> dict[str, object]:
        return {
            "status": "ok",
            "browser_score": {
                "fit_score": 0.8,
                "views": [
                    {
                        "dists_distance": 0.25,
                        "residual_features": [0.1, -0.2],
                    }
                ],
                "structured_residual_features": {"features": []},
            },
        }


def test_render_score_reads_single_view_dists_fields_from_aggregate_payload() -> None:
    score = render_score(_Driver(), evaluation_index=0, params={})
    assert score["distance"] == 0.25
    assert score["fit_score"] == 0.8
    assert score["residual_features"] == [0.1, -0.2]


def test_render_score_uses_browser_diff_score_as_distance() -> None:
    class BrowserMetricDriver:
        def render_candidate(
            self,
            _evaluation_index: int,
            _params: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "ok",
                "browser_score": {
                    "fit_score": 0.72,
                    "diff_score": 0.28,
                    "structured_residual_features": {"features": [0.1, -0.1]},
                },
            }

    score = render_score(BrowserMetricDriver(), evaluation_index=0, params={})

    assert score["distance"] == 0.28
    assert score["fit_score"] == 0.72
    assert score["residual_features"] == [0.1, -0.1]


def test_build_single_view_driver_applies_browser_score_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "capture_defaults": {
                    "target_name": "model",
                    "views": [{"view_id": "v000_yaw0_pitch0"}],
                }
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"not-read-by-driver-construction")

    class CapturedDriver:
        def __init__(self, **kwargs: object) -> None:
            self.capture_config = kwargs["capture_config"]

    monkeypatch.setattr(single_view_runtime, "RenderDriver", CapturedDriver)
    driver = build_single_view_driver(
        profile_path=profile,
        output_root=tmp_path / "output",
        material_patch={},
        node_modules=tmp_path,
        reference_path=reference,
        return_images=False,
        perceptual_metric="cross_engine_foreground_components_v4",
        browser_score_overrides={
            "residual_grid_size": 32,
            "residual_sketch_size": 256,
        },
    )

    browser_score = driver.capture_config["browser_score"]
    assert browser_score["residual_grid_size"] == 32
    assert browser_score["residual_sketch_size"] == 256


def test_build_single_view_driver_enables_dists_residual_features_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "capture_defaults": {
                    "target_name": "model",
                    "views": [{"view_id": "v000_yaw0_pitch0"}],
                }
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"not-read-by-driver-construction")

    class CapturedDriver:
        def __init__(self, **kwargs: object) -> None:
            self.capture_config = kwargs["capture_config"]

    monkeypatch.setattr(single_view_runtime, "RenderDriver", CapturedDriver)
    driver = build_single_view_driver(
        profile_path=profile,
        output_root=tmp_path / "output",
        material_patch={},
        node_modules=tmp_path,
        reference_path=reference,
        return_images=False,
    )

    assert driver.capture_config["browser_score"]["perceptual_emit_residual_features"] is True
    assert driver.capture_config["browser_score"]["perceptual_residual_sketch_size"] == 4096
    assert driver.capture_config["browser_score"]["perceptual_residual_sketch_tables"] == 4
