"""Pure-colour background normalisation (Experiment E-011).

Why this module exists
======================

E-009 introduced a perceptual scoring system that auto-masks each
engine's editor/sky background before computing the weighted MAE and
SSIM. That works *correctly* when both engines render onto the same
background colour. In the user's actual setup (2026-05-07) Unity
renders the model onto neutral grey ``(71, 71, 71)`` while Laya
renders onto a blue-grey sky ``(134, 151, 180)`` — pure colours, but
*different* pure colours.

`auto_background_mask` will detect both backgrounds correctly and
exclude their pixels from the diff. **But the foreground silhouette
band still leaks engine-specific bg colour into fully-foreground
pixels** because of alpha-compositing at edges:

    edge_pixel ≈ α · material + (1 − α) · engine_bg_colour

Even with the same material, edge pixels diverge between Unity and
Laya by up to ``(1 − α) · |engine_bg_unity − engine_bg_laya|`` —
which on this scene means up to ``0.5 · 80 ≈ 40`` per channel for
α≈0.5 edge pixels. E-009's synthetic verification (`verify_e009.py`)
quantified this drop at ≈0.29 fit_score on identical foregrounds
with mismatched backgrounds.

The cleanest fix the user could apply (re-render with the same bg
colour in both engines) is what we recommended in E-009 §5.5. They
have unified each engine's bg to a *pure* colour but not to the
*same* pure colour. This module bridges that gap with a
post-rendering preprocessing step.

Algorithm
---------

For each image:

1. Sample a 4-corner median (same detector as
   :func:`vision.perceptual_score.auto_background_mask`) to recover
   the engine-specific bg colour.
2. Compute each pixel's L2 colour distance ``d`` to that bg.
3. Build a soft foreground-likeness ``α_fg`` ∈ [0, 1] via a linear
   ramp::

        α_fg = clip((d − soft_low) / (soft_high − soft_low), 0, 1)

   Pixels with ``d ≤ soft_low`` → ``α_fg = 0`` → *fully* substituted.
   Pixels with ``d ≥ soft_high`` → ``α_fg = 1`` → *unchanged*.
   In between → smooth blend.
4. Re-compose under the alpha-compositing model
   ``pixel = α · F + (1 − α) · bg`` to swap ``bg`` for ``target_bg``::

        new_pixel = pixel + (1 − α_fg) · (target_bg − bg)

   * Pure bg (``α_fg = 0``): ``new = bg + (target_bg − bg) = target_bg`` ✓
   * Pure foreground (``α_fg = 1``): ``new = pixel`` ✓
   * Edge (``α_fg = 0.5``): ``new = pixel + 0.5 · (target_bg − bg)``
     — half-replaces the bg contribution, leaving foreground untouched.

What this *does* fix
--------------------

* **Pure bg pixels** become identical between engines (all become
  ``target_bg``), eliminating any leakage through later metric
  stages where the auto-mask is loose.
* **Edge "halo" pixels** in the soft-zone (typical 1-2 px wide ring
  around silhouette) get partially corrected — magnitude scales
  linearly with how close the pixel is to bg.

What this *does not* fix
------------------------

* **Strong-foreground edge pixels** with ``d > soft_high`` are
  treated as 100% foreground and left untouched. For these the
  ``(1 − α_true) · engine_bg_colour`` contamination remains. There
  is no closed-form way to recover the unmixed material colour
  from a single pixel without a known foreground prior. See
  ``Metric_Validation.md`` §5.5 for why this is fundamentally
  underdetermined and what tier-2 / tier-3 work could close the
  gap (alpha matting, ECC alignment).

Tunability
----------

The user said: *"如果后面再更换了背景色，这个预处理你稍微修改一下即可"*.
So we expose:

* ``target_bg`` — final unified colour. Default ``(128, 128, 128)`` is
  the neutral grey we recommend; on a future bg change the only knob
  the user needs to touch is this, *or* per-image overrides via
  ``source_bg_*``.
* ``soft_low`` / ``soft_high`` — width of the transition zone.
  Default ``(8, 32)`` is calibrated so that the typical 1-2 px edge
  band is partially corrected without ever touching saturated
  foreground material.

This module is deliberately framework-free: it takes ``np.ndarray`` in,
returns ``np.ndarray`` out. The integration with ``diff_analysis`` is
a one-liner there, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# --------------------------------------------------------------------
# Config / result dataclasses


@dataclass(frozen=True)
class BackgroundNormalizeConfig:
    """User-tunable knobs for the bg normalisation step."""

    enabled: bool = True
    """Master kill switch — when False the input image is returned
    untouched. Useful for ablation experiments and as an escape hatch
    when the bg detector misfires (e.g. on screenshots where the corner
    pixels happen to be pure black UI chrome rather than render bg)."""

    target_bg: tuple[int, int, int] = (128, 128, 128)
    """The unified background colour both engines' captures will be
    re-composed onto. Choose a colour that is *least likely* to overlap
    with foreground material colours in either engine — neutral grey
    works for most fish/mech materials. Change this if you also change
    the actual rendered bg colour in either engine."""

    soft_low: float = 2.0
    """Below this L2 distance to the source bg the pixel is treated as
    100% bg → fully substituted with ``target_bg``. Default 2 catches
    just the pure-colour bg + tiny dithering noise (~1 LSB per
    channel). DO NOT raise without re-running ``verify_e011.py`` —
    the synthetic experiment showed that any threshold > 8 starts
    introducing **asymmetric** corrections at edge pixels (Unity-grey
    edges are intrinsically closer to bg than Laya-sky edges, so the
    preprocessor activates on one engine and not the other), and
    that even a very narrow ramp can re-classify just-barely-bg
    pixels as foreground in the downstream auto-mask, *adding* error
    instead of removing it."""

    soft_high: float = 4.0
    """Above this L2 distance the pixel is treated as 100% foreground
    → completely unchanged. Defaults form an extremely narrow ramp
    ``[2, 4]`` that only touches pixels we're > 99.9% sure are pure
    background, and never crosses the auto-mask threshold (L∞ = 16
    ≈ L2 = 27 worst case) used by
    :func:`vision.diff_analysis.analyze_image_diff` — so the
    substitution never moves a pixel from "bg" to "fg" in the
    downstream mask logic."""

    corner_size: int = 12
    """Sample patch size used by the 4-corner median bg detector
    (matches ``AutoMaskConfig.corner_size`` for symmetry). When the
    image is < 24 px on any axis the patch shrinks automatically."""


@dataclass
class NormalizeResult:
    """What the preprocessor saw and did, for forensics."""

    image: np.ndarray
    """The output image, dtype uint8, same shape as input."""

    detected_bg: tuple[int, int, int]
    """The bg colour the corner detector returned. Compare to
    ``target_bg`` to see how much shifting was applied."""

    target_bg: tuple[int, int, int]
    """Echoed for convenience so callers can write a single payload."""

    soft_low: float
    soft_high: float

    n_pixels_pure_bg: int
    """Pixels with L2 distance ≤ ``soft_low`` (treated as 100% bg)."""

    n_pixels_soft_zone: int
    """Pixels in ``(soft_low, soft_high)`` (partially blended)."""

    n_pixels_pure_fg: int
    """Pixels with L2 distance ≥ ``soft_high`` (left untouched)."""

    @property
    def coverage(self) -> dict[str, float]:
        """Fractions of the image in each bucket — useful for sanity
        checks ("did the bg detector actually find ≥50% bg as
        expected?")."""

        total = max(
            1,
            self.n_pixels_pure_bg + self.n_pixels_soft_zone + self.n_pixels_pure_fg,
        )
        return {
            "pure_bg": self.n_pixels_pure_bg / total,
            "soft_zone": self.n_pixels_soft_zone / total,
            "pure_fg": self.n_pixels_pure_fg / total,
        }

    def as_dict(self) -> dict[str, object]:
        """JSON-friendly summary for ``decision.json``-style logs."""

        return {
            "detected_bg": list(self.detected_bg),
            "target_bg": list(self.target_bg),
            "soft_low": self.soft_low,
            "soft_high": self.soft_high,
            "n_pixels_pure_bg": self.n_pixels_pure_bg,
            "n_pixels_soft_zone": self.n_pixels_soft_zone,
            "n_pixels_pure_fg": self.n_pixels_pure_fg,
            "coverage": self.coverage,
        }


# --------------------------------------------------------------------
# Bg detector — kept simple and identical in spirit to
# ``perceptual_score.auto_background_mask`` so we always see the same
# "bg colour" the mask later sees.


def detect_corner_background(
    image: np.ndarray,
    *,
    corner_size: int = 12,
) -> np.ndarray:
    """Return the 4-corner median colour as an ``np.float32`` of shape ``(3,)``.

    The median is robust to compression noise / 1-2 px UI artefacts in
    the corners (e.g. Laya's tiny gizmo cross). For pure-colour bgs the
    median collapses to the exact colour, which is what we want.
    """

    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError(
            "detect_corner_background expects an HxWx3+ RGB-like image; "
            f"got shape {image.shape!r}"
        )
    arr = image[..., :3].astype(np.float32)
    h, w = arr.shape[:2]
    cs = max(1, min(int(corner_size), h // 2, w // 2))
    corners = np.concatenate(
        [
            arr[:cs, :cs].reshape(-1, 3),
            arr[:cs, -cs:].reshape(-1, 3),
            arr[-cs:, :cs].reshape(-1, 3),
            arr[-cs:, -cs:].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(corners, axis=0)


# --------------------------------------------------------------------
# Main entry point


def normalize_background(
    image: np.ndarray,
    config: BackgroundNormalizeConfig | None = None,
    *,
    source_bg_override: Sequence[float] | None = None,
) -> NormalizeResult:
    """Re-compose ``image`` so its detected pure-colour bg becomes
    ``config.target_bg`` while leaving foreground untouched.

    Parameters
    ----------
    image
        ``np.ndarray`` of shape ``(H, W, 3)`` or ``(H, W, 4)``,
        dtype ``uint8`` or compatible. Alpha (if any) is dropped from
        the comparison but copied through to the output.
    config
        :class:`BackgroundNormalizeConfig` instance. Defaults to a
        ready-to-ship config with neutral-grey target.
    source_bg_override
        If given, skips the corner detector and uses this colour as
        the source bg. Useful in tests and for "I know my engine
        screenshot doesn't have clean corners" cases.

    Returns
    -------
    :class:`NormalizeResult` whose ``.image`` field holds the
    re-composed image (ready to feed into ``analyze_image_diff``)
    and whose remaining fields summarise what the detector saw.
    """

    config = config or BackgroundNormalizeConfig()

    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(
            "normalize_background expects an HxWx3 or HxWx4 image; "
            f"got shape {image.shape!r}"
        )

    rgb = image[..., :3]
    src_dtype = image.dtype

    if source_bg_override is not None:
        src_bg = np.asarray(source_bg_override, dtype=np.float32).reshape(3)
    else:
        src_bg = detect_corner_background(rgb, corner_size=config.corner_size)

    target_bg_arr = np.asarray(config.target_bg, dtype=np.float32).reshape(3)

    # Distance from each pixel to source bg (L2).
    diff = rgb.astype(np.float32) - src_bg
    dist = np.sqrt((diff * diff).sum(axis=-1, keepdims=True))

    # Soft foreground likeness ∈ [0, 1].
    span = max(1e-6, float(config.soft_high - config.soft_low))
    if config.soft_high <= config.soft_low:
        # Degenerate ramp → fall back to a hard step at soft_low.
        alpha_fg = (dist > config.soft_low).astype(np.float32)
    else:
        alpha_fg = np.clip(
            (dist - float(config.soft_low)) / span,
            0.0,
            1.0,
        )

    # Re-compose: new = pixel + (1 − α_fg) · (target_bg − src_bg).
    # This is the unique linear formula that:
    #   * lands on target_bg when α_fg → 0 (pure bg pixel),
    #   * lands on the original pixel when α_fg → 1 (pure foreground),
    #   * blends smoothly in between.
    delta = target_bg_arr - src_bg
    if config.enabled:
        new_rgb = rgb.astype(np.float32) + (1.0 - alpha_fg) * delta
        new_rgb = np.clip(new_rgb, 0.0, 255.0)
    else:
        new_rgb = rgb.astype(np.float32)

    # Forensic counters — use L2 distance buckets matching the ramp.
    pure_bg_mask = (dist <= float(config.soft_low)).reshape(-1)
    pure_fg_mask = (dist >= float(config.soft_high)).reshape(-1)
    n_pure_bg = int(pure_bg_mask.sum())
    n_pure_fg = int(pure_fg_mask.sum())
    n_total = int(rgb.shape[0] * rgb.shape[1])
    n_soft = max(0, n_total - n_pure_bg - n_pure_fg)

    if image.shape[2] == 4:
        out = np.concatenate([new_rgb, image[..., 3:].astype(np.float32)], axis=-1)
    else:
        out = new_rgb
    out = out.astype(src_dtype, copy=False)

    return NormalizeResult(
        image=out,
        detected_bg=tuple(int(round(float(v))) for v in src_bg),
        target_bg=tuple(int(round(float(v))) for v in target_bg_arr),
        soft_low=float(config.soft_low),
        soft_high=float(config.soft_high),
        n_pixels_pure_bg=n_pure_bg,
        n_pixels_soft_zone=n_soft,
        n_pixels_pure_fg=n_pure_fg,
    )


# --------------------------------------------------------------------
# Convenience wrapper for callers that want a (ref, cand) tuple


def normalize_pair(
    reference: np.ndarray,
    candidate: np.ndarray,
    config: BackgroundNormalizeConfig | None = None,
) -> tuple[NormalizeResult, NormalizeResult]:
    """Apply :func:`normalize_background` to both images independently.

    Each image's bg is detected and re-composed *separately* — this
    is what makes the metric background-colour-invariant: the
    reference's bg becomes ``target_bg``, the candidate's bg also
    becomes ``target_bg``, so any subsequent pixel-comparison stage
    sees a consistent neutral surround in both inputs.
    """

    config = config or BackgroundNormalizeConfig()
    return (
        normalize_background(reference, config),
        normalize_background(candidate, config),
    )


__all__ = [
    "BackgroundNormalizeConfig",
    "NormalizeResult",
    "detect_corner_background",
    "normalize_background",
    "normalize_pair",
]
