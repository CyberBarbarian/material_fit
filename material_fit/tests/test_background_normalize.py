"""Unit tests for E-011 background normaliser.

These exercise the pure-numpy preprocessor in isolation. Integration
with ``vision/diff_analysis.py`` is covered by
``test_diff_analysis_perceptual.py`` (E-009 family) which now also
sees the bg substitution under default config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.vision.background_normalize import (  # noqa: E402
    BackgroundNormalizeConfig,
    NormalizeResult,
    detect_corner_background,
    normalize_background,
    normalize_pair,
)


# --------------------------------------------------------------------
# detect_corner_background


def _make_image(bg_rgb: tuple[int, int, int], fg_rgb: tuple[int, int, int]) -> np.ndarray:
    """64x64 image with a 32x32 foreground patch in the centre."""
    img = np.full((64, 64, 3), bg_rgb, dtype=np.uint8)
    img[16:48, 16:48] = fg_rgb
    return img


def test_detect_corner_background_returns_pure_bg_for_uniform_corners():
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    bg = detect_corner_background(img)
    assert tuple(int(v) for v in bg) == (71, 71, 71)


def test_detect_corner_background_uses_median_to_resist_corner_noise():
    img = _make_image(bg_rgb=(134, 151, 180), fg_rgb=(90, 90, 90))
    # Sprinkle a few noisy pixels into one corner — median should ignore.
    img[0:2, 0:2] = (255, 0, 0)
    bg = detect_corner_background(img, corner_size=12)
    # Most of the corner is still (134, 151, 180); median wins.
    assert tuple(int(v) for v in bg) == (134, 151, 180)


def test_detect_corner_background_handles_small_images():
    """Corner size auto-shrinks when the image is smaller than 2 × corner_size."""
    img = np.full((4, 4, 3), 88, dtype=np.uint8)
    bg = detect_corner_background(img, corner_size=12)
    assert tuple(int(v) for v in bg) == (88, 88, 88)


def test_detect_corner_background_rejects_non_image_input():
    bad = np.zeros((10, 10), dtype=np.uint8)
    with pytest.raises(ValueError, match="HxWx3"):
        detect_corner_background(bad)


# --------------------------------------------------------------------
# normalize_background — core behaviour


def test_normalize_replaces_pure_bg_with_target():
    """Pixels at exactly the bg colour become exactly target_bg."""
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(
        enabled=True,
        target_bg=(128, 128, 128),
        soft_low=2.0,
        soft_high=4.0,
    )
    result = normalize_background(img, cfg)
    # A pure-bg pixel at (0,0) must become exactly target_bg.
    assert tuple(int(v) for v in result.image[0, 0, :3]) == (128, 128, 128)
    # Forensic counters: most of the 64x64 = 4096 pixels are bg.
    # We have 32x32 = 1024 fg pixels and 4096 - 1024 = 3072 bg pixels.
    assert result.n_pixels_pure_bg >= 3000
    assert result.n_pixels_pure_fg >= 1000


def test_normalize_keeps_clear_foreground_unchanged():
    """A pixel far from bg (e.g. saturated red on grey bg) is untouched."""
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(
        target_bg=(128, 128, 128), soft_low=2.0, soft_high=4.0
    )
    result = normalize_background(img, cfg)
    assert tuple(int(v) for v in result.image[32, 32, :3]) == (200, 30, 30)


def test_normalize_disabled_returns_input_unchanged():
    """When ``enabled=False`` the image must be returned bit-identical
    even though the bg detector still runs (it populates the
    forensic ``detected_bg`` field)."""
    img = _make_image(bg_rgb=(50, 60, 70), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(enabled=False)
    result = normalize_background(img, cfg)
    np.testing.assert_array_equal(result.image, img)


def test_normalize_respects_source_bg_override():
    """When the caller supplies the bg colour, the corner detector
    is skipped — useful when you've already detected the bg via
    auto_mask and want to share state."""
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(target_bg=(0, 0, 0), soft_low=2.0, soft_high=4.0)
    result = normalize_background(img, cfg, source_bg_override=(0, 255, 0))
    assert tuple(int(v) for v in result.detected_bg) == (0, 255, 0)
    # The bg pixel (71,71,71) is far from the override (0,255,0) →
    # treated as foreground → left untouched.
    assert tuple(int(v) for v in result.image[0, 0, :3]) == (71, 71, 71)


def test_normalize_soft_zone_blends_smoothly():
    """A pixel at the midpoint of the soft zone gets a 50/50 blend
    between its original colour and ``pixel + (target − bg)`` —
    i.e. half of the bg-substitution shift."""
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    bg = np.array([100, 100, 100], dtype=np.float32)
    target = np.array([200, 100, 100], dtype=np.float32)  # red-shift +100R
    # Construct a pixel exactly at L2 dist = 3 (midpoint of [2, 4]).
    # E.g. (100 + 3, 100, 100) is exactly distance 3 along R.
    img[0, 0] = (103, 100, 100)
    img[0, 1] = (100, 100, 100)  # pure bg
    img[0, 2] = (160, 100, 100)  # well outside soft zone
    cfg = BackgroundNormalizeConfig(
        target_bg=(int(target[0]), int(target[1]), int(target[2])),
        soft_low=2.0,
        soft_high=4.0,
    )
    result = normalize_background(img, cfg, source_bg_override=bg.tolist())
    # Pure bg → target.
    assert tuple(int(v) for v in result.image[0, 1, :3]) == (200, 100, 100)
    # Outside soft zone → unchanged.
    assert tuple(int(v) for v in result.image[0, 2, :3]) == (160, 100, 100)
    # Midpoint pixel: alpha_fg = 0.5 → new = (103, 100, 100) + 0.5 * (100, 0, 0)
    # = (153, 100, 100).
    midpoint = result.image[0, 0, :3]
    assert int(midpoint[0]) == 153
    assert int(midpoint[1]) == 100
    assert int(midpoint[2]) == 100


def test_normalize_handles_rgba_input_and_preserves_alpha():
    img = np.zeros((4, 4, 4), dtype=np.uint8)
    img[..., :3] = (71, 71, 71)
    img[..., 3] = 200  # custom alpha plane
    cfg = BackgroundNormalizeConfig(target_bg=(128, 128, 128), soft_low=2.0, soft_high=4.0)
    result = normalize_background(img, cfg)
    assert result.image.shape == (4, 4, 4)
    assert result.image.dtype == np.uint8
    # RGB substituted, alpha plane preserved untouched.
    assert tuple(int(v) for v in result.image[0, 0, :3]) == (128, 128, 128)
    assert int(result.image[0, 0, 3]) == 200


def test_normalize_rejects_grayscale_input():
    img = np.zeros((4, 4), dtype=np.uint8)
    with pytest.raises(ValueError, match="HxWx3"):
        normalize_background(img)


def test_normalize_degenerate_ramp_falls_back_to_hard_step():
    """When ``soft_high <= soft_low`` we drop into a hard step at
    ``soft_low``; pixels strictly within that boundary get the full
    bg-to-target shift applied. Note this preserves the original
    pixel's *deviation* from bg, so a slightly-off-pure-bg pixel
    gets the same deviation around target_bg (this is by design —
    we don't want to clip small rendering noise away)."""
    img = np.array(
        [
            [[100, 100, 100], [102, 100, 100], [110, 100, 100]],
            [[100, 100, 100], [100, 100, 100], [100, 100, 100]],
        ],
        dtype=np.uint8,
    )
    cfg = BackgroundNormalizeConfig(
        target_bg=(0, 0, 0), soft_low=5.0, soft_high=5.0
    )
    result = normalize_background(img, cfg, source_bg_override=(100, 100, 100))
    # Pure bg pixel: new = bg + (target - bg) = (0, 0, 0).
    assert tuple(int(v) for v in result.image[0, 0, :3]) == (0, 0, 0)
    # Off-by-2 in R within hard step: new = (102,100,100) + (-100,-100,-100)
    # = (2, 0, 0). Deviation from bg is preserved around target.
    assert tuple(int(v) for v in result.image[0, 1, :3]) == (2, 0, 0)
    # Pixel at L2=10 > 5 → fg → unchanged.
    assert tuple(int(v) for v in result.image[0, 2, :3]) == (110, 100, 100)


def test_normalize_pair_processes_each_image_independently():
    """Each image's bg is detected separately — that's the whole
    point of E-011 (the two engines may have different bg colours)."""
    img_a = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    img_b = _make_image(bg_rgb=(134, 151, 180), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(target_bg=(128, 128, 128), soft_low=2.0, soft_high=4.0)
    res_a, res_b = normalize_pair(img_a, img_b, cfg)
    # Both bg corners now read as (128,128,128).
    assert tuple(int(v) for v in res_a.image[0, 0, :3]) == (128, 128, 128)
    assert tuple(int(v) for v in res_b.image[0, 0, :3]) == (128, 128, 128)
    # Foregrounds (saturated red, far from any bg) are unchanged in both.
    assert tuple(int(v) for v in res_a.image[32, 32, :3]) == (200, 30, 30)
    assert tuple(int(v) for v in res_b.image[32, 32, :3]) == (200, 30, 30)


def test_normalize_result_coverage_sums_to_one():
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(target_bg=(128, 128, 128), soft_low=2.0, soft_high=4.0)
    result = normalize_background(img, cfg)
    coverage = result.coverage
    total = coverage["pure_bg"] + coverage["soft_zone"] + coverage["pure_fg"]
    assert pytest.approx(total, abs=1e-6) == 1.0


def test_normalize_result_as_dict_is_json_friendly():
    img = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cfg = BackgroundNormalizeConfig(target_bg=(128, 128, 128))
    result = normalize_background(img, cfg)
    payload = result.as_dict()
    import json
    encoded = json.dumps(payload)  # must not raise
    assert "detected_bg" in payload
    assert payload["detected_bg"] == [71, 71, 71]
    assert payload["target_bg"] == [128, 128, 128]
    assert isinstance(json.loads(encoded), dict)


# --------------------------------------------------------------------
# Integration with auto_mask through analyze_image_diff


def test_diff_analysis_records_bg_normalize_payload(tmp_path):
    """When E-011 is enabled and auto_mask succeeds, the analysis
    output exposes a ``bg_normalize`` block with detected/target
    bg colours so downstream UIs and ``decision.json`` consumers
    can show what the preprocessor did."""
    from PIL import Image
    from tools.material_fit.vision.diff_analysis import (
        ImageDiffConfig,
        analyze_image_diff,
    )

    ref = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cand = _make_image(bg_rgb=(134, 151, 180), fg_rgb=(200, 30, 30))
    ref_path = tmp_path / "ref.png"
    cand_path = tmp_path / "cand.png"
    Image.fromarray(ref).save(ref_path)
    Image.fromarray(cand).save(cand_path)

    cfg = ImageDiffConfig(
        reference_path=ref_path,
        candidate_path=cand_path,
        output_dir=tmp_path,
    )
    result = analyze_image_diff(cfg)
    payload = result.get("bg_normalize")
    assert payload is not None
    assert payload["enabled"] is True
    assert payload["reference"]["detected_bg"] == [71, 71, 71]
    assert payload["candidate"]["detected_bg"] == [134, 151, 180]
    assert payload["reference"]["target_bg"] == [128, 128, 128]


def test_diff_analysis_skips_bg_normalize_when_disabled(tmp_path):
    from PIL import Image
    from tools.material_fit.vision.diff_analysis import (
        ImageDiffConfig,
        analyze_image_diff,
    )

    ref = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cand = _make_image(bg_rgb=(134, 151, 180), fg_rgb=(200, 30, 30))
    ref_path = tmp_path / "ref.png"
    cand_path = tmp_path / "cand.png"
    Image.fromarray(ref).save(ref_path)
    Image.fromarray(cand).save(cand_path)

    cfg = ImageDiffConfig(
        reference_path=ref_path,
        candidate_path=cand_path,
        output_dir=tmp_path,
        bg_normalize_enabled=False,
    )
    result = analyze_image_diff(cfg)
    payload = result.get("bg_normalize")
    assert payload is not None
    assert payload["enabled"] is False
    assert "disabled" in payload["reason"]


def test_diff_analysis_skips_bg_normalize_when_caller_supplies_mask(tmp_path):
    """An explicit mask means the caller has already chosen what is
    foreground; the bg detector would over-substitute interior
    pixels that happen to share the corner colour."""
    from PIL import Image
    from tools.material_fit.vision.diff_analysis import (
        ImageDiffConfig,
        analyze_image_diff,
    )

    ref = _make_image(bg_rgb=(71, 71, 71), fg_rgb=(200, 30, 30))
    cand = _make_image(bg_rgb=(134, 151, 180), fg_rgb=(200, 30, 30))
    mask = np.full((64, 64), 255, dtype=np.uint8)
    ref_path = tmp_path / "ref.png"
    cand_path = tmp_path / "cand.png"
    mask_path = tmp_path / "mask.png"
    Image.fromarray(ref).save(ref_path)
    Image.fromarray(cand).save(cand_path)
    Image.fromarray(mask, mode="L").save(mask_path)

    cfg = ImageDiffConfig(
        reference_path=ref_path,
        candidate_path=cand_path,
        mask_path=mask_path,
        output_dir=tmp_path,
    )
    result = analyze_image_diff(cfg)
    payload = result.get("bg_normalize")
    assert payload is not None
    assert payload["enabled"] is False
    assert "explicit mask" in payload["reason"]
