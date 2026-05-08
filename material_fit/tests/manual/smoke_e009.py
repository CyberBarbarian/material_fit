"""Smoke-run the new E-009 perceptual scoring end-to-end on the
fish_1580 reference/candidate pair. This is a manual diagnostic
script, not a pytest test.

Usage::

    python -m tools.material_fit.tests.manual.smoke_e009

It is also safe to invoke directly via ``python <path>`` from the
repo root."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.vision.diff_analysis import (  # noqa: E402
    ImageDiffConfig,
    analyze_image_diff,
)


def main() -> None:
    ref = REPO_ROOT / "tools/material_fit/vision/test_image/unity_reference.png"
    cand = REPO_ROOT / "tools/material_fit/vision/test_image/laya_candidate_134.png"
    out_dir = Path(tempfile.mkdtemp(prefix="e009_smoke_"))

    res = analyze_image_diff(
        ImageDiffConfig(
            reference_path=str(ref),
            candidate_path=str(cand),
            output_dir=out_dir,
            generate_diff_image=False,
        )
    )

    print(f"status: {res.get('status')}")
    print(f"legacy_mae (score): {res.get('score', -1):.4f}")
    print(f"perceptual_fit_score: {res.get('perceptual_fit_score', -1):.4f}")
    perc = res["perceptual"]
    print(f"weighted_mae: {perc['weighted_mae']:.4f}")
    print(f"ssim: {(perc['ssim'] or 0):.4f}")
    print(f"ssim_status: {perc['ssim_status']}")
    print(f"mae_branch: {perc['fit_components']['mae_branch']:.4f}")
    print(f"ssim_branch: {perc['fit_components']['ssim_branch']:.4f}")
    am = res["auto_mask"] or {}
    print(f"auto_mask status: {am.get('status')}")
    print(f"  ref_bg: {am.get('reference_bg_color')} ratio: {am.get('reference_bg_ratio', 0):.3f}")
    print(f"  cand_bg: {am.get('candidate_bg_color')} ratio: {am.get('candidate_bg_ratio', 0):.3f}")
    print(f"  foreground_ratio: {am.get('foreground_ratio', 0):.3f}")
    print(f"coverage of channel weights: {perc['coverage']:.3f}")
    print()
    print("per-channel weighted contributions:")
    contribs = sorted(perc["contributions"].items(), key=lambda kv: -kv[1])
    for name, contrib in contribs:
        weight = perc["weights_used"][name]
        print(f"  {name:35s}  contrib={contrib:.4f}  weight={weight:.3f}")


if __name__ == "__main__":
    main()
