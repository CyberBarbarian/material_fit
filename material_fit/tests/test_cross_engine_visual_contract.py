from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from material_fit.experiments.fish_visual_contract_experiment import _parse_args
from material_fit.vision.cross_engine_alignment import score_alignment_pair, score_eight_view_alignment
from material_fit.vision.cross_engine_score import (
    COMPONENT_WEIGHTS_V11,
    aggregate_cross_engine_scores,
    score_cross_engine_pair,
    score_cross_engine_pair_v3,
    score_cross_engine_pair_v4,
    score_cross_engine_pair_v5,
    score_cross_engine_pair_v6,
    score_cross_engine_pair_v7,
    score_cross_engine_pair_v8,
    score_cross_engine_pair_v9,
    score_cross_engine_pair_v10,
    score_cross_engine_pair_v11,
    score_cross_engine_pair_v12,
)


def _fish_like_image(
    *,
    shift_x: int = 0,
    color: tuple[int, int, int] = (90, 150, 210),
    stripe_delta: int = 25,
) -> Image.Image:
    height, width = 96, 128
    yy, xx = np.mgrid[:height, :width]
    body = ((xx - (64 + shift_x)) / 35.0) ** 2 + ((yy - 48) / 20.0) ** 2 <= 1.0
    tail = (xx >= 92 + shift_x) & (xx <= 108 + shift_x) & (np.abs(yy - 48) <= (xx - (92 + shift_x)))
    mask = body | tail
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[mask, :3] = color
    rgba[mask, 3] = 255
    stripe = mask & (((xx + yy) % 12) < 4)
    rgba[stripe, :3] = np.clip(np.asarray(color) + stripe_delta, 0, 255)
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


def test_v4_rejects_texture_collapse_that_keeps_the_mean_color() -> None:
    reference = _fish_like_image(color=(150, 80, 40), stripe_delta=60)
    detailed = _fish_like_image(color=(148, 82, 42), stripe_delta=55)
    flat = _fish_like_image(color=(170, 100, 60), stripe_delta=0)

    detailed_score = score_cross_engine_pair_v4(reference, detailed)
    flat_score = score_cross_engine_pair_v4(reference, flat)

    assert detailed_score["status"] == "ok"
    assert flat_score["status"] == "ok"
    assert detailed_score["components"]["texture_detail_distribution"] > 0.90
    assert flat_score["components"]["texture_detail_distribution"] < 0.55
    assert detailed_score["score"] > flat_score["score"] + 0.15


def test_v4_prefers_moved_matching_texture_over_aligned_flat_texture() -> None:
    reference = _fish_like_image(color=(150, 80, 40), stripe_delta=50)
    moved = _fish_like_image(shift_x=3, color=(150, 80, 40), stripe_delta=50)
    flat = _fish_like_image(color=(160, 90, 50), stripe_delta=0)

    moved_score = score_cross_engine_pair_v4(reference, moved)
    flat_score = score_cross_engine_pair_v4(reference, flat)

    assert moved_score["status"] == "ok"
    assert moved_score["alignment"]["bbox_center_error_px"] >= 2.0
    assert moved_score["score"] > flat_score["score"]


def test_v5_penalizes_model_relative_dark_region_misplacement() -> None:
    height, width = 120, 180
    yy, xx = np.mgrid[:height, :width]
    mask = ((xx - 90) / 70.0) ** 2 + ((yy - 60) / 38.0) ** 2 <= 1.0

    def render(*, dark_left: bool) -> Image.Image:
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        split = xx < 90 if dark_left else xx >= 90
        rgba[mask & split, :3] = (35, 25, 20)
        rgba[mask & ~split, :3] = (220, 130, 40)
        rgba[mask, 3] = 255
        return Image.fromarray(rgba)

    reference = render(dark_left=True)
    matching = render(dark_left=True)
    swapped = render(dark_left=False)

    matching_score = score_cross_engine_pair_v5(reference, matching)
    swapped_score = score_cross_engine_pair_v5(reference, swapped)

    assert matching_score["components"]["spatial_luminance_layout"] == 1.0
    assert swapped_score["components"]["spatial_luminance_layout"] < 0.55
    assert matching_score["score"] > swapped_score["score"] + 0.20


def test_v6_penalizes_model_relative_hue_misplacement() -> None:
    height, width = 120, 180
    yy, xx = np.mgrid[:height, :width]
    mask = ((xx - 90) / 70.0) ** 2 + ((yy - 60) / 38.0) ** 2 <= 1.0

    def render(*, orange_left: bool) -> Image.Image:
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        split = xx < 90 if orange_left else xx >= 90
        rgba[mask & split, :3] = (220, 100, 25)
        rgba[mask & ~split, :3] = (35, 155, 170)
        rgba[mask, 3] = 255
        return Image.fromarray(rgba)

    reference = render(orange_left=True)
    matching = render(orange_left=True)
    swapped = render(orange_left=False)

    matching_score = score_cross_engine_pair_v6(reference, matching)
    swapped_score = score_cross_engine_pair_v6(reference, swapped)

    assert matching_score["components"]["spatial_hue_mass"] == 1.0
    assert swapped_score["components"]["spatial_hue_mass"] < 0.25
    assert matching_score["score"] > swapped_score["score"] + 0.30


def test_v7_penalizes_chromatic_contamination_in_dark_regions() -> None:
    height, width = 120, 180
    yy, xx = np.mgrid[:height, :width]
    mask = ((xx - 90) / 70.0) ** 2 + ((yy - 60) / 38.0) ** 2 <= 1.0
    center = mask & (xx > 65) & (xx < 115)

    def render(*, dark_color: tuple[int, int, int]) -> Image.Image:
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[mask, :3] = (220, 115, 30)
        rgba[center, :3] = dark_color
        rgba[mask, 3] = 255
        return Image.fromarray(rgba)

    reference = render(dark_color=(30, 28, 24))
    matching = render(dark_color=(30, 28, 24))
    olive = render(dark_color=(62, 76, 28))

    matching_score = score_cross_engine_pair_v7(reference, matching)
    olive_score = score_cross_engine_pair_v7(reference, olive)

    assert matching_score["components"]["spatial_dark_chroma"] == 1.0
    assert olive_score["components"]["spatial_dark_chroma"] < 0.80
    assert matching_score["score"] > olive_score["score"] + 0.15


def test_v8_penalizes_olive_shift_with_similar_hue() -> None:
    reference = _fish_like_image(color=(220, 110, 20), stripe_delta=20)
    matching = _fish_like_image(color=(220, 110, 20), stripe_delta=20)
    olive = _fish_like_image(color=(130, 120, 20), stripe_delta=20)

    matching_score = score_cross_engine_pair_v8(reference, matching)
    olive_score = score_cross_engine_pair_v8(reference, olive)

    assert matching_score["components"]["spatial_chromaticity"] == 1.0
    assert olive_score["components"]["spatial_chromaticity"] < 0.70
    assert matching_score["score"] > olive_score["score"] + 0.20


def test_v9_penalizes_dim_candidate_with_matching_chromaticity() -> None:
    reference = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    matching = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    dim = _fish_like_image(color=(138, 72, 18), stripe_delta=12)

    matching_score = score_cross_engine_pair_v9(reference, matching)
    dim_score = score_cross_engine_pair_v9(reference, dim)

    assert matching_score["components"]["spatial_radiance"] == 1.0
    assert dim_score["components"]["spatial_chromaticity"] > 0.95
    assert dim_score["components"]["spatial_radiance"] < 0.75
    assert matching_score["score"] > dim_score["score"] + 0.10


def test_v10_uses_reference_adaptive_highlight_energy() -> None:
    reference = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    matching = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    dim = _fish_like_image(color=(138, 72, 18), stripe_delta=12)

    matching_score = score_cross_engine_pair_v10(reference, matching)
    dim_score = score_cross_engine_pair_v10(reference, dim)

    assert matching_score["components"]["spatial_highlight_energy"] == 1.0
    assert dim_score["components"]["spatial_chromaticity"] > 0.95
    assert dim_score["components"]["spatial_highlight_energy"] < 0.75
    assert matching_score["score"] > dim_score["score"] + 0.10
    thresholds = dim_score["spatial_highlight_energy"]["thresholds"]
    assert thresholds == sorted(thresholds)


def test_v11_balances_essential_material_components() -> None:
    reference = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    dim = _fish_like_image(color=(138, 72, 18), stripe_delta=12)

    score = score_cross_engine_pair_v11(reference, dim)

    expected = np.exp(
        sum(
            weight * np.log(max(1e-6, score["components"][name]))
            for name, weight in COMPONENT_WEIGHTS_V11.items()
        )
    )
    assert score["aggregation"] == "weighted_geometric_mean"
    assert score["score"] == expected
    assert sum(COMPONENT_WEIGHTS_V11.values()) == 1.0


def test_v12_penalizes_imbalanced_material_dimensions() -> None:
    reference = _fish_like_image(color=(230, 120, 30), stripe_delta=20)
    dim = _fish_like_image(color=(138, 72, 18), stripe_delta=12)

    score = score_cross_engine_pair_v12(reference, dim)
    values = np.asarray(
        [score["components"][name] for name in score["component_names"]],
        dtype=np.float64,
    )

    assert score["aggregation"] == "equal_component_mean_minus_population_std"
    assert score["component_mean"] == values.mean()
    assert score["component_std"] == values.std()
    assert score["score"] == max(0.0, min(1.0, values.mean() - values.std()))


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
