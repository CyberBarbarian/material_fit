"""Render a frozen Stage 2 Laya sample and audit it against Unity PNGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from material_fit.assets.stage2_sampling import resolve_stage2_sampling
from material_fit.assets.stage2_unity_references import audit_stage2_unity_references
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.experiments.material_cross_engine_stage2_intake import (
    audit_stage2_candidate,
    write_pair_contact_sheet,
)
from material_fit.laya import lmat_io
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.vision.stage2_registration import apply_frozen_stage2_registration


def run_stage2_capture(
    *,
    repo_root: Path,
    asset_id: str,
    output_dir: Path,
    material_variant: str = "start",
    lighting_variant: str = "baseline",
    node_modules: Path | None = None,
) -> dict[str, Any]:
    spec = resolve_stage2_sampling(
        repo_root,
        asset_id,
        material_variant=material_variant,
        lighting_variant=lighting_variant,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / "stage2_capture_profile.json"
    profile_path.write_text(
        json.dumps(spec.profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raw_render_dir = output_dir / "raw_laya_render"
    raw_render_dir.mkdir(parents=True, exist_ok=True)
    render_dir = output_dir / "laya_render"
    render_dir.mkdir(parents=True, exist_ok=True)
    for view in spec.references.views:
        for directory in (raw_render_dir, render_dir):
            stale_path = directory / view["candidate_file_name"]
            if stale_path.is_file():
                stale_path.unlink()

    material = lmat_io.load_lmat(spec.material_path)
    params = lmat_io.extract_params(material)
    material_patch = material_patch_from_lmat(spec.material_path)
    defines = {
        key: list(value)
        for key, value in dict(material_patch["defines"]).items()
    }
    for name in spec.additional_material_defines:
        for key in ("managed", "enabled"):
            if name not in defines[key]:
                defines[key].append(name)
    views = phase05._profile_views(profile_path)
    driver = phase05._build_artifact_capture_driver(
        profile_path=profile_path,
        output_root=output_dir / "runtime",
        defines=defines,
        render_states=dict(material_patch["render_states"]),
        references=None,
        node_modules=(node_modules or repo_root / "node_modules").resolve(),
    )
    try:
        capture_result = phase05._capture_artifact_set(
            driver=driver,
            artifact_dir=raw_render_dir,
            params=params,
            views=views,
            iteration=0,
        )
    finally:
        driver.close()

    registration = apply_frozen_stage2_registration(
        raw_dir=raw_render_dir,
        output_dir=render_dir,
        views=spec.references.views,
        registration=spec.calibration["registration"],
    )

    reference_audit = audit_stage2_unity_references(spec.references)
    candidate_audit = audit_stage2_candidate(spec.references, render_dir)
    contact_sheet = write_pair_contact_sheet(
        spec.references,
        render_dir,
        output_dir / "unity_laya_eight_views.png",
    )
    report = {
        "contract": "material_fit_stage2_frozen_capture_v1",
        "sampling": spec.manifest(),
        "profile_path": str(profile_path),
        "raw_render_dir": str(raw_render_dir),
        "render_dir": str(render_dir),
        "capture_status": capture_result.get("status"),
        "registration": registration,
        "reference": reference_audit,
        "candidate": candidate_audit,
        "contact_sheet": str(contact_sheet),
    }
    report_path = output_dir / "stage2_capture_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": str(report_path), **report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="turtle")
    parser.add_argument(
        "--material",
        default="start",
        choices=("start", "human-adjusted"),
        help="Material used for the Laya sample; geometry calibration is fixed for both.",
    )
    parser.add_argument(
        "--lighting",
        default="baseline",
        help="Frozen Stage 2 lighting preset; baseline preserves the historical renderer.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--node-modules", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    result = run_stage2_capture(
        repo_root=repo_root,
        asset_id=args.asset,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        material_variant=args.material,
        lighting_variant=args.lighting,
        node_modules=(Path(args.node_modules).expanduser().resolve() if args.node_modules else None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_stage2_capture"]
