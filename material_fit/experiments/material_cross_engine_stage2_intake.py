"""Audit real Unity references before Stage 2 material optimization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from material_fit.assets.stage2_unity_references import (
    Stage2UnityReferenceSet,
    audit_stage2_unity_references,
    resolve_stage2_unity_references,
)
from material_fit.vision.cross_engine_alignment import score_alignment_pair
from material_fit.vision.cross_engine_score import (
    aggregate_cross_engine_scores_v3,
    score_cross_engine_pair_v3,
)


def audit_stage2_candidate(
    reference_set: Stage2UnityReferenceSet,
    candidate_dir: Path,
) -> dict[str, Any]:
    per_view: list[dict[str, Any]] = []
    material_items: list[dict[str, Any]] = []
    for view in reference_set.views:
        reference_path = reference_set.root / view["reference_file_name"]
        candidate_path = candidate_dir / view["candidate_file_name"]
        if not candidate_path.is_file():
            raise FileNotFoundError(f"missing Laya candidate for {view['view_id']}: {candidate_path}")
        with Image.open(reference_path) as reference, Image.open(candidate_path) as candidate:
            alignment = score_alignment_pair(reference, candidate)
            material = score_cross_engine_pair_v3(reference, candidate)
        per_view.append(
            {
                "view_id": view["view_id"],
                "reference_file_name": view["reference_file_name"],
                "candidate_file_name": view["candidate_file_name"],
                **alignment,
            }
        )
        material_items.append(
            {
                "view_id": view["view_id"],
                "reference_file_name": view["reference_file_name"],
                "candidate_file_name": view["candidate_file_name"],
                **material,
            }
        )
    alignment = _aggregate_alignment(per_view)
    material_score = aggregate_cross_engine_scores_v3(material_items)
    material_score["reference_dir"] = str(reference_set.root)
    material_score["candidate_dir"] = str(candidate_dir)
    return {
        "contract": "material_fit_stage2_unity_laya_preoptimization_gate_v1",
        "asset_id": reference_set.asset_id,
        "reference_dir": str(reference_set.root),
        "candidate_dir": str(candidate_dir),
        "alignment": alignment,
        "material_score": material_score,
        "ready_for_material_optimization": bool(alignment.get("passed")) and material_score.get("status") == "ok",
    }


def write_pair_contact_sheet(
    reference_set: Stage2UnityReferenceSet,
    candidate_dir: Path,
    output_path: Path,
) -> Path:
    cell_width = 450
    cell_height = 350
    label_height = 28
    sheet = Image.new("RGB", (cell_width * 4, (cell_height + label_height) * 4), "#f1f4f8")
    draw = ImageDraw.Draw(sheet)
    for index, view in enumerate(reference_set.views):
        row = index // 2
        pair = index % 2
        paths = (
            ("Unity", reference_set.root / view["reference_file_name"]),
            ("Laya", candidate_dir / view["candidate_file_name"]),
        )
        for role_index, (role, path) in enumerate(paths):
            with Image.open(path) as source:
                rgba = source.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                rendered = Image.alpha_composite(white, rgba).convert("RGB")
                rendered.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
            column = pair * 2 + role_index
            x = column * cell_width + (cell_width - rendered.width) // 2
            y = row * (cell_height + label_height) + (cell_height - rendered.height) // 2
            sheet.paste(rendered, (x, y))
            draw.text((column * cell_width + 8, y + rendered.height + 5), f"{role} | {view['view_id']}", fill="black")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def _aggregate_alignment(per_view: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in per_view if item.get("status") == "ok"]
    if len(valid) != 8:
        return {
            "version": "cross_engine_alignment_v2",
            "status": "invalid",
            "passed": False,
            "view_count": len(per_view),
            "valid_view_count": len(valid),
            "views": per_view,
        }

    def values(name: str) -> list[float]:
        return [float(item[name]) for item in valid]

    ious = values("foreground_iou")
    overlaps = values("foreground_overlap_coefficient")
    centroid_errors = values("centroid_error_norm")
    scale_errors = values("bbox_scale_error")
    trusted_core = values("trusted_core_pixels")
    edge_distances = values("symmetric_edge_distance_px")
    thresholds = {
        "min_foreground_overlap_coefficient": 0.80,
        "max_centroid_error_norm": 0.02,
        "max_bbox_scale_error": 0.15,
        "min_trusted_core_pixels": 1000,
    }
    checks = {
        "foreground_overlap": min(overlaps) >= thresholds["min_foreground_overlap_coefficient"],
        "centroid": max(centroid_errors) <= thresholds["max_centroid_error_norm"],
        "bbox_scale": max(scale_errors) <= thresholds["max_bbox_scale_error"],
        "trusted_core": min(trusted_core) >= thresholds["min_trusted_core_pixels"],
    }
    return {
        "version": "cross_engine_alignment_v2",
        "status": "ok",
        "passed": all(checks.values()),
        "view_count": len(per_view),
        "valid_view_count": len(valid),
        "mean_foreground_iou": float(np.mean(ious)),
        "min_foreground_iou": min(ious),
        "min_foreground_overlap_coefficient": min(overlaps),
        "max_centroid_error_norm": max(centroid_errors),
        "max_bbox_scale_error": max(scale_errors),
        "min_trusted_core_pixels": int(min(trusted_core)),
        "mean_symmetric_edge_distance_px": float(np.mean(edge_distances)),
        "thresholds": thresholds,
        "checks": checks,
        "views": per_view,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, choices=("fish", "turtle", "crocodile", "1503", "1504", "1506"))
    parser.add_argument("--candidate-dir", default="")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_set = resolve_stage2_unity_references(repo_root, args.asset)
    report: dict[str, Any] = {
        "reference": audit_stage2_unity_references(reference_set),
    }
    if args.candidate_dir:
        candidate_dir = Path(args.candidate_dir).expanduser().resolve()
        report["candidate"] = audit_stage2_candidate(reference_set, candidate_dir)
        report["contact_sheet"] = str(
            write_pair_contact_sheet(reference_set, candidate_dir, output_dir / "unity_laya_eight_views.png")
        )
    report_path = output_dir / "stage2_intake_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["audit_stage2_candidate", "write_pair_contact_sheet"]
