from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from material_fit.assets.stage2_unity_references import (
    audit_stage2_unity_references,
    resolve_stage2_unity_references,
)
from material_fit.experiments.material_cross_engine_stage2_intake import audit_stage2_candidate


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("asset", "canonical_id", "geometry_ready", "clipped_views"),
    [
        (
            "crocodile",
            "1503",
            False,
            {"v000_yaw0_pitch0", "v003_yaw135_pitch0", "v004_yaw180_pitch0"},
        ),
        ("fish", "1504", False, {"v003_yaw135_pitch0", "v004_yaw180_pitch0", "v005_yaw225_pitch0"}),
        ("turtle", "1506", True, set()),
    ],
)
def test_tracked_stage2_unity_references_are_structurally_valid(
    asset: str,
    canonical_id: str,
    geometry_ready: bool,
    clipped_views: set[str],
) -> None:
    reference_set = resolve_stage2_unity_references(REPO_ROOT, asset)
    report = audit_stage2_unity_references(reference_set)

    assert reference_set.asset_id == canonical_id
    assert report["passed"] is True
    assert report["geometry_ready"] is geometry_ready
    assert set(report["clipped_view_ids"]) == clipped_views
    assert report["exporter_version"] == "1.1.0"
    assert report["image_size"] == [900, 700]
    assert len(report["views"]) == 8
    assert all(view["partial_alpha_pixels"] == 0 for view in report["views"])
    assert reference_set.metadata["outputFolder"] == "."
    assert all(Path(view["imagePath"]).name == view["fileName"] for view in reference_set.metadata["views"])


def test_stage2_candidate_mapping_scores_identical_images(tmp_path: Path) -> None:
    reference_set = resolve_stage2_unity_references(REPO_ROOT, "fish")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    for view in reference_set.views:
        shutil.copy2(
            reference_set.root / view["reference_file_name"],
            candidate_dir / view["candidate_file_name"],
        )

    report = audit_stage2_candidate(reference_set, candidate_dir)

    assert report["ready_for_material_optimization"] is True
    assert report["alignment"]["passed"] is True
    assert report["alignment"]["mean_foreground_iou"] == pytest.approx(1.0)
    assert report["material_score"]["score"] == pytest.approx(1.0)
