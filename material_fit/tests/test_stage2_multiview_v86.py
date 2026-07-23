from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from material_fit.experiments.material_cross_engine_stage2_multiview_v86 import (
    load_external_observations,
)


def _write_manifest(tmp_path: Path, count: int) -> Path:
    observations = []
    for index in range(count):
        image_path = tmp_path / f"reference_{index:03d}.png"
        Image.new("RGBA", (16, 16), (index % 255, 20, 30, 255)).save(image_path)
        observations.append(
            {
                "view_id": f"arbitrary_{index}",
                "yaw": index * (360.0 / count),
                "pitch": 0.0,
                "image_path": image_path.name,
            }
        )
    path = tmp_path / "observations.json"
    path.write_text(json.dumps({"observations": observations}), encoding="utf-8")
    return path


@pytest.mark.parametrize("count", [1, 3, 8, 11])
def test_external_observation_manifest_accepts_any_positive_count(
    tmp_path: Path,
    count: int,
) -> None:
    result = load_external_observations(_write_manifest(tmp_path, count))

    assert len(result.views) == count
    assert [view["view_id"] for view in result.views] == [
        f"arbitrary_{index}" for index in range(count)
    ]
    assert len({view["file_name"] for view in result.views}) == count
    assert all(Path(view["reference_file_name"]).is_file() for view in result.views)


def test_external_observation_manifest_rejects_empty_and_duplicate_ids(
    tmp_path: Path,
) -> None:
    empty_path = tmp_path / "empty.json"
    empty_path.write_text('{"observations": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        load_external_observations(empty_path)

    manifest_path = _write_manifest(tmp_path, 2)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["observations"][1]["view_id"] = payload["observations"][0]["view_id"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_external_observations(manifest_path)
