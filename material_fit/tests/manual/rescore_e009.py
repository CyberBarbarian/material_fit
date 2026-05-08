"""Re-score the historical fish_1580 12-iteration trajectory with the
E-009 metric and dump a side-by-side comparison.

This is the data source for the *Metric Comparison* table in
``docs/Metric_Validation.md``. It is intentionally a one-shot
diagnostic; it does not modify any decision.json on disk, only
prints (and saves) a CSV-ish report.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.vision.diff_analysis import (  # noqa: E402
    ImageDiffConfig,
    analyze_image_diff,
)


def main() -> None:
    auto_dir = REPO_ROOT / "tools/material_fit/output/fish_1580/auto_adjust"
    iters = sorted([d for d in auto_dir.glob("iter_*") if d.is_dir()])
    if not iters:
        print("no iterations found at", auto_dir)
        return

    print(
        f"{'iter':>5}  {'legacy_fit':>12}  {'new_fit':>10}  "
        f"{'legacy_mae':>12}  {'weighted_mae':>14}  "
        f"{'ssim':>8}  {'fg_ratio':>10}  stage"
    )
    print("-" * 100)

    rows = []
    for d in iters:
        decision_path = d / "decision.json"
        if not decision_path.exists():
            continue
        try:
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"{d.name}: failed to load decision.json: {exc}")
            continue
        pair = decision.get("input_pair") or {}
        ref_path = pair.get("reference")
        cand_path = pair.get("candidate")
        if not ref_path or not cand_path:
            continue
        if not Path(ref_path).exists() or not Path(cand_path).exists():
            print(f"{d.name}: image missing, skipping")
            continue
        try:
            new_analysis = analyze_image_diff(
                ImageDiffConfig(
                    reference_path=ref_path,
                    candidate_path=cand_path,
                    output_dir=d / "image_analysis_e009",
                    generate_diff_image=False,
                )
            )
        except Exception as exc:
            print(f"{d.name}: analyze failed: {exc}")
            continue

        legacy_fit = decision.get("fit_score_before")
        legacy_mae = decision.get("diff_score_before")
        new_fit = new_analysis.get("perceptual_fit_score")
        weighted_mae = new_analysis["perceptual"]["weighted_mae"]
        ssim_value = new_analysis["perceptual"]["ssim"]
        am = new_analysis.get("auto_mask") or {}
        fg_ratio = am.get("foreground_ratio", 0.0)
        stage = decision.get("selected_stage")

        rows.append(
            {
                "iter": d.name,
                "legacy_fit": legacy_fit,
                "new_fit": new_fit,
                "legacy_mae": legacy_mae,
                "weighted_mae": weighted_mae,
                "ssim": ssim_value,
                "foreground_ratio": fg_ratio,
                "stage": stage,
            }
        )

        def fmt(v, w):
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                return f"{'--':>{w}}"
            return f"{v:>{w}.4f}"

        print(
            f"{d.name[-4:]:>5}  "
            f"{fmt(legacy_fit, 12)}  {fmt(new_fit, 10)}  "
            f"{fmt(legacy_mae, 12)}  {fmt(weighted_mae, 14)}  "
            f"{fmt(ssim_value, 8)}  {fmt(fg_ratio, 10)}  {stage}"
        )

    out_path = auto_dir / "e009_rescore.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
