from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from material_fit.experiments.material_cross_engine_stage2_multiview_ablation import (
    SINGLE_VIEW_ID,
    _optimizer_score_progress,
    _select_views,
    _validate_frozen_camera,
    _write_variant_profile,
)


def _views() -> list[dict[str, object]]:
    return [
        {
            "view_id": f"v{index:03d}_yaw{yaw}_pitch0",
            "yaw": float(yaw),
            "pitch": 0.0,
            "file_name": f"laya_v{index:03d}_yaw{yaw}_pitch0.png",
        }
        for index, yaw in enumerate(range(0, 360, 45))
    ]


def test_select_views_keeps_requested_single_view() -> None:
    views = _views()
    selected = _select_views(views, (SINGLE_VIEW_ID,))

    assert [view["view_id"] for view in selected] == [SINGLE_VIEW_ID]
    assert selected[0] is not views[0]


def test_select_views_supports_any_count_and_requested_order() -> None:
    views = _views()
    requested = (str(views[5]["view_id"]), str(views[1]["view_id"]), str(views[7]["view_id"]))

    selected = _select_views(views, requested)

    assert tuple(str(view["view_id"]) for view in selected) == requested


def test_select_views_rejects_empty_or_duplicate_inputs() -> None:
    views = _views()
    with pytest.raises(ValueError, match="at least one"):
        _select_views(views, ())
    duplicate = str(views[0]["view_id"])
    with pytest.raises(ValueError, match="duplicates"):
        _select_views(views, (duplicate, duplicate))


def test_variant_profile_changes_only_resolution_and_views(tmp_path: Path) -> None:
    source_payload = {
        "width": 900,
        "height": 700,
        "runtime": {"camera": {"orthographic_vertical_size": 6.625}},
        "capture_defaults": {"views": _views()},
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(source_payload), encoding="utf-8")

    output = _write_variant_profile(
        source,
        tmp_path / "variant.json",
        _views()[:1],
        width=720,
        height=560,
    )
    variant = json.loads(output.read_text(encoding="utf-8"))

    assert variant["width"] == 720
    assert variant["height"] == 560
    assert len(variant["capture_defaults"]["views"]) == 1
    assert variant["runtime"] == source_payload["runtime"]


def test_validate_frozen_camera_rejects_runtime_drift() -> None:
    profile = {
        "runtime": {
            "camera": {
                "orthographic_vertical_size": 6.625,
                "center_offset": [0.0, 0.34, 0.0],
            }
        },
        "capture_defaults": {"target_base_yaw": 180.0},
        "camera_calibration": {
            "alignment_passed": True,
            "orthographic_vertical_size": 6.625,
            "center_offset": [0.0, 0.34, 0.0],
            "target_base_yaw": 180.0,
        },
    }
    _validate_frozen_camera(profile)
    drifted = copy.deepcopy(profile)
    drifted["runtime"]["camera"]["center_offset"] = [0.0, 0.0, 0.0]

    with pytest.raises(ValueError, match="center offset"):
        _validate_frozen_camera(drifted)

    yaw_drifted = copy.deepcopy(profile)
    yaw_drifted["capture_defaults"]["target_base_yaw"] = 0.0
    with pytest.raises(ValueError, match="target base yaw"):
        _validate_frozen_camera(yaw_drifted)


def test_optimizer_score_progress_uses_initial_and_best_scores(tmp_path: Path) -> None:
    path = tmp_path / "iteration_series.json"
    path.write_text(
        json.dumps(
            [
                {"fit_score_before": 0.60},
                {"fit_score_before": 0.72},
                {"fit_score_before": 0.68},
            ]
        ),
        encoding="utf-8",
    )

    assert _optimizer_score_progress(path) == {
        "scored_material_count": 3,
        "initial_fit_score": 0.60,
        "best_fit_score": 0.72,
        "online_score_gain": pytest.approx(0.12),
    }
