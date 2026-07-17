from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_fit.assets.material_phase05 import canonicalize_axis_aligned_eight_view_profile
from material_fit.laya_capture.asset_profile import capture_command_from_profile, load_asset_profile


def _write_profile(tmp_path: Path, *, animation_mode: str | None = None) -> Path:
    project = tmp_path / "project"
    scene = project / "assets" / "model.lh"
    scene.parent.mkdir(parents=True)
    scene.write_text("{}", encoding="utf-8")
    capture_defaults = {
        "views": [{"view_id": "v000_yaw0_pitch0", "yaw": 0, "pitch": 0}],
    }
    if animation_mode is not None:
        capture_defaults["animation_mode"] = animation_mode
    profile = tmp_path / "asset_profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "asset_id": "example",
                "project_root": "project",
                "scene": "assets/model.lh",
                "capture_defaults": capture_defaults,
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_asset_profile_defaults_to_disabled_animation(tmp_path: Path) -> None:
    profile = load_asset_profile(_write_profile(tmp_path))
    command = capture_command_from_profile(profile)

    assert command["animation_mode"] == "disabled"
    assert command["freeze_animators"] is True
    assert command["settle_frames"] == 0
    assert command["animation_freeze_settle_frames"] == 0
    assert profile["_scene_path"].endswith("assets\\model.lh") or profile["_scene_path"].endswith("assets/model.lh")


def test_asset_profile_allows_explicit_fixed_pose(tmp_path: Path) -> None:
    profile = load_asset_profile(_write_profile(tmp_path, animation_mode="fixed_pose"))
    assert profile["capture_defaults"]["animation_mode"] == "fixed_pose"


def test_asset_profile_rejects_unknown_animation_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported animation_mode"):
        load_asset_profile(_write_profile(tmp_path, animation_mode="moving"))


def test_material_asset_profile_uses_axis_aligned_eight_views() -> None:
    profile = {
        "runtime": {
            "camera": {
                "yaw": -45,
                "pitch": 14.420773,
                "distance": 7,
                "height_offset": 2,
            }
        },
        "capture_defaults": {
            "animation_mode": "fixed_pose",
            "fixed_animation_state": "swim",
            "fixed_animation_time": 0.25,
            "yaw_offset": -45,
            "pitch_offset": 14.420773,
            "camera_distance": 7,
            "camera_height_factor": 0.2,
            "views": [{"view_id": "editor_view", "yaw": 17, "pitch": 12}],
        },
    }

    canonicalize_axis_aligned_eight_view_profile(profile)

    assert profile["runtime"]["camera"]["yaw"] == 0.0
    assert profile["runtime"]["camera"]["pitch"] == 0.0
    assert profile["runtime"]["camera"]["height_offset"] == 0.0
    assert profile["capture_defaults"]["yaw_offset"] == 0.0
    assert profile["capture_defaults"]["pitch_offset"] == 0.0
    assert profile["capture_defaults"]["camera_height_factor"] == 0.0
    assert profile["capture_defaults"]["animation_mode"] == "disabled"
    assert profile["capture_defaults"]["freeze_animators"] is True
    assert "fixed_animation_state" not in profile["capture_defaults"]
    assert "fixed_animation_time" not in profile["capture_defaults"]
    assert [view["yaw"] for view in profile["capture_defaults"]["views"]] == [
        0.0,
        45.0,
        90.0,
        135.0,
        180.0,
        225.0,
        270.0,
        315.0,
    ]
    assert {view["pitch"] for view in profile["capture_defaults"]["views"]} == {0.0}


def test_axis_aligned_contract_removes_asset_specific_fixed_pose() -> None:
    profile = {
        "capture_defaults": {
            "animation_mode": "fixed_pose",
            "fixed_animation_state": "idle1",
            "fixed_animation_time": 0.21875,
        }
    }

    canonicalize_axis_aligned_eight_view_profile(profile)

    defaults = profile["capture_defaults"]
    assert defaults["animation_mode"] == "disabled"
    assert "fixed_animation_state" not in defaults
    assert "fixed_animation_time" not in defaults
