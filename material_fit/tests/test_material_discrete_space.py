from __future__ import annotations

import json
from pathlib import Path

from material_fit.assets.material_stage1 import resolve_material_stage1_asset
from material_fit.laya import lmat_io
from material_fit.laya.render_driver import _candidate_material_patch
from material_fit.laya_capture.asset_profile import material_patch_from_lmat
from material_fit.optimizer.material_discrete_space import (
    BROWSER_SCORE_OVERRIDE_PARAM,
    DISCRETE_CANDIDATE_PARAM,
    attach_discrete_candidate,
    build_legal_discrete_candidates,
    compress_observationally_equivalent_candidates,
    find_candidate_for_patch,
    split_discrete_candidate,
    write_candidate_lmat_with_discrete_state,
)


def test_shared_space_contains_all_define_bits_blend_values_and_original_starts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for asset_id in ("fish", "turtle"):
        asset = resolve_material_stage1_asset(repo_root, asset_id)
        start_patch = material_patch_from_lmat(asset.start_material_path)
        candidates = build_legal_discrete_candidates(start_patch)
        start_candidate = find_candidate_for_patch(candidates, start_patch)

        assert len(candidates) == 16
        assert len({row["candidate_id"] for row in candidates}) == 16
        assert start_candidate["defines"]["enabled"] == ["NORMALMAP_Y_INVERT"]
        assert start_candidate["render_states"] == {"s_BlendSrc": 1}
        assert {row["render_states"]["s_BlendSrc"] for row in candidates} == {0, 1}

        representatives, report = compress_observationally_equivalent_candidates(
            candidates,
            start_candidate=start_candidate,
            start_patch=start_patch,
        )
        assert start_patch["render_states"]["s_Blend"] == 0
        assert len(representatives) == 6
        assert report["legal_candidate_count"] == 16
        assert report["representative_candidate_count"] == 6
        assert report["start_candidate_preserved"] is True
        assert report["target_information_used"] is False


def test_observation_equivalence_keeps_blend_source_when_blending_is_active() -> None:
    start_patch = {
        "defines": {
            "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
            "enabled": ["NORMALMAP_Y_INVERT"],
        },
        "render_states": {"s_Blend": 1, "s_BlendSrc": 1},
    }
    candidates = build_legal_discrete_candidates(start_patch)
    start_candidate = find_candidate_for_patch(candidates, start_patch)

    representatives, report = compress_observationally_equivalent_candidates(
        candidates,
        start_candidate=start_candidate,
        start_patch=start_patch,
    )

    assert len(representatives) == 12
    assert report["blend_enabled"] is True
    assert report["rules"]["blend_src_is_dormant_when_blending_disabled"] is False


def test_dynamic_render_patch_does_not_send_internal_candidate_as_uniform() -> None:
    start_patch = {
        "target_name": "model",
        "defines": {
            "managed": ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"],
            "enabled": ["NORMALMAP_Y_INVERT"],
        },
        "render_states": {"s_BlendSrc": 1, "s_DepthWrite": True},
    }
    candidates = build_legal_discrete_candidates(start_patch)
    selected = next(
        row
        for row in candidates
        if row["defines"]["enabled"] == ["NORMALMAP", "RIMSMOOTHNESS"]
        and row["render_states"]["s_BlendSrc"] == 0
    )
    params = attach_discrete_candidate({"u_GammaPower": 1.25}, selected)
    params[BROWSER_SCORE_OVERRIDE_PARAM] = {
        "metric": "cross_engine_foreground_components_v4"
    }

    patch = _candidate_material_patch(start_patch, target_name="model", params=params)

    assert patch["values"] == {"u_GammaPower": 1.25}
    assert DISCRETE_CANDIDATE_PARAM not in patch["values"]
    assert BROWSER_SCORE_OVERRIDE_PARAM not in patch["values"]
    assert patch["defines"]["enabled"] == ["NORMALMAP", "RIMSMOOTHNESS"]
    assert patch["render_states"] == {"s_BlendSrc": 0, "s_DepthWrite": True}
    assert patch["discrete_candidate_id"] == selected["candidate_id"]


def test_write_candidate_material_persists_selected_discrete_state(tmp_path: Path) -> None:
    source = tmp_path / "source.lmat"
    output = tmp_path / "best.lmat"
    source.write_text(
        json.dumps(
            {
                "version": "LAYAMATERIAL:04",
                "props": {
                    "type": "Custom/Test",
                    "renderQueue": 2000,
                    "materialRenderMode": 0,
                    "defines": ["NORMALMAP_Y_INVERT", "UNMANAGED_KEEP"],
                    "s_BlendSrc": 1,
                    "s_DepthWrite": True,
                    "textures": [],
                    "u_GammaPower": 0.5,
                },
            }
        ),
        encoding="utf-8",
    )
    patch = material_patch_from_lmat(source)
    candidates = build_legal_discrete_candidates(patch)
    selected = next(
        row
        for row in candidates
        if row["defines"]["enabled"]
        == ["NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS"]
        and row["render_states"]["s_BlendSrc"] == 0
    )
    params = attach_discrete_candidate({"u_GammaPower": 1.5}, selected)

    write_candidate_lmat_with_discrete_state(source, output, params)
    props = lmat_io.get_props(lmat_io.load_lmat(output))
    continuous, recovered = split_discrete_candidate(params)

    assert continuous == {"u_GammaPower": 1.5}
    assert recovered == selected
    assert props["u_GammaPower"] == 1.5
    assert props["s_BlendSrc"] == 0
    assert props["defines"] == [
        "UNMANAGED_KEEP",
        "NORMALMAP",
        "NORMALMAP_Y_INVERT",
        "RIMSMOOTHNESS",
    ]
