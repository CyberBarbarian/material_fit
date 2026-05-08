"""Controlled verification of the E-011 background normaliser.

The question this script answers:

    Given that the user's Unity engine renders onto pure grey
    (71, 71, 71) and their Laya engine renders onto pure
    blue-grey (134, 151, 180), how much fit_score loss does this
    bg colour mismatch alone introduce, and how much of it does
    E-011's preprocessor recover?

We synthesise three "fish-like" foregrounds with controlled material
appearance, composite each onto both engine backgrounds with proper
alpha, and report the metric:

    Q1  identical fg, Unity bg vs Laya bg     (status quo, E-011 OFF)
    Q2  identical fg, Unity bg vs Laya bg     (E-011 ON, target=128 grey)
    Q3  identical fg, Unity bg vs Unity bg    (the unreachable upper
                                                bound — same bg in
                                                both renders)
    Q4  near-identical fg (slight emission
        change), Unity bg vs Laya bg          (E-011 ON, the realistic
                                                "we're optimising and
                                                the materials don't
                                                quite match yet" case)

Compare the fit_scores: Q1 should be the worst, Q3 the best, Q2
should close most of the (Q3 − Q1) gap, and Q4 should remain
sensitive to the actual fg change so the metric still discriminates
between "wrong material" and "right material".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from PIL import Image  # noqa: E402

from tools.material_fit.vision.diff_analysis import (  # noqa: E402
    ImageDiffConfig,
    analyze_image_diff,
)


UNITY_BG = np.array([71, 71, 71], dtype=np.float32)
LAYA_BG = np.array([134, 151, 180], dtype=np.float32)
TARGET_GREY = (128, 128, 128)

H, W = 256, 256


def _make_alpha_disc(cx: float, cy: float, radius: float, softness: float = 1.5) -> np.ndarray:
    """Anti-aliased filled disc — α∈[0,1] at every pixel.

    Soft 1-2 px edge gives realistic silhouette anti-aliasing —
    exactly the source of the E-009 "silhouette artifact" we are
    measuring."""

    yy, xx = np.mgrid[:H, :W].astype(np.float32)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    alpha = np.clip((radius - dist) / softness, 0.0, 1.0)
    return alpha[..., None]  # broadcastable to (H, W, 3)


def _make_fg(seed: int = 0, emission_boost: float = 0.0) -> np.ndarray:
    """A simple "mech with red emission" RGB image."""

    rng = np.random.default_rng(seed)
    base_grey = np.full((H, W, 3), 90, dtype=np.float32)
    # Add some texture variation so the fg is not a flat colour.
    noise = rng.normal(0.0, 8.0, base_grey.shape).astype(np.float32)
    base_grey = np.clip(base_grey + noise, 0.0, 255.0)
    # Emissive red highlight blob in the upper half.
    yy, xx = np.mgrid[:H, :W].astype(np.float32)
    glow = np.exp(-((xx - 130) ** 2 + (yy - 80) ** 2) / (2 * 32 * 32))
    red = np.zeros_like(base_grey)
    red[..., 0] = (200.0 + 40.0 * emission_boost) * glow
    red[..., 1] = (40.0 + 10.0 * emission_boost) * glow
    red[..., 2] = (40.0 + 10.0 * emission_boost) * glow
    fg = np.clip(base_grey + red, 0.0, 255.0)
    return fg


def _composite(fg_rgb: np.ndarray, bg: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Standard linear alpha-compositing: pixel = α·F + (1−α)·B."""

    bg_full = np.broadcast_to(bg, fg_rgb.shape).astype(np.float32)
    out = alpha * fg_rgb.astype(np.float32) + (1.0 - alpha) * bg_full
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def _save_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(image).save(path)


def _run_pair(
    label: str,
    out_dir: Path,
    ref: np.ndarray,
    cand: np.ndarray,
    *,
    e011_enabled: bool,
) -> dict:
    pair_dir = out_dir / label
    pair_dir.mkdir(parents=True, exist_ok=True)
    ref_path = pair_dir / "ref.png"
    cand_path = pair_dir / "cand.png"
    _save_rgb(ref_path, ref)
    _save_rgb(cand_path, cand)
    cfg = ImageDiffConfig(
        reference_path=ref_path,
        candidate_path=cand_path,
        output_dir=pair_dir,
        bg_normalize_enabled=e011_enabled,
        bg_normalize_target=TARGET_GREY,
    )
    return analyze_image_diff(cfg)


def _summary_row(label: str, result: dict) -> str:
    perc = result.get("perceptual") or {}
    fit = result.get("perceptual_fit_score")
    mae = perc.get("weighted_mae")
    ssim = perc.get("ssim")
    bg_norm = result.get("bg_normalize") or {}
    if bg_norm.get("enabled"):
        ref_bg = bg_norm["reference"]["detected_bg"]
        cand_bg = bg_norm["candidate"]["detected_bg"]
        target_bg = bg_norm["reference"]["target_bg"]
        bg_text = f"src→tgt   ref:{ref_bg}->{target_bg}  cand:{cand_bg}->{target_bg}"
    else:
        am = result.get("auto_mask") or {}
        bg_text = (
            "E-011 OFF; auto_mask saw "
            f"ref:{am.get('reference_bg_color')}  cand:{am.get('candidate_bg_color')}"
        )
    return (
        f"{label:38s}  fit={fit:7.4f}  weighted_mae={mae:7.4f}  ssim={ssim:7.4f}"
        f"\n   {bg_text}"
    )


def main() -> None:
    out_dir = REPO / "tools" / "material_fit" / "output" / "_e011_synthetic"
    out_dir.mkdir(parents=True, exist_ok=True)

    fg = _make_fg(seed=0)
    fg_perturbed = _make_fg(seed=0, emission_boost=0.30)  # +30% emission
    alpha = _make_alpha_disc(cx=128, cy=140, radius=80, softness=1.5)

    ref_unity = _composite(fg, UNITY_BG, alpha)
    cand_unity = _composite(fg, UNITY_BG, alpha)  # identical bg, identical fg
    cand_laya = _composite(fg, LAYA_BG, alpha)  # identical fg, different bg
    cand_laya_perturbed = _composite(fg_perturbed, LAYA_BG, alpha)

    print("E-011 verification\n" + "=" * 70)
    print(
        f"Synthetic image: {H}x{W}, anti-aliased disc (α-band ~1.5 px),"
        " emissive red blob inside grey body."
    )
    print(
        f"Engine bg: Unity={UNITY_BG.astype(int).tolist()}  "
        f"Laya={LAYA_BG.astype(int).tolist()}\n"
    )

    # Q1: status quo, E-011 disabled. Worst case.
    q1 = _run_pair("Q1_status_quo_off", out_dir, ref_unity, cand_laya, e011_enabled=False)
    print(_summary_row("Q1 identical fg, mismatched bg [E-011 OFF]", q1))

    # Q2: same image pair, E-011 enabled. Should recover most of the gap.
    q2 = _run_pair("Q2_e011_recovery", out_dir, ref_unity, cand_laya, e011_enabled=True)
    print(_summary_row("Q2 identical fg, mismatched bg [E-011 ON]", q2))

    # Q3: upper bound — both rendered on Unity bg.
    q3 = _run_pair("Q3_unreachable_bound", out_dir, ref_unity, cand_unity, e011_enabled=True)
    print(_summary_row("Q3 identical fg, identical bg [upper bound]", q3))

    # Q4: realistic optimiser case — fg actually differs slightly.
    q4 = _run_pair("Q4_real_optim_step", out_dir, ref_unity, cand_laya_perturbed, e011_enabled=True)
    print(_summary_row("Q4 +30% emission, mismatched bg [E-011 ON]", q4))

    print()
    fit1 = q1.get("perceptual_fit_score") or 0.0
    fit2 = q2.get("perceptual_fit_score") or 0.0
    fit3 = q3.get("perceptual_fit_score") or 0.0
    fit4 = q4.get("perceptual_fit_score") or 0.0

    print("Key findings")
    print("-" * 70)
    print(
        f"  Q3 - Q1  (full bg-mismatch loss without E-011): {fit3 - fit1:+.4f}"
    )
    print(
        f"  Q2 - Q1  (E-011 recovery on identical fg)     : {fit2 - fit1:+.4f}"
    )
    if fit3 > fit1:
        recovery = (fit2 - fit1) / (fit3 - fit1) * 100
        print(
            f"  E-011 closes {recovery:5.1f}% of the bg-mismatch gap"
        )
    print(
        f"  Q2 - Q4  (E-011 still discriminates fg change): {fit2 - fit4:+.4f}"
        " (positive = metric is still sensitive to material drift)"
    )
    print()
    print(f"All artifacts saved under: {out_dir}")


if __name__ == "__main__":
    main()
