from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.experiments.material_delivery_package import build_delivery_package
from material_fit.laya import lmat_io


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_BEST = (
    REPO_ROOT
    / "material_fit/assets/material_starts/1613/experimental_best_20260723.lmat"
)


def test_tracked_1613_best_is_explicitly_unaccepted_and_preserves_texture() -> None:
    metadata = json.loads(
        TRACKED_BEST.with_suffix(".json").read_text(encoding="utf-8")
    )
    textures = lmat_io.extract_textures(lmat_io.load_lmat(TRACKED_BEST))

    assert metadata["accepted"] is False
    assert metadata["independent_eight_view_score"] == pytest.approx(
        0.8795882290878261
    )
    assert hashlib.sha256(TRACKED_BEST.read_bytes()).hexdigest() == metadata[
        "material_sha256"
    ]
    assert textures[0]["path"] == "res://f2d112e5-1b94-40ee-9eb0-2a199fe25b15"


def test_direct_material_delivery_contains_complete_runtime(tmp_path: Path) -> None:
    output = tmp_path / "1613-direct.zip"
    result = build_delivery_package(
        repo_root=REPO_ROOT,
        asset_id="1613",
        output_zip=output,
        material_path=TRACKED_BEST,
        score=0.8841877893703689,
        accepted=False,
    )

    assert result["texture_binding_count"] == 1
    assert result["accepted"] is False
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        prefix = "1613-direct/"
        assert prefix + "best_material.lmat" in names
        assert prefix + "best_params.json" in names
        assert prefix + "DELIVERY_MANIFEST.json" in names
        assert (
            prefix
            + "laya_project/assets/resources/model/1613/prefab/1613.lh"
            in names
        )
        installed_name = (
            prefix
            + "laya_project/assets/resources/model/1613/mat/"
            "fish_1543_shengdanlaoren_laya_diff.lmat"
        )
        assert archive.read(installed_name) == TRACKED_BEST.read_bytes()
        manifest = json.loads(
            archive.read(prefix + "DELIVERY_MANIFEST.json").decode("utf-8")
        )
        assert manifest["texture_audit"]["passed"] is True
        assert manifest["view_count"] == 8
        assert manifest["params_sha256"] == hashlib.sha256(
            TRACKED_BEST.with_name(
                f"{TRACKED_BEST.stem}_params.json"
            ).read_bytes()
        ).hexdigest()


def test_run_backed_delivery_rejects_missing_review(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "best_material.lmat").write_bytes(TRACKED_BEST.read_bytes())
    (run_dir / "stage2_v86_report.json").write_text(
        json.dumps(
            {
                "accepted": False,
                "best_score": 0.884,
                "best_material_path": str(run_dir / "best_material.lmat"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="incomplete run-backed delivery"):
        build_delivery_package(
            repo_root=REPO_ROOT,
            asset_id="1613",
            output_zip=tmp_path / "missing.zip",
            run_dir=run_dir,
        )


def test_run_backed_delivery_requires_and_collects_all_views(tmp_path: Path) -> None:
    asset = resolve_material_asset(REPO_ROOT, "1613")
    run_dir = tmp_path / "run"
    best_render = run_dir / "best_render"
    best_render.mkdir(parents=True)
    (run_dir / "best_material.lmat").write_bytes(TRACKED_BEST.read_bytes())
    (run_dir / "best_params_full_resolution_reranked.json").write_text(
        "{}",
        encoding="utf-8",
    )
    for view in asset.profile["capture_defaults"]["views"]:
        Image.new("RGB", (16, 16), "white").save(best_render / view["file_name"])
    contact_sheet = run_dir / "unity_start_v86_best.png"
    Image.new("RGB", (32, 16), "white").save(contact_sheet)
    (run_dir / "stage2_v86_report.json").write_text(
        json.dumps(
            {
                "accepted": False,
                "best_score": 0.884,
                "best_material_path": str(run_dir / "best_material.lmat"),
                "best_params_path": str(
                    run_dir / "best_params_full_resolution_reranked.json"
                ),
                "best_render_dir": str(best_render),
                "contact_sheet": str(contact_sheet),
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "complete.zip"
    build_delivery_package(
        repo_root=REPO_ROOT,
        asset_id="1613",
        output_zip=output,
        run_dir=run_dir,
    )

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert len(
            [
                name
                for name in names
                if name.startswith("complete/review/best_render/")
                and name.endswith(".png")
            ]
        ) == 8
        assert "complete/review/unity_start_v86_best.png" in names
