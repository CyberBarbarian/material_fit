"""Verification experiments for the E-009 metric (auto-mask +
channel-weighted MAE + SSIM).

Three controlled questions:

1. **Background invariance** — given an identical foreground (model
   pixels), does the metric give nearly the same score regardless
   of background colour? (Goal: yes; this validates auto-mask works.)

2. **Background unification gain** — if the user unifies Unity's
   and Laya's background colour to the same value, how much does
   fit_score improve over the current "both have different bgs"
   setup? (Goal: quantify the residual gain from unification, on
   top of E-009 auto-mask.)

3. **Silhouette anti-aliasing artefact** — at the model's edge,
   pixels alpha-blend with the bg colour, so different bgs cause
   systematic edge differences even when foreground material is
   identical. How much MAE does this contribute, and does
   auto-mask catch it? (Goal: identify the residual confound that
   bg unification eliminates.)

We construct synthetic "fish-like" test images so the experiment
is fully reproducible and doesn't depend on a live Laya editor.
The fish shape is a soft-edged ellipse with simulated highlight
gradient — enough to exercise auto-mask, channel weighting, SSIM,
and silhouette AA effects all at once.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from tools.material_fit.vision.diff_analysis import (  # noqa: E402
    ImageDiffConfig,
    analyze_image_diff,
)


@dataclass
class TestCase:
    """One ref/cand experimental pair."""

    name: str
    ref_path: Path
    cand_path: Path
    description: str


def render_synthetic_fish(
    width: int = 320,
    height: int = 240,
    bg_color: tuple[int, int, int] = (128, 128, 128),
    fish_color: tuple[int, int, int] = (200, 80, 60),
    highlight_color: tuple[int, int, int] = (255, 220, 180),
    centre: tuple[float, float] = (0.5, 0.5),
    scale: tuple[float, float] = (0.32, 0.18),
    highlight_centre: tuple[float, float] = (0.42, 0.35),
    highlight_scale: float = 0.06,
    edge_softness: float = 1.5,
) -> Image.Image:
    """Generate a synthetic fish image: soft-edged ellipse + circular highlight.

    The "fish" is a single ellipse with smoothly anti-aliased edges,
    overlaid with a brighter circular highlight to simulate a specular
    blob. The edges blend with the background colour, which is the
    whole point: if we change ``bg_color`` keeping all foreground
    parameters, the *body of the fish* is identical but the edge
    pixels will systematically differ — that's the silhouette AA
    confound we want to measure.
    """

    cx_pix = centre[0] * width
    cy_pix = centre[1] * height
    sx = scale[0] * width
    sy = scale[1] * height

    hcx_pix = highlight_centre[0] * width
    hcy_pix = highlight_centre[1] * height
    hr = highlight_scale * min(width, height)

    canvas = np.zeros((height, width, 3), dtype=np.float32)
    bg = np.array(bg_color, dtype=np.float32)
    fg = np.array(fish_color, dtype=np.float32)
    hl = np.array(highlight_color, dtype=np.float32)

    canvas[:] = bg

    yy, xx = np.indices((height, width)).astype(np.float32)
    body_d = ((xx - cx_pix) / sx) ** 2 + ((yy - cy_pix) / sy) ** 2 - 1.0
    body_alpha = np.clip(0.5 - body_d * 0.5 / edge_softness, 0.0, 1.0)
    body_alpha = body_alpha[..., None]
    canvas = canvas * (1.0 - body_alpha) + fg * body_alpha

    hl_d = np.sqrt((xx - hcx_pix) ** 2 + (yy - hcy_pix) ** 2) - hr
    hl_alpha = np.clip(0.5 - hl_d * 0.5 / edge_softness, 0.0, 1.0)
    hl_inside = (body_alpha[..., 0] > 0.5) * hl_alpha
    hl_alpha = hl_inside[..., None] * 0.7

    canvas = canvas * (1.0 - hl_alpha) + hl * hl_alpha

    canvas = np.clip(canvas, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB")


def run_pair(case: TestCase) -> dict:
    """Run analyze_image_diff on one (ref, cand) pair and pull the
    headline numbers out of the result."""

    out_dir = case.ref_path.parent / f"_diff_{case.name}"
    res = analyze_image_diff(
        ImageDiffConfig(
            reference_path=str(case.ref_path),
            candidate_path=str(case.cand_path),
            output_dir=str(out_dir),
            generate_diff_image=False,
        )
    )
    perc = res.get("perceptual", {})
    am = res.get("auto_mask") or {}
    return {
        "case": case.name,
        "description": case.description,
        "legacy_mae": res.get("score"),
        "perceptual_fit_score": res.get("perceptual_fit_score"),
        "weighted_mae": perc.get("weighted_mae"),
        "ssim": perc.get("ssim"),
        "fg_ratio": am.get("foreground_ratio"),
        "ref_bg": am.get("reference_bg_color"),
        "cand_bg": am.get("candidate_bg_color"),
    }


def fmt(value, digits=4):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "  --  "
    return f"{value:>{6 + digits}.{digits}f}"


def main() -> None:
    # Output directory under the existing test-image folder so the
    # synthetic PNGs and the diff_analysis sidecar files all stay
    # alongside the real captures and can be compared visually.
    out = REPO_ROOT / "tools/material_fit/output/_e009_verification"
    out.mkdir(parents=True, exist_ok=True)

    # Reference: simulated Unity render. We use the actual Unity
    # corner colour we measured earlier so the experiment is grounded
    # in what really happens.
    UNITY_BG = (172, 160, 146)
    LAYA_BG = (134, 151, 180)
    NEUTRAL_BG = (128, 128, 128)
    FISH_BASE = (200, 80, 60)
    FISH_DARKER = (180, 70, 55)
    FISH_REDDER = (220, 60, 50)
    FISH_BLUER = (180, 80, 110)

    # Render the canonical "Unity reference" once.
    ref = render_synthetic_fish(bg_color=UNITY_BG, fish_color=FISH_BASE)
    ref_path = out / "ref_unity_bg.png"
    ref.save(ref_path)

    # Also render a Unity-like reference but with neutral bg, so we
    # can reuse it as the "post-unification" reference.
    ref_neutral = render_synthetic_fish(bg_color=NEUTRAL_BG, fish_color=FISH_BASE)
    ref_neutral_path = out / "ref_neutral_bg.png"
    ref_neutral.save(ref_neutral_path)

    cases: list[TestCase] = []

    # --- Q1: Background invariance ---
    # Identical foreground (FISH_BASE), candidate has Laya bg vs Unity bg.
    cand_lba = render_synthetic_fish(bg_color=LAYA_BG, fish_color=FISH_BASE)
    cand_lba_path = out / "cand_identical_fish_laya_bg.png"
    cand_lba.save(cand_lba_path)
    cases.append(
        TestCase(
            name="Q1_identical_fish_diff_bg",
            ref_path=ref_path,
            cand_path=cand_lba_path,
            description="ref=Unity bg, cand=Laya bg, foreground IDENTICAL — best-case auto-mask test",
        )
    )

    cand_uba = render_synthetic_fish(bg_color=UNITY_BG, fish_color=FISH_BASE)
    cand_uba_path = out / "cand_identical_fish_unity_bg.png"
    cand_uba.save(cand_uba_path)
    cases.append(
        TestCase(
            name="Q1_identical_fish_same_bg",
            ref_path=ref_path,
            cand_path=cand_uba_path,
            description="ref=Unity bg, cand=Unity bg, foreground IDENTICAL — gold standard, fit≈1",
        )
    )

    # --- Q2: Background unification gain ---
    # Compare two scenarios:
    #   (a) status quo: Unity has Unity bg, Laya has Laya bg, fish slightly off (FISH_DARKER)
    #   (b) unified:    Unity has neutral bg, Laya has neutral bg, fish slightly off
    # Both cases have the SAME foreground difference, so any score
    # difference between them is purely the bg-unification gain.

    cand_status_quo = render_synthetic_fish(bg_color=LAYA_BG, fish_color=FISH_DARKER)
    cand_status_quo_path = out / "cand_offfish_laya_bg.png"
    cand_status_quo.save(cand_status_quo_path)
    cases.append(
        TestCase(
            name="Q2a_status_quo_off_fish",
            ref_path=ref_path,
            cand_path=cand_status_quo_path,
            description="ref=Unity bg, cand=Laya bg, fish slightly off — current production setup",
        )
    )

    cand_unified = render_synthetic_fish(bg_color=NEUTRAL_BG, fish_color=FISH_DARKER)
    cand_unified_path = out / "cand_offfish_neutral_bg.png"
    cand_unified.save(cand_unified_path)
    cases.append(
        TestCase(
            name="Q2b_unified_bg_off_fish",
            ref_path=ref_neutral_path,
            cand_path=cand_unified_path,
            description="ref=neutral bg, cand=neutral bg, SAME fish offset — unification gain test",
        )
    )

    # --- Q3: Various foreground errors, fixed Laya bg ---
    # Calibrate "what fit_score means" for known-magnitude fish errors.
    error_levels = {
        "tiny_off_color":   FISH_DARKER,      # ~5% darker
        "medium_off_color": FISH_REDDER,      # ~10% redder
        "large_off_color":  FISH_BLUER,       # ~30% bluer
    }
    for label, fish_color in error_levels.items():
        c = render_synthetic_fish(bg_color=LAYA_BG, fish_color=fish_color)
        cp = out / f"cand_{label}.png"
        c.save(cp)
        cases.append(
            TestCase(
                name=f"Q3_{label}",
                ref_path=ref_path,
                cand_path=cp,
                description=f"ref=Unity bg, cand=Laya bg, fish color = {fish_color}",
            )
        )

    # --- Q4: 1-pixel positional jitter (no foreground change) ---
    # Render fish offset by 1 px in x — this is exactly the noise
    # we get from window-anchored captures.
    cand_jittered = render_synthetic_fish(
        bg_color=LAYA_BG,
        fish_color=FISH_BASE,
        centre=(0.5 + 1.0 / 320, 0.5),  # 1 px right
    )
    cand_jittered_path = out / "cand_1px_jitter.png"
    cand_jittered.save(cand_jittered_path)
    cases.append(
        TestCase(
            name="Q4_1px_jitter",
            ref_path=ref_path,
            cand_path=cand_jittered_path,
            description="ref=Unity bg, cand=Laya bg + 1 px shift, identical foreground",
        )
    )

    # --- Run everything ---
    rows = [run_pair(case) for case in cases]
    (out / "verify_e009_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- Print human-readable table ---
    print(
        f"{'case':28s}  {'fit_score':>11s}  {'weighted_MAE':>14s}  "
        f"{'SSIM':>8s}  {'fg_ratio':>10s}  {'legacy_MAE':>12s}"
    )
    print("-" * 100)
    for r in rows:
        print(
            f"{r['case']:28s}  "
            f"{fmt(r['perceptual_fit_score']):>11s}  "
            f"{fmt(r['weighted_mae']):>14s}  "
            f"{fmt(r['ssim'], 3):>8s}  "
            f"{fmt(r['fg_ratio'], 3):>10s}  "
            f"{fmt(r['legacy_mae']):>12s}"
        )

    # --- Targeted insights ---
    print()
    print("=" * 100)
    print("KEY FINDINGS")
    print("=" * 100)
    by_name = {r["case"]: r for r in rows}

    # Q1: background invariance
    a = by_name["Q1_identical_fish_diff_bg"]
    b = by_name["Q1_identical_fish_same_bg"]
    print()
    print("Q1: Background invariance (identical foreground, different bg vs same bg)")
    print(f"   different bg fit_score = {a['perceptual_fit_score']:.4f}  weighted_MAE = {a['weighted_mae']:.4f}")
    print(f"   same      bg fit_score = {b['perceptual_fit_score']:.4f}  weighted_MAE = {b['weighted_mae']:.4f}")
    delta_q1 = b["perceptual_fit_score"] - a["perceptual_fit_score"]
    print(f"   gap (purely bg-induced)  = {delta_q1:+.4f}")
    print(f"   ==> if metric were perfectly bg-invariant, gap would be 0.")

    # Q2: bg unification gain
    s = by_name["Q2a_status_quo_off_fish"]
    u = by_name["Q2b_unified_bg_off_fish"]
    print()
    print("Q2: Background-unification gain (same fish offset, status-quo vs unified bg)")
    print(f"   status-quo (different bgs) fit_score = {s['perceptual_fit_score']:.4f}")
    print(f"   unified  (same bg)         fit_score = {u['perceptual_fit_score']:.4f}")
    delta_q2 = u["perceptual_fit_score"] - s["perceptual_fit_score"]
    print(f"   gain from unifying bg                = {delta_q2:+.4f}")
    print(f"   ==> this is what you would gain if you change Unity & Laya to the same bg.")

    # Q3: error magnitude calibration
    print()
    print("Q3: Foreground-error magnitude calibration (current = different bgs)")
    for label in ("tiny_off_color", "medium_off_color", "large_off_color"):
        r = by_name[f"Q3_{label}"]
        print(f"   {label:20s} fit_score = {r['perceptual_fit_score']:.4f}  "
              f"weighted_MAE = {r['weighted_mae']:.4f}  SSIM = {r['ssim']:.3f}")

    # Q4: positional jitter
    j = by_name["Q4_1px_jitter"]
    print()
    print("Q4: 1-pixel jitter (identical foreground, candidate shifted right by 1 px)")
    print(f"   1px-jitter fit_score = {j['perceptual_fit_score']:.4f} (vs identical-fish-diff-bg = {a['perceptual_fit_score']:.4f})")
    delta_q4 = a["perceptual_fit_score"] - j["perceptual_fit_score"]
    print(f"   penalty from 1 px shift = {delta_q4:+.4f}")
    print(f"   ==> SSIM is supposed to absorb this; should be small.")


if __name__ == "__main__":
    main()
