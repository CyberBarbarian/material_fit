from __future__ import annotations

from pathlib import Path

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.assets.stage2_unity_references import (
    audit_stage2_unity_references,
    resolve_stage2_unity_references,
)
from material_fit.laya import lmat_io


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_holiday_1613_renderer_intake_is_self_contained() -> None:
    asset = resolve_material_asset(REPO_ROOT, "1613")

    assert asset.asset_id == "holiday_1613"
    assert asset.scene_path.name == "1613.lh"
    assert asset.target_material_path.name == "fish_1543_shengdanlaoren_laya_diff.lmat"
    assert asset.shader_path.name == "Custom_low.shader"
    assert asset.profile["width"] == 900
    assert asset.profile["height"] == 700
    assert asset.profile["capture_defaults"]["orthographic_vertical_size"] == 6.625
    assert asset.profile["runtime"]["camera"]["center_offset"] == [0.0, 0.34, 0.0]
    assert asset.profile["capture_defaults"]["target_base_yaw"] == 180.0
    assert asset.profile["camera_calibration"]["target_base_yaw"] == 180.0
    assert asset.profile["camera_calibration"]["alignment_passed"] is True
    assert asset.profile["capture_defaults"]["animation_mode"] == "disabled"
    assert len(asset.profile["capture_defaults"]["views"]) == 8

    textures = lmat_io.extract_textures(lmat_io.load_lmat(asset.target_material_path))
    params = lmat_io.extract_params(lmat_io.load_lmat(asset.target_material_path))
    assert len(textures) == 1
    assert textures[0]["name"] == "u_MainTex"
    assert textures[0]["path"] == "res://f2d112e5-1b94-40ee-9eb0-2a199fe25b15"
    assert textures[0]["constructParams"][:2] == [1024, 1024]
    assert not any(name.startswith("u_MaterialFit") for name in params)
    assert (
        asset.project_root
        / "assets/resources/model/1613/texture/fish_1543_shengdanlaoren_laya_diff.png.meta"
    ).is_file()


def test_holiday_1613_unity_references_are_structurally_valid() -> None:
    reference_set = resolve_stage2_unity_references(REPO_ROOT, "holiday_1613")
    report = audit_stage2_unity_references(reference_set)

    assert reference_set.asset_id == "1613"
    assert report["passed"] is True
    assert report["geometry_ready"] is True
    assert report["image_size"] == [900, 700]
    assert report["capture_mode"] == "rotate_target"
    assert report["use_orthographic"] is True
    assert report["orthographic_size"] == 2.5
    assert report["clipped_view_ids"] == []
    assert len(report["views"]) == 8
    assert all(view["partial_alpha_pixels"] == 0 for view in report["views"])


def test_holiday_1613_shader_has_no_view_conditioned_material_fit_path() -> None:
    asset = resolve_material_asset(REPO_ROOT, "1613")
    shader = asset.shader_path.read_text(encoding="utf-8")

    assert "u_MaterialFitViewAtlas" not in shader
    assert "u_MaterialFitObservationYaw" not in shader
