"""Validate foreground DISTS across arbitrary Stage 1 evidence cases."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from material_fit.vision.cross_engine_alignment import foreground_mask
from material_fit.vision.dists_score import (
    DISTS_ALIGNED_RGB_METRIC,
    ForegroundDISTSAlignedRGBScorer,
)


PERTURBATIONS = {
    "tiny": (0.99, 0.99, 0.99),
    "mild": (0.82, 0.78, 0.86),
    "strong": (0.58, 0.48, 0.68),
}


def run_stage2_scorer_validation(
    *,
    evidence_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Validate one fixed scorer on every discoverable Stage 1 evidence case."""

    root = evidence_root.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    cases = _discover_cases(root)
    if not cases:
        raise ValueError(
            f"no Stage 1 cases with target_render/start_render/best_render were found under {root}"
        )

    scorer = ForegroundDISTSAlignedRGBScorer()
    case_reports = [
        _score_case(
            case_dir=case_dir,
            output_dir=output,
            scorer=scorer,
        )
        for case_dir in cases
    ]
    checks = {
        "all_same_image_scores_near_one": all(
            case["checks"]["same_image_scores_near_one"] for case in case_reports
        ),
        "all_generic_perturbations_ordered": all(
            case["checks"]["generic_perturbations_ordered"] for case in case_reports
        ),
        "all_recovered_bests_improve_mean_score": all(
            case["checks"]["recovered_best_improves_mean_score"]
            for case in case_reports
        ),
        "all_recovered_bests_win_most_views": all(
            case["checks"]["recovered_best_wins_most_views"]
            for case in case_reports
        ),
    }
    contact_sheet = _write_contact_sheet(
        case_reports,
        output / "stage2_generic_scorer_validation_contact_sheet.png",
    )
    report = {
        "contract": "material_fit_stage2_generic_dists_validation_v1",
        "status": "passed" if all(checks.values()) else "failed",
        "metric": DISTS_ALIGNED_RGB_METRIC,
        "fitted_parameters": 0,
        "asset_specific_score_branches": False,
        "target_color_constants": False,
        "evidence_root": str(root),
        "case_count": len(case_reports),
        "checks": checks,
        "cases": case_reports,
        "contact_sheet": str(contact_sheet),
        "notes": [
            "Cases are discovered from directory structure; case names are labels only.",
            "The same scorer instance, foreground extraction, and perturbation policy are used for every case.",
            "Human or target material parameters are never read by this validation.",
            "Stage 1 target/start/best renders are same-renderer recovery evidence; Unity comparisons remain a separate cross-engine audit.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "stage2_generic_scorer_validation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": str(report_path), **report}


def _discover_cases(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"evidence root does not exist: {root}")
    cases = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        required = [child / name for name in ("target_render", "start_render", "best_render")]
        if all(path.is_dir() for path in required) and (child / "stage1_report.json").is_file():
            cases.append(child)
    return cases


def _score_case(
    *,
    case_dir: Path,
    output_dir: Path,
    scorer: ForegroundDISTSAlignedRGBScorer,
) -> dict[str, Any]:
    target_dir = case_dir / "target_render"
    start_dir = case_dir / "start_render"
    best_dir = case_dir / "best_render"
    file_names = sorted(
        path.name
        for path in target_dir.glob("*.png")
        if (start_dir / path.name).is_file() and (best_dir / path.name).is_file()
    )
    if not file_names:
        raise ValueError(f"case has no common target/start/best PNGs: {case_dir}")

    rows = []
    perturbation_root = output_dir / "perturbations" / case_dir.name
    for file_name in file_names:
        target_path = target_dir / file_name
        start_path = start_dir / file_name
        best_path = best_dir / file_name
        with Image.open(target_path) as source:
            target = source.convert("RGBA")
        scores = {
            "same": scorer.score_image(target_path, target).fit_score,
            "start": scorer.score_paths(target_path, start_path).fit_score,
            "best": scorer.score_paths(target_path, best_path).fit_score,
        }
        perturbation_paths: dict[str, str] = {}
        for name, factors in PERTURBATIONS.items():
            variant = _appearance_variant(target, *factors)
            variant_path = perturbation_root / Path(file_name).stem / f"{name}.png"
            variant_path.parent.mkdir(parents=True, exist_ok=True)
            variant.save(variant_path)
            scores[name] = scorer.score_image(target_path, variant).fit_score
            perturbation_paths[name] = str(variant_path)
        rows.append(
            {
                "view": Path(file_name).stem,
                "target": str(target_path),
                "start": str(start_path),
                "best": str(best_path),
                "scores": scores,
                "perturbations": perturbation_paths,
                "checks": {
                    "same_near_one": scores["same"] >= 0.99999,
                    "perturbations_ordered": (
                        scores["same"] >= scores["tiny"] > scores["mild"] > scores["strong"]
                    ),
                    "best_beats_start": scores["best"] > scores["start"],
                },
            }
        )

    mean_scores = {
        role: statistics.fmean(float(row["scores"][role]) for row in rows)
        for role in ("same", "tiny", "mild", "strong", "start", "best")
    }
    best_win_rate = statistics.fmean(
        1.0 if row["checks"]["best_beats_start"] else 0.0 for row in rows
    )
    checks = {
        "same_image_scores_near_one": all(row["checks"]["same_near_one"] for row in rows),
        "generic_perturbations_ordered": all(
            row["checks"]["perturbations_ordered"] for row in rows
        ),
        "recovered_best_improves_mean_score": mean_scores["best"] > mean_scores["start"],
        "recovered_best_wins_most_views": best_win_rate >= 0.75,
    }
    return {
        "case_id": case_dir.name,
        "case_dir": str(case_dir),
        "view_count": len(rows),
        "mean_scores": mean_scores,
        "best_over_start_mean_margin": mean_scores["best"] - mean_scores["start"],
        "best_over_start_view_win_rate": best_win_rate,
        "checks": checks,
        "rows": rows,
    }


def _appearance_variant(
    image: Image.Image,
    brightness: float,
    saturation: float,
    contrast: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    mask, _ = foreground_mask(rgba)
    values = np.asarray(rgba, dtype=np.float32)[:, :, :3] / 255.0
    luminance = np.sum(
        values * np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32),
        axis=2,
        keepdims=True,
    )
    adjusted = luminance + float(saturation) * (values - luminance)
    adjusted = 0.5 + float(contrast) * (adjusted - 0.5)
    adjusted *= float(brightness)
    output = np.ones_like(values)
    output[mask] = np.clip(adjusted[mask], 0.0, 1.0)
    alpha = np.full((*mask.shape, 1), 255, dtype=np.uint8)
    rgb = np.rint(output * 255.0).astype(np.uint8)
    return Image.fromarray(np.concatenate((rgb, alpha), axis=2))


def _write_contact_sheet(cases: list[dict[str, Any]], output_path: Path) -> Path:
    tile_size = (300, 234)
    label_height = 42
    roles = ("target", "start", "best", "strong")
    sheet = Image.new(
        "RGB",
        (tile_size[0] * len(roles), (tile_size[1] + label_height) * len(cases)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for row_index, case in enumerate(cases):
        row = case["rows"][0]
        paths = {
            "target": Path(row["target"]),
            "start": Path(row["start"]),
            "best": Path(row["best"]),
            "strong": Path(row["perturbations"]["strong"]),
        }
        for column_index, role in enumerate(roles):
            with Image.open(paths[role]) as source:
                image = ImageOps.contain(source.convert("RGB"), tile_size)
            x = column_index * tile_size[0] + (tile_size[0] - image.width) // 2
            y0 = row_index * (tile_size[1] + label_height)
            y = y0 + label_height + (tile_size[1] - image.height) // 2
            sheet.paste(image, (x, y))
            score = 1.0 if role == "target" else float(row["scores"][role])
            draw.text(
                (column_index * tile_size[0] + 6, y0 + 6),
                f"{case['case_id']} | {role} | {score:.6f}",
                fill="black",
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = run_stage2_scorer_validation(
        evidence_root=Path(args.evidence_root),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_stage2_scorer_validation"]
