"""Canonical fish scene assets used by core material-fit experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SOURCE_ARCHIVE_DIR = Path("artifacts/source_archives/20260612_original_fish_inputs")
EXTRACT_ROOT = Path("artifacts/original_zip_probe_20260612")

LAYA_ZIP_NAME = "laya_project_minimal(3).zip"
UNITY_ZIP_NAME = "unity_references(1).zip"

EXPECTED_LAYA_ZIP_SHA256 = "ae61165ab727acd66f4ac6bd0448af437a3cab46412ec4c38f14ff1f9a1d740d"
EXPECTED_UNITY_ZIP_SHA256 = "b1afb643185a5dbee67e590c517af8edbcc54ad87d98f894ecd7bfa66bd6968f"
EXPECTED_SOURCE_SCENE_SHA256 = "fe99a133da3088d45ca4ec2f1077e72d067409ee3703269695ee554cbefbc602"
EXPECTED_BASELINE_MATERIAL_SHA256 = "9521e1e1671dffdfcc67c07e4dd95314155bf7ed541768ce0ca7e158c0a1f7d3"
EXPECTED_SOURCE_MATERIAL_SHA256 = EXPECTED_BASELINE_MATERIAL_SHA256
EXPECTED_SHADER_SHA256 = "c4a71f3ca946304e93986d7f4b04d18e4cb45f14f57ad0a50ec3082c2ea56946"

CANONICAL_ASSET_SET_NAME = "fish_1504_original_zip_20260612"
ZERO_ASSET_SET_NAME = "fish_1504_zero_searchable_from_original_zip_20260612"
FINETUNE_ASSET_SET_NAME = "fish_1504_default_finetune_from_original_zip_20260612"
SOURCE_SCENE_MATERIAL_UUID = "4adc3c2d-41bc-4cad-87df-77ecfb84a558"
BASELINE_MATERIAL_NAME = "fish_jxs_test.lmat"
SOURCE_SCENE_MATERIAL_NAME = BASELINE_MATERIAL_NAME

CORE_VIEW_IDS = (
    "v000_yaw0_pitch0",
    "v001_yaw45_pitch0",
    "v002_yaw90_pitch0",
    "v003_yaw135_pitch0",
    "v004_yaw180_pitch0",
    "v005_yaw225_pitch0",
    "v006_yaw270_pitch0",
    "v007_yaw315_pitch0",
)


@dataclass(frozen=True)
class FishSceneAssets:
    """Resolved canonical fish asset paths."""

    asset_set_name: str
    repo_root: Path
    source_archive_dir: Path
    laya_zip: Path
    unity_zip: Path
    extract_root: Path
    source_laya_project_dir: Path
    source_scene_path: Path
    laya_project_dir: Path
    unity_reference_dir: Path
    scene_path: Path
    baseline_material_path: Path
    source_material_path: Path
    shader_path: Path
    scene_material_uuid: str
    source_scene_material_uuid: str
    baseline_material_name: str
    source_scene_material_name: str

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


def resolve_fish_scene_assets(repo_root: Path, *, extract: bool = True, verify_hashes: bool = True) -> FishSceneAssets:
    """Resolve and validate the original fish scene from the source zip archives."""

    repo_root = repo_root.resolve()
    source_archive_dir = repo_root / SOURCE_ARCHIVE_DIR
    laya_zip = source_archive_dir / LAYA_ZIP_NAME
    unity_zip = source_archive_dir / UNITY_ZIP_NAME
    extract_root = repo_root / EXTRACT_ROOT
    source_laya_project_dir = extract_root / "laya_project_zip" / "laya_project_minimal"
    laya_project_dir = source_laya_project_dir
    unity_reference_dir = extract_root / "unity_references_zip" / "unity_references"

    if extract:
        _extract_if_needed(laya_zip, extract_root / "laya_project_zip")
        _extract_if_needed(unity_zip, extract_root / "unity_references_zip")

    source_scene_path = source_laya_project_dir / "assets/resources/game.ls"
    scene_path = source_scene_path
    baseline_material_path = source_laya_project_dir / f"assets/resources/model/1504/mat/{BASELINE_MATERIAL_NAME}"
    source_material_path = source_laya_project_dir / f"assets/resources/model/1504/mat/{SOURCE_SCENE_MATERIAL_NAME}"
    shader_path = source_laya_project_dir / "assets/resources/shader/Custom_low.shader"
    required = [
        laya_zip,
        unity_zip,
        source_laya_project_dir,
        laya_project_dir,
        unity_reference_dir,
        source_scene_path,
        scene_path,
        baseline_material_path,
        source_material_path,
        shader_path,
        *[unity_reference_dir / f"laya_{view_id}.png" for view_id in CORE_VIEW_IDS],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "missing canonical fish scene assets. Put the original zip files under "
            f"{source_archive_dir} and rerun.\n" + "\n".join(missing)
        )

    if verify_hashes:
        _require_sha256(laya_zip, EXPECTED_LAYA_ZIP_SHA256)
        _require_sha256(unity_zip, EXPECTED_UNITY_ZIP_SHA256)
        _require_sha256(source_scene_path, EXPECTED_SOURCE_SCENE_SHA256)
        _require_sha256(baseline_material_path, EXPECTED_BASELINE_MATERIAL_SHA256)
        _require_sha256(source_material_path, EXPECTED_SOURCE_MATERIAL_SHA256)
        _require_sha256(shader_path, EXPECTED_SHADER_SHA256)

    source_scene_text = source_scene_path.read_text(encoding="utf-8-sig", errors="replace")
    if SOURCE_SCENE_MATERIAL_UUID not in source_scene_text:
        raise RuntimeError(
            f"source fish scene does not bind expected source material uuid {SOURCE_SCENE_MATERIAL_UUID}: "
            f"{source_scene_path}"
        )

    return FishSceneAssets(
        asset_set_name=CANONICAL_ASSET_SET_NAME,
        repo_root=repo_root,
        source_archive_dir=source_archive_dir,
        laya_zip=laya_zip,
        unity_zip=unity_zip,
        extract_root=extract_root,
        source_laya_project_dir=source_laya_project_dir,
        source_scene_path=source_scene_path,
        laya_project_dir=laya_project_dir,
        unity_reference_dir=unity_reference_dir,
        scene_path=scene_path,
        baseline_material_path=baseline_material_path,
        source_material_path=source_material_path,
        shader_path=shader_path,
        scene_material_uuid=SOURCE_SCENE_MATERIAL_UUID,
        source_scene_material_uuid=SOURCE_SCENE_MATERIAL_UUID,
        baseline_material_name=BASELINE_MATERIAL_NAME,
        source_scene_material_name=SOURCE_SCENE_MATERIAL_NAME,
    )


def _extract_if_needed(zip_path: Path, output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        return
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(output_dir)


def _require_sha256(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(f"sha256 mismatch for {path}: expected {expected}, got {actual}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the canonical fish source archives and scene.")
    parser.add_argument("--repo-root", default=".", help="Repository root; defaults to current directory.")
    parser.add_argument("--no-extract", action="store_true", help="Validate existing extraction only.")
    parser.add_argument("--no-hash", action="store_true", help="Skip sha256 checks.")
    args = parser.parse_args(argv)
    assets = resolve_fish_scene_assets(
        Path(args.repo_root),
        extract=not bool(args.no_extract),
        verify_hashes=not bool(args.no_hash),
    )
    print(json.dumps(assets.to_json_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
