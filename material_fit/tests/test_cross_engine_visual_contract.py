from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from material_fit.experiments.fish_visual_contract_experiment import _parse_args
from material_fit.vision.cross_engine_alignment import score_alignment_pair, score_eight_view_alignment
from material_fit.vision.cross_engine_score import (
    aggregate_cross_engine_scores,
    score_cross_engine_pair,
    score_cross_engine_pair_v3,
)


def _fish_like_image(*, shift_x: int = 0, color: tuple[int, int, int] = (90, 150, 210)) -> Image.Image:
    height, width = 96, 128
    yy, xx = np.mgrid[:height, :width]
    body = ((xx - (64 + shift_x)) / 35.0) ** 2 + ((yy - 48) / 20.0) ** 2 <= 1.0
    tail = (xx >= 92 + shift_x) & (xx <= 108 + shift_x) & (np.abs(yy - 48) <= (xx - (92 + shift_x)))
    mask = body | tail
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[mask, :3] = color
    rgba[mask, 3] = 255
    stripe = mask & (((xx + yy) % 12) < 4)
    rgba[stripe, :3] = np.clip(np.asarray(color) + 25, 0, 255)
    return Image.fromarray(rgba)


def test_identical_transparent_render_scores_one() -> None:
    reference = _fish_like_image()
    result = score_cross_engine_pair(reference, reference.copy())

    assert result["status"] == "ok"
    assert result["score"] == 1.0
    assert result["alignment"]["foreground_iou"] == 1.0


def test_identical_thin_opaque_render_is_not_rejected_by_canvas_area() -> None:
    array = np.full((700, 900, 4), 255, dtype=np.uint8)
    array[280:420, 442:458, :3] = (45, 120, 190)
    reference = Image.fromarray(array)

    result = score_cross_engine_pair_v3(reference, reference.copy())

    assert result["status"] == "ok"
    assert result["score"] == 1.0
    assert result["alignment"]["foreground_iou"] == 1.0
    assert result["trusted_core_pixels"] >= result["minimum_trusted_core_pixels"]
    assert result["minimum_trusted_core_pixels"] < int(0.02 * 700 * 900)


def test_transparent_background_rgb_does_not_change_score() -> None:
    reference = _fish_like_image()
    candidate_array = np.asarray(reference).copy()
    candidate_array[candidate_array[:, :, 3] == 0, :3] = (255, 0, 255)
    candidate = Image.fromarray(candidate_array)

    result = score_cross_engine_pair(reference, candidate)

    assert result["status"] == "ok"
    assert result["score"] == 1.0


def test_color_perturbation_strength_is_monotonic() -> None:
    reference = _fish_like_image(color=(90, 150, 210))
    tiny = _fish_like_image(color=(92, 151, 208))
    mild = _fish_like_image(color=(105, 140, 190))
    strong = _fish_like_image(color=(170, 80, 60))

    scores = [score_cross_engine_pair(reference, image)["score"] for image in (tiny, mild, strong)]

    assert scores[0] > scores[1] > scores[2]


def test_v3_penalizes_desaturated_candidate_with_similar_luminance() -> None:
    reference = _fish_like_image(color=(190, 80, 45))
    candidate = _fish_like_image(color=(105, 105, 105))

    v2 = score_cross_engine_pair(reference, candidate)
    v3 = score_cross_engine_pair_v3(reference, candidate)

    assert v3["status"] == "ok"
    assert v3["components"]["chroma_hue"] < 0.75
    assert v3["score"] < v2["score"] - 0.03


def test_v3_color_perturbation_strength_is_monotonic() -> None:
    reference = _fish_like_image(color=(90, 150, 210))
    tiny = _fish_like_image(color=(92, 151, 208))
    mild = _fish_like_image(color=(105, 140, 190))
    strong = _fish_like_image(color=(170, 80, 60))

    scores = [score_cross_engine_pair_v3(reference, image)["score"] for image in (tiny, mild, strong)]

    assert scores[0] > scores[1] > scores[2]


def test_geometry_shift_remains_visible_without_registration() -> None:
    reference = _fish_like_image()
    candidate = _fish_like_image(shift_x=12)

    alignment = score_alignment_pair(reference, candidate)
    score = score_cross_engine_pair(reference, candidate)

    assert alignment["foreground_iou"] < 0.75
    assert alignment["bbox_center_error_px"] >= 11.0
    assert score["status"] == "ok"
    assert score["alignment"]["bbox_center_error_px"] == alignment["bbox_center_error_px"]
    assert "translation" in " ".join(score["notes"])


def test_eight_view_report_and_robust_aggregation(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference"
    candidate_dir = tmp_path / "candidate"
    reference_dir.mkdir()
    candidate_dir.mkdir()
    views = []
    pair_scores = []
    for index in range(8):
        file_name = f"view_{index}.png"
        view = {"view_id": f"v{index}", "file_name": file_name}
        views.append(view)
        reference = _fish_like_image()
        candidate = _fish_like_image(color=(90 + index, 150, 210 - index))
        reference.save(reference_dir / file_name)
        candidate.save(candidate_dir / file_name)
        pair_scores.append(score_cross_engine_pair(reference, candidate))

    alignment = score_eight_view_alignment(
        reference_dir=reference_dir,
        candidate_dir=candidate_dir,
        views=views,
    )
    aggregate = aggregate_cross_engine_scores(pair_scores)

    assert alignment is not None
    assert alignment["passed"] is True
    assert alignment["view_count"] == 8
    assert aggregate["status"] == "ok"
    assert aggregate["min_score"] <= aggregate["score"] <= aggregate["mean_score"]


def test_visual_contract_settle_frames_default_and_override() -> None:
    assert _parse_args([]).settle_frames == 0
    assert _parse_args(["--settle-frames", "2"]).settle_frames == 2
