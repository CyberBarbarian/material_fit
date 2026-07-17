from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from material_fit.assets.laya_scene_bounds import (
    perspective_camera_distance,
    target_bounds_from_lh,
)


def test_target_bounds_apply_target_rotation_and_scale(tmp_path: Path) -> None:
    scene = {
        "_$type": "Sprite3D",
        "name": "root",
        "_$child": [
            {
                "_$type": "Sprite3D",
                "name": "model",
                "transform": {
                    "localRotation": {
                        "x": math.sin(math.pi / 4),
                        "w": math.cos(math.pi / 4),
                    },
                    "localScale": {"x": 0.5, "y": 0.5, "z": 0.5},
                },
                "_$child": [
                    {
                        "_$type": "Sprite3D",
                        "name": "mesh",
                        "_$comp": [
                            {
                                "_$type": "SkinnedMeshRenderer",
                                "localBounds": {
                                    "min": {"x": -2, "y": -4, "z": -6},
                                    "max": {"x": 2, "y": 4, "z": 6},
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "model.lh"
    path.write_text(json.dumps(scene), encoding="utf-8")

    bounds = target_bounds_from_lh(path, "model")

    assert bounds.center == pytest.approx((0.0, 0.0, 0.0))
    assert bounds.extent == pytest.approx((1.0, 3.0, 2.0))
    assert perspective_camera_distance(
        bounds, width=800, height=600, vertical_field_of_view=60, margin=1.0
    ) == pytest.approx(bounds.radius / math.sin(math.radians(30)))


def test_target_bounds_reject_missing_inline_geometry(tmp_path: Path) -> None:
    path = tmp_path / "model.lh"
    path.write_text(json.dumps({"name": "model"}), encoding="utf-8")

    with pytest.raises(ValueError, match="no inline localBounds"):
        target_bounds_from_lh(path, "model")
