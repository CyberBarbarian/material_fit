"""Quick standalone probe: run E-009 metric on the user's real Unity/Laya pair.

We have:
  Unity reference  background: (71, 71, 71)   pure neutral grey
  Laya  candidate  background: (134, 151, 180) pure blue-grey sky

Both engines now use a uniform pure colour, but the colours don't match,
so the silhouette anti-aliasing band still leaks bg colour into edge
pixels. This script measures the effect on the current shipping E-009
metric so we know whether a background-normalisation preprocessor is
worth the engineering.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.material_fit.vision.diff_analysis import (  # noqa: E402
    ImageDiffConfig,
    analyze_image_diff,
)


def _show_perceptual(label: str, analysis: dict) -> None:
    perc = analysis.get("perceptual") or {}
    auto_mask = analysis.get("auto_mask") or {}
    print(f"--- {label} ---")
    print(f"  perceptual_fit_score : {analysis.get('perceptual_fit_score')!r}")
    print(f"  weighted_mae         : {perc.get('weighted_mae')!r}")
    print(f"  ssim                 : {perc.get('ssim')!r}")
    print(f"  legacy_score (mae)   : {analysis.get('score')!r}")
    if auto_mask:
        print(f"  auto_mask.fg_ratio   : {auto_mask.get('foreground_ratio')!r}")
        print(f"  auto_mask.ref_bg     : {auto_mask.get('reference_bg_color')!r}")
        print(f"  auto_mask.cand_bg    : {auto_mask.get('candidate_bg_color')!r}")
    print()


def main() -> None:
    test_dir = REPO / "tools" / "material_fit" / "vision" / "test_image"
    out_dir = REPO / "tools" / "material_fit" / "output" / "_e011_diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)

    ref = test_dir / "unity_reference.png"
    cand_files = sorted(p for p in test_dir.glob("laya_candidate_0*.png"))
    if not cand_files:
        cand_files = [test_dir / "laya_candidate.png"]

    for cand in cand_files:
        config = ImageDiffConfig(
            reference_path=ref,
            candidate_path=cand,
            output_dir=out_dir / cand.stem,
        )
        result = analyze_image_diff(config)
        _show_perceptual(cand.name, result)


if __name__ == "__main__":
    main()
