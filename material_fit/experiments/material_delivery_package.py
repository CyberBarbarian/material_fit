"""Build a validated friend-facing ZIP from a material-fit result."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.laya import lmat_io


REPORT_NAMES = (
    "stage2_v86_report.json",
    "stage2_refine_report.json",
    "stage1_report.json",
)
PARAM_NAMES = (
    "best_params_full_resolution_reranked.json",
    "best_params.json",
    "output/auto_adjust/best/params.json",
)


def build_delivery_package(
    *,
    repo_root: Path,
    asset_id: str,
    output_zip: Path,
    run_dir: Path | None = None,
    material_path: Path | None = None,
    score: float | None = None,
    accepted: bool | None = None,
) -> dict[str, Any]:
    """Package a complete runtime project with one fitted material installed.

    A run-backed package is strict: report, params, every configured best-view
    PNG, and the contact sheet must exist.  A direct-material package is for a
    tracked snapshot and contains the runtime, material, and delivery manifest.
    """

    root = repo_root.expanduser().resolve()
    output = output_zip.expanduser().resolve()
    if output.suffix.lower() != ".zip":
        raise ValueError(f"delivery output must be a .zip: {output}")
    if output.exists():
        raise FileExistsError(f"delivery ZIP already exists: {output}")

    run = run_dir.expanduser().resolve() if run_dir is not None else None
    if run is not None and not run.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run}")

    report_path, report = _load_run_report(run)
    selected_material = _resolve_material(run, report, material_path)
    selected_params = _resolve_optional_run_path(run, report, "best_params_path", PARAM_NAMES)
    snapshot_metadata: dict[str, Any] = {}
    if run is None:
        params_sidecar = selected_material.with_name(
            f"{selected_material.stem}_params.json"
        )
        if selected_params is None and params_sidecar.is_file():
            selected_params = params_sidecar.resolve()
        metadata_sidecar = selected_material.with_suffix(".json")
        if metadata_sidecar.is_file():
            payload = json.loads(metadata_sidecar.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                snapshot_metadata = payload
    best_render_dir = _resolve_optional_run_directory(run, report, "best_render_dir", "best_render")
    contact_sheet = _resolve_contact_sheet(run, report)

    if run is not None:
        missing = []
        if report_path is None:
            missing.append("result report")
        if selected_params is None:
            missing.append("best parameter JSON")
        if best_render_dir is None:
            missing.append("best_render directory")
        if contact_sheet is None:
            missing.append("contact sheet")
        if missing:
            raise FileNotFoundError(
                f"incomplete run-backed delivery ({', '.join(missing)}): {run}"
            )

    asset = resolve_material_asset(root, asset_id)
    material_relative = asset.target_material_path.relative_to(asset.project_root)
    material_sha = _sha256(selected_material)
    resolved_score = (
        float(score)
        if score is not None
        else _optional_float(
            report.get(
                "best_score",
                snapshot_metadata.get("independent_eight_view_score"),
            )
        )
    )
    resolved_accepted = (
        bool(accepted)
        if accepted is not None
        else bool(report.get("accepted", snapshot_metadata.get("accepted", False)))
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="material-fit-delivery-", dir=output.parent) as raw_tmp:
        package_root = Path(raw_tmp) / output.stem
        project_out = package_root / "laya_project"
        shutil.copytree(asset.project_root, project_out)
        installed_material = project_out / material_relative
        shutil.copy2(selected_material, installed_material)

        texture_audit = _audit_texture_bindings(project_out, installed_material)
        if not texture_audit["passed"]:
            raise ValueError(
                "packaged material contains unresolved texture bindings: "
                f"{texture_audit['unresolved_uuids']}"
            )

        shutil.copy2(selected_material, package_root / "best_material.lmat")
        if selected_params is not None:
            shutil.copy2(selected_params, package_root / "best_params.json")
        if report_path is not None:
            shutil.copy2(report_path, package_root / "result_report.json")

        review_files: list[str] = []
        if best_render_dir is not None:
            review_dir = package_root / "review" / "best_render"
            review_dir.mkdir(parents=True, exist_ok=True)
            expected_names = [
                str(view["file_name"])
                for view in asset.profile["capture_defaults"]["views"]
            ]
            missing_views = [
                name for name in expected_names if not (best_render_dir / name).is_file()
            ]
            if missing_views:
                raise FileNotFoundError(
                    f"best_render is missing configured views: {missing_views}"
                )
            for name in expected_names:
                shutil.copy2(best_render_dir / name, review_dir / name)
                review_files.append(f"review/best_render/{name}")
        if contact_sheet is not None:
            contact_name = contact_sheet.name
            contact_out = package_root / "review" / contact_name
            contact_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contact_sheet, contact_out)
            review_files.append(f"review/{contact_name}")

        delivery_manifest = {
            "contract": "material_fit_delivery_package_v1",
            "asset_id": asset.asset_id,
            "accepted": resolved_accepted,
            "score": resolved_score,
            "source_run": str(run) if run is not None else None,
            "source_material": str(selected_material),
            "installed_material": f"laya_project/{material_relative.as_posix()}",
            "material_sha256": material_sha,
            "params_sha256": (
                _sha256(selected_params) if selected_params is not None else None
            ),
            "texture_audit": texture_audit,
            "scene": f"laya_project/{asset.scene_path.relative_to(asset.project_root).as_posix()}",
            "shader": f"laya_project/{asset.shader_path.relative_to(asset.project_root).as_posix()}",
            "width": int(asset.profile["width"]),
            "height": int(asset.profile["height"]),
            "view_count": len(asset.profile["capture_defaults"]["views"]),
            "review_files": review_files,
        }
        _write_json(package_root / "DELIVERY_MANIFEST.json", delivery_manifest)
        _update_project_manifest(project_out, material_sha, resolved_score, resolved_accepted)
        (package_root / "README.md").write_text(
            _delivery_readme(delivery_manifest),
            encoding="utf-8",
        )
        _write_zip(package_root, output)

    with zipfile.ZipFile(output) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"corrupt delivery ZIP entry: {corrupt}")
        entry_count = len(archive.infolist())

    return {
        "contract": "material_fit_delivery_package_result_v1",
        "output_zip": str(output),
        "zip_sha256": _sha256(output),
        "zip_bytes": output.stat().st_size,
        "entry_count": entry_count,
        "material_sha256": material_sha,
        "texture_binding_count": texture_audit["binding_count"],
        "accepted": resolved_accepted,
        "score": resolved_score,
    }


def _load_run_report(run_dir: Path | None) -> tuple[Path | None, dict[str, Any]]:
    if run_dir is None:
        return None, {}
    for name in REPORT_NAMES:
        path = run_dir / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError(f"result report must be a JSON object: {path}")
            return path, payload
    return None, {}


def _resolve_material(
    run_dir: Path | None,
    report: dict[str, Any],
    material_path: Path | None,
) -> Path:
    if material_path is not None:
        selected = material_path.expanduser().resolve()
    elif run_dir is not None and (run_dir / "best_material.lmat").is_file():
        selected = (run_dir / "best_material.lmat").resolve()
    else:
        raw = report.get("best_material_path")
        selected = Path(str(raw)).expanduser().resolve() if raw else Path()
    if not selected.is_file():
        raise FileNotFoundError(f"best material does not exist: {selected}")
    return selected


def _resolve_optional_run_path(
    run_dir: Path | None,
    report: dict[str, Any],
    report_key: str,
    relative_names: tuple[str, ...],
) -> Path | None:
    if run_dir is None:
        return None
    for name in relative_names:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate.resolve()
    raw = report.get(report_key)
    candidate = Path(str(raw)).expanduser().resolve() if raw else None
    return candidate if candidate is not None and candidate.is_file() else None


def _resolve_optional_run_directory(
    run_dir: Path | None,
    report: dict[str, Any],
    report_key: str,
    relative_name: str,
) -> Path | None:
    if run_dir is None:
        return None
    local = run_dir / relative_name
    if local.is_dir():
        return local.resolve()
    raw = report.get(report_key)
    candidate = Path(str(raw)).expanduser().resolve() if raw else None
    return candidate if candidate is not None and candidate.is_dir() else None


def _resolve_contact_sheet(run_dir: Path | None, report: dict[str, Any]) -> Path | None:
    if run_dir is None:
        return None
    raw = report.get("contact_sheet")
    if raw:
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        if candidate.is_file():
            return candidate.resolve()
    local = sorted(run_dir.glob("*contact*.png")) + sorted(run_dir.glob("unity_*.png"))
    return local[0].resolve() if local else None


def _audit_texture_bindings(project_root: Path, material_path: Path) -> dict[str, Any]:
    meta_uuids: set[str] = set()
    for meta_path in project_root.rglob("*.meta"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        uuid = payload.get("uuid") if isinstance(payload, dict) else None
        if isinstance(uuid, str) and uuid:
            meta_uuids.add(uuid)

    bindings = lmat_io.extract_textures(lmat_io.load_lmat(material_path))
    required = [
        str(binding["path"])[len("res://") :]
        for binding in bindings
        if str(binding.get("path", "")).startswith("res://")
    ]
    unresolved = sorted(uuid for uuid in required if uuid not in meta_uuids)
    return {
        "passed": not unresolved,
        "binding_count": len(bindings),
        "required_uuids": sorted(required),
        "unresolved_uuids": unresolved,
    }


def _update_project_manifest(
    project_root: Path,
    material_sha: str,
    score: float | None,
    accepted: bool,
) -> None:
    path = project_root / "MINIMAL_PROJECT_MANIFEST.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    payload["name"] = f"{payload.get('name', 'material_fit')}_delivery"
    payload["purpose"] = "Runtime project with the packaged fitted material installed."
    appearance = payload.setdefault("appearance_contract", {})
    appearance["material_sha256"] = material_sha
    appearance["delivered_score"] = score
    appearance["accepted"] = accepted
    _write_json(path, payload)


def _delivery_readme(manifest: dict[str, Any]) -> str:
    score = manifest["score"]
    score_text = "unknown" if score is None else f"{float(score):.10f}"
    return (
        "# Material Fit delivery\n\n"
        f"- Asset: `{manifest['asset_id']}`\n"
        f"- Score: `{score_text}`\n"
        f"- Accepted: `{str(bool(manifest['accepted'])).lower()}`\n"
        f"- Installed material: `{manifest['installed_material']}`\n"
        f"- Scene: `{manifest['scene']}`\n"
        f"- Shader: `{manifest['shader']}`\n"
        f"- Capture: `{manifest['width']}x{manifest['height']}`, "
        f"{manifest['view_count']} view(s)\n\n"
        "The fitted material is already installed inside `laya_project/`. "
        "Texture UUID bindings were resolved before the ZIP was written. "
        "See `DELIVERY_MANIFEST.json` for hashes and audit details.\n"
    )


def _write_zip(package_root: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, Path(package_root.name) / path.relative_to(package_root))


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="1613")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--material", default="")
    parser.add_argument("--score", type=float)
    parser.add_argument("--accepted", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    result = build_delivery_package(
        repo_root=repo_root,
        asset_id=args.asset,
        output_zip=Path(args.output),
        run_dir=Path(args.run_dir) if args.run_dir else None,
        material_path=Path(args.material) if args.material else None,
        score=args.score,
        accepted=args.accepted,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_delivery_package"]
