from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageEnhance, ImageFilter

pytest.importorskip("DISTS_pytorch")
pytest.importorskip("torch")

from material_fit.experiments.material_stage2_scorer_validation import (  # noqa: E402
    _discover_cases,
)
from material_fit.vision.cross_engine_alignment import foreground_mask  # noqa: E402
from material_fit.vision.dists_score import (  # noqa: E402
    DEFAULT_ALIGNED_RGB_IMAGE_SIZE,
    DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE,
    DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE,
    DISTS_ALIGNED_RGB_DISTS_WEIGHT,
    DISTS_ALIGNED_RGB_DESCRIPTOR_WEIGHT,
    DISTS_ALIGNED_RGB_LOCAL_CONTRAST_WEIGHT,
    DISTS_ALIGNED_RGB_METRIC,
    DISTS_ALIGNED_RGB_PIXEL_WEIGHT,
    DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT,
    DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT,
    DISTS_ALIGNED_RGB_V3_METRIC,
    DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT,
    DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT,
    DISTS_ALIGNED_RGB_V5_METRIC,
    DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT,
    DISTS_METRIC,
    DISTS_MATERIAL_METRIC,
    DISTS_MATERIAL_RESIDUAL_CONTRACT,
    DISTS_RESIDUAL_CONTRACT,
    ForegroundDISTSAlignedRGBScorer,
    ForegroundDISTSScorer,
    ForegroundDISTSMaterialScorer,
    normalized_foreground_tensor,
)


def _render() -> Image.Image:
    image = Image.new("RGBA", (96, 64), "white")
    values = np.asarray(image).copy()
    values[18:46, 20:76, :3] = [210, 80, 25]
    values[18:46, 20:76, 3] = 255
    values[25:39, 35:61, :3] = [255, 210, 50]
    return Image.fromarray(values)


def test_stage2_dists_has_no_asset_or_target_color_rules() -> None:
    source_path = Path(__file__).resolve().parents[1] / "vision" / "dists_score.py"
    source = source_path.read_text(encoding="utf-8").lower()

    for forbidden in ("fish", "turtle", "crocodile", "1503", "1504", "1506"):
        assert forbidden not in source


def test_normalized_tensor_reuses_foreground_mask_without_changing_pixels() -> None:
    source = _render()
    mask, _ = foreground_mask(source)

    direct = normalized_foreground_tensor(source, image_size=64)
    reused = normalized_foreground_tensor(source, image_size=64, foreground=mask)

    assert np.array_equal(direct.numpy(), reused.numpy())


def test_dists_score_prefers_identical_image(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    darker = ImageEnhance.Brightness(reference.convert("RGB")).enhance(0.5)

    scorer = ForegroundDISTSScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
        emit_residual_features=True,
    )
    same = scorer.score_image(reference_path, reference)
    changed = scorer.score_image(reference_path, darker)

    assert same.fit_score == pytest.approx(1.0, abs=1e-6)
    assert same.distance == pytest.approx(0.0, abs=1e-6)
    assert changed.fit_score < same.fit_score
    assert len(changed.residual_features) > 1000
    payload = changed.as_dict()
    assert payload["metric"] == DISTS_METRIC
    assert payload["residual_contract"] == DISTS_RESIDUAL_CONTRACT
    assert len(changed.residual_features) == 1475 + DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE
    assert max(abs(value) for value in same.residual_features) < 1.0e-6
    residual_energy = float(np.dot(changed.residual_features, changed.residual_features))
    assert residual_energy == pytest.approx(changed.distance, rel=0.08, abs=1.0e-5)


def test_dists_penalizes_empty_candidate_without_crashing(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    empty = Image.new("RGBA", reference.size, "white")

    scorer = ForegroundDISTSScorer(image_size=64, device="cpu", torch_threads=1)
    result = scorer.score_image(reference_path, empty)

    assert 0.0 < result.fit_score < 1.0
    assert result.candidate_foreground_pixels == 0


def test_composite_score_combines_dists_and_aligned_material(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    darker = ImageEnhance.Brightness(reference.convert("RGB")).enhance(0.5)

    scorer = ForegroundDISTSMaterialScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
        emit_residual_features=True,
    )
    same = scorer.score_image(reference_path, reference)
    changed = scorer.score_image(reference_path, darker)

    assert same.fit_score == pytest.approx(1.0, abs=1e-6)
    assert changed.fit_score < same.fit_score
    payload = changed.as_dict()
    assert payload["metric"] == DISTS_MATERIAL_METRIC
    assert payload["fit_score"] == pytest.approx(
        0.25 * payload["dists_fit_score"]
        + 0.75 * payload["aligned_material_fit_score"]
    )
    assert payload["residual_features"]
    assert payload["residual_contract"] == DISTS_MATERIAL_RESIDUAL_CONTRACT
    assert len(changed.residual_features) == (
        len(changed.dists.residual_features)
        + DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE**2 * 3
        + 23
    )
    assert max(abs(value) for value in same.residual_features) < 1.0e-6


def test_aligned_rgb_score_emits_dense_signed_inverse_feedback(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    darker = ImageEnhance.Brightness(reference.convert("RGB")).enhance(0.5)

    scorer = ForegroundDISTSAlignedRGBScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
        emit_residual_features=True,
    )
    same = scorer.score_image(reference_path, reference)
    changed = scorer.score_image(reference_path, darker)

    assert same.fit_score == pytest.approx(1.0, abs=1e-6)
    assert same.normalized_rgb_mae == pytest.approx(0.0, abs=1e-8)
    assert changed.fit_score < same.fit_score
    assert changed.normalized_rgb_mae > 0.0
    payload = changed.as_dict()
    assert payload["metric"] == DISTS_ALIGNED_RGB_METRIC
    assert payload["fit_score"] == pytest.approx(
        DISTS_ALIGNED_RGB_DISTS_WEIGHT * payload["dists_fit_score"]
        + DISTS_ALIGNED_RGB_PIXEL_WEIGHT * payload["aligned_rgb_fit_score"]
        + DISTS_ALIGNED_RGB_LOCAL_CONTRAST_WEIGHT
        * payload["local_contrast_fit_score"]
    )
    assert len(changed.residual_features) == (
        len(changed.dists.residual_features)
        + DEFAULT_ALIGNED_RGB_IMAGE_SIZE**2 * 3
        + DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE**2 * 3
        + 23
        + 33
    )
    assert max(abs(value) for value in same.residual_features) < 1.0e-6


def test_legacy_inverse_score_preserves_the_v3_search_objective(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    darker = ImageEnhance.Brightness(reference.convert("RGB")).enhance(0.5)

    scorer = ForegroundDISTSAlignedRGBScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
        emit_residual_features=True,
        metric=DISTS_ALIGNED_RGB_V3_METRIC,
        dists_weight=DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT,
        aligned_rgb_weight=DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT,
        material_descriptor_weight=DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT,
        local_contrast_weight=0.0,
        residual_contract=(
            "weighted_dists_normalized_rgb_and_material_descriptor_v3"
        ),
    )
    payload = scorer.score_image(reference_path, darker).as_dict()

    assert payload["metric"] == DISTS_ALIGNED_RGB_V3_METRIC
    assert payload["fit_score"] == pytest.approx(
        DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT * payload["dists_fit_score"]
        + DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT * payload["aligned_rgb_fit_score"]
    )
    assert payload["residual_contract"] == (
        "weighted_dists_normalized_rgb_and_material_descriptor_v3"
    )
    assert len(payload["residual_features"]) == (
        len(scorer.score_image(reference_path, darker).dists.residual_features)
        + DEFAULT_ALIGNED_RGB_IMAGE_SIZE**2 * 3
        + DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE**2 * 3
        + 23
    )


def test_v5_metric_keeps_the_previous_two_term_acceptance_formula(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    darker = ImageEnhance.Brightness(reference.convert("RGB")).enhance(0.5)
    scorer = ForegroundDISTSAlignedRGBScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
        metric=DISTS_ALIGNED_RGB_V5_METRIC,
        dists_weight=DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT,
        aligned_rgb_weight=DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT,
        local_contrast_weight=0.0,
    )

    payload = scorer.score_image(reference_path, darker).as_dict()

    assert payload["metric"] == DISTS_ALIGNED_RGB_V5_METRIC
    assert payload["fit_score"] == pytest.approx(
        DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT * payload["dists_fit_score"]
        + DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT * payload["aligned_rgb_fit_score"]
    )
    assert "local_contrast_fit_score" not in payload


def test_v6_metric_penalizes_lost_local_highlight_shadow_structure(tmp_path: Path) -> None:
    reference = _render()
    reference_path = tmp_path / "reference.png"
    reference.save(reference_path)
    blurred = reference.filter(ImageFilter.GaussianBlur(radius=5.0))
    scorer = ForegroundDISTSAlignedRGBScorer(
        image_size=64,
        device="cpu",
        torch_threads=1,
    )

    same = scorer.score_image(reference_path, reference).as_dict()
    changed = scorer.score_image(reference_path, blurred).as_dict()

    assert same["local_contrast_fit_score"] == pytest.approx(1.0, abs=1.0e-8)
    assert changed["local_contrast_fit_score"] < same["local_contrast_fit_score"]
    assert changed["local_contrast_distance"] > 0.0


def test_generic_validation_discovers_arbitrary_case_name(tmp_path: Path) -> None:
    case = tmp_path / "previously_unseen_asset"
    for directory in ("target_render", "start_render", "best_render"):
        (case / directory).mkdir(parents=True)
    (case / "stage1_report.json").write_text("{}", encoding="utf-8")

    assert _discover_cases(tmp_path) == [case]
