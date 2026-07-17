from __future__ import annotations

import json

import pytest

from material_fit.optimizer.fish_define_variants import (
    FISH_DEFINE_VARIANTS,
    MANAGED_FISH_DEFINES,
    apply_variant_to_capture_config,
    define_patch_for_variant,
    material_with_variant,
    optimizer_input_boundary_report,
)


def test_fish_define_variants_are_six_legal_normal_and_rim_states() -> None:
    assert len(FISH_DEFINE_VARIANTS) == 6
    for enabled in FISH_DEFINE_VARIANTS.values():
        assert set(enabled) <= set(MANAGED_FISH_DEFINES)
        assert "NORMALMAP_Y_INVERT" not in enabled or "NORMALMAP" in enabled


def test_define_patch_is_complete_and_rejects_unknown_variant() -> None:
    patch = define_patch_for_variant("normal_smooth_rim")
    assert patch["managed"] == list(MANAGED_FISH_DEFINES)
    assert patch["enabled"] == ["NORMALMAP", "RIMSMOOTHNESS"]
    with pytest.raises(ValueError, match="unknown fish define variant"):
        define_patch_for_variant("invented")


def test_apply_variant_to_capture_config_keeps_candidate_values_dynamic() -> None:
    config = {"laya_capture": {"material_patch": {"target_name": "model"}}}
    apply_variant_to_capture_config(config, "normal_y_invert_hard_rim")
    patch = config["laya_capture"]["material_patch"]
    assert patch["target_name"] == "model"
    assert "values" not in patch
    assert patch["defines"]["enabled"] == ["NORMALMAP", "NORMALMAP_Y_INVERT"]


def test_material_with_variant_uses_start_material_not_teacher(tmp_path) -> None:
    source = tmp_path / "active.lmat"
    source.write_text(
        json.dumps({"props": {"u_GammaPower": 1.0, "defines": ["NORMALMAP_Y_INVERT"]}}),
        encoding="utf-8",
    )
    material = material_with_variant(source, {"u_GammaPower": 1.5}, "normal_smooth_rim")
    assert material["props"]["u_GammaPower"] == pytest.approx(1.5)
    assert material["props"]["defines"] == ["NORMALMAP", "RIMSMOOTHNESS"]


def test_optimizer_input_boundary_rejects_human_or_teacher_paths() -> None:
    valid = optimizer_input_boundary_report(
        {"laya_capture": {"browser_score": {"reference_images": ["target_render/v000.png"]}}}
    )
    assert valid["passed"] is True

    invalid = optimizer_input_boundary_report(
        {"target_material": "material_starts/1504/human_adjusted/1504_body.lmat"}
    )
    assert invalid["passed"] is False
    assert {item["token"] for item in invalid["hits"]} >= {"human_adjusted", "1504_body.lmat"}
