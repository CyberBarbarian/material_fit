from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from material_fit.vision.stage2_confidence import (
    build_frozen_confidence_mask,
    score_pair_with_frozen_confidence,
    score_pair_with_frozen_confidence_blend,
)
from material_fit.vision.cross_engine_score import score_cross_engine_pair_v3


def _write_square(path: Path, *, x0: int, color: tuple[int, int, int]) -> None:
    pixels = np.full((64, 64, 3), 255, dtype=np.uint8)
    pixels[12:52, x0 : x0 + 40] = color
    Image.fromarray(pixels).save(path)


def test_frozen_confidence_ignores_only_predeclared_geometry_mismatch(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.png"
    start_path = tmp_path / "start.png"
    mask_path = tmp_path / "confidence.png"
    _write_square(reference_path, x0=12, color=(200, 80, 30))
    _write_square(start_path, x0=14, color=(120, 70, 50))

    report = build_frozen_confidence_mask(
        reference_path=reference_path,
        registered_start_path=start_path,
        output_path=mask_path,
        erosion_pixels=3,
    )
    assert report["frozen_before_optimization"] is True
    assert report["candidate_dependent"] is False
    assert report["reference_coverage"] >= report["minimum_reference_coverage"]

    with Image.open(reference_path) as reference, Image.open(mask_path) as confidence:
        outside_changed = np.asarray(reference.convert("RGB")).copy()
        frozen = np.asarray(confidence.convert("L")) >= 128
        outside_changed[~frozen] = (0, 0, 255)
        matching = score_pair_with_frozen_confidence(
            reference,
            Image.fromarray(outside_changed),
            confidence,
        )
        inside_changed = np.asarray(reference.convert("RGB")).copy()
        inside_changed[frozen] = (80, 160, 220)
        perturbed = score_pair_with_frozen_confidence(
            reference,
            Image.fromarray(inside_changed),
            confidence,
        )

    assert matching["status"] == "ok"
    assert matching["score"] > 0.999
    assert perturbed["status"] == "ok"
    assert perturbed["score"] < matching["score"]


def test_frozen_confidence_rejects_candidate_that_erases_the_core(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.png"
    start_path = tmp_path / "start.png"
    mask_path = tmp_path / "confidence.png"
    _write_square(reference_path, x0=12, color=(200, 80, 30))
    _write_square(start_path, x0=12, color=(120, 70, 50))
    build_frozen_confidence_mask(
        reference_path=reference_path,
        registered_start_path=start_path,
        output_path=mask_path,
        erosion_pixels=3,
    )

    with Image.open(reference_path) as reference, Image.open(mask_path) as confidence:
        blank = Image.new("RGB", reference.size, "white")
        result = score_pair_with_frozen_confidence(reference, blank, confidence)

    assert result["status"] == "invalid_confidence_coverage"
    assert result["score"] == 0.0
    assert result["candidate_confidence_coverage"] == 0.0


def test_blended_score_downweights_but_keeps_noncore_foreground(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.png"
    start_path = tmp_path / "start.png"
    mask_path = tmp_path / "confidence.png"
    _write_square(reference_path, x0=12, color=(200, 80, 30))
    _write_square(start_path, x0=14, color=(120, 70, 50))
    build_frozen_confidence_mask(
        reference_path=reference_path,
        registered_start_path=start_path,
        output_path=mask_path,
        erosion_pixels=3,
    )

    with Image.open(reference_path) as reference, Image.open(mask_path) as confidence:
        pixels = np.asarray(reference.convert("RGB")).copy()
        frozen = np.asarray(confidence.convert("L")) >= 128
        foreground = np.max(np.abs(pixels.astype(np.int16) - 255), axis=2) > 8
        pixels[foreground & ~frozen] = (80, 160, 220)
        candidate = Image.fromarray(pixels)
        robust = score_pair_with_frozen_confidence(reference, candidate, confidence)
        full = score_cross_engine_pair_v3(reference, candidate)
        blended = score_pair_with_frozen_confidence_blend(reference, candidate, confidence)

    assert robust["score"] > 0.999
    assert full["score"] < blended["score"] < robust["score"]
    assert blended["score"] == pytest.approx(0.75 * robust["score"] + 0.25 * full["score"])
