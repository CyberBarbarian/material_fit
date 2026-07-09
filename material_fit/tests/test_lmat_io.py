"""Regression tests for the .lmat read/write hardening.

Background: an earlier version of this module silently allowed the optimiser
to add new top-level keys (``u_BaseMap = "white"`` etc.) and to change the
shape of existing values. The result was an .lmat that Laya could no longer
load, which broke the user's model rendering until they restored from
backup. These tests pin the new strict guarantees in place so that bug
class can never regress.

Run with:

    python -m pytest tools/material_fit/tests/test_lmat_io.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.material_fit.laya import lmat_io  # noqa: E402
from tools.material_fit.laya.lmat_io import LmatWriteError  # noqa: E402
from tools.material_fit.laya.shader_parser import parse_laya_shader  # noqa: E402
from tools.material_fit.optimizer.parameter_search import (  # noqa: E402
    build_initial_params,
    build_zero_searchable_initial_params,
)
from tools.material_fit.shared.models import ShaderParam  # noqa: E402


REAL_LMAT = ROOT / "assets/resources/play/fish/1580/mat/1580_body.lmat"
REAL_SHADER = ROOT / "assets/resources/shader/FishStandard.shader"


@pytest.fixture
def real_lmat_text() -> str:
    if not REAL_LMAT.exists():
        pytest.skip(f"sample .lmat missing: {REAL_LMAT}")
    return REAL_LMAT.read_text(encoding="utf-8-sig")


@pytest.fixture
def real_lmat() -> dict:
    if not REAL_LMAT.exists():
        pytest.skip(f"sample .lmat missing: {REAL_LMAT}")
    return lmat_io.load_lmat(REAL_LMAT)


@pytest.fixture
def real_shader():
    if not REAL_SHADER.exists():
        pytest.skip(f"sample shader missing: {REAL_SHADER}")
    return parse_laya_shader(REAL_SHADER)


def test_load_round_trips_through_json(real_lmat_text: str) -> None:
    """``load_lmat`` must produce the same dict as plain ``json.loads``."""
    via_loader = lmat_io.load_lmat(REAL_LMAT)
    via_json = json.loads(real_lmat_text)
    assert via_loader == via_json


def test_extract_params_excludes_engine_state_and_header(real_lmat: dict) -> None:
    params = lmat_io.extract_params(real_lmat)
    forbidden = {"type", "renderQueue", "materialRenderMode", "textures", "defines"}
    leaked = forbidden & set(params)
    assert not leaked, f"extract_params leaked engine-state keys: {leaked}"
    s_keys = [k for k in params if k.startswith("s_")]
    assert not s_keys, f"extract_params leaked s_* engine state: {s_keys}"


def test_shader_parser_default_keeps_full_vector(real_shader) -> None:
    """``default: [1, 1, 1, 1]`` must parse as a 4-element list, not '[1'."""
    bc = next((p for p in real_shader.params if p.name == "u_BaseColor"), None)
    assert bc is not None, "u_BaseColor not found in parsed shader"
    assert isinstance(bc.default, list), (
        f"u_BaseColor.default should be list, got {type(bc.default).__name__}({bc.default!r})"
    )
    assert len(bc.default) == 4, (
        f"u_BaseColor.default should have 4 components, got {bc.default!r}"
    )


def test_build_initial_params_drops_texture_sampler_defaults(real_lmat, real_shader) -> None:
    """Texture/sampler params must NEVER appear as top-level scalar uniforms.

    Before the fix, build_initial_params produced ``u_BaseMap = "white"``,
    ``u_Mask = "white"`` etc., which when written into ``props`` made the
    .lmat unparseable by Laya.
    """
    laya_params = lmat_io.extract_params(real_lmat)
    initial = build_initial_params(laya_params, real_shader.params)

    sampler_names = {
        p.name for p in real_shader.params
        if str(p.param_type).strip().lower() in {
            "texture2d", "texture", "texturecube",
            "sampler2d", "sampler", "samplercube", "rendertexture",
        }
    }
    leaked = sampler_names & set(initial)
    assert not leaked, (
        f"sampler params leaked into initial_params as scalar uniforms: {leaked}"
    )

    # And no string values should be left in initial_params either.
    string_vals = {k: v for k, v in initial.items() if isinstance(v, str)}
    assert not string_vals, (
        f"initial_params still contains string-valued uniforms: {string_vals}"
    )


def test_zero_searchable_initial_params_zeroes_searchable_but_preserves_validity_params() -> None:
    """Zero-start may be visually blank, but must keep material-validity values."""
    shader_params = [
        ShaderParam("u_Color", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_ShadowColor1", "Color", default=[0.5, 0.5, 0.5, 1]),
        ShaderParam("u_RimColor", "Color", default=[0, 1, 1, 1]),
        ShaderParam("u_MainTex_ST", "Vector4", default=[1, 1, 0, 0]),
        ShaderParam("u_NormalTex_ST", "Vector4", default=[1, 1, 0, 0]),
        ShaderParam("u_AlphaTestValue", "Float", default=0.5),
        ShaderParam("u_SkyRotateX", "Float", default=231.0),
        ShaderParam("u_SkyRotateY", "Float", default=255.0),
        ShaderParam("u_TexPower", "Float", default=1.0),
        ShaderParam("u_GammaPower", "Float", default=2.2),
        ShaderParam("u_Saturation", "Float", default=1.0),
        ShaderParam("u_Contrast", "Float", default=1.0),
        ShaderParam("u_NormalScale", "Float", default=1.0),
        ShaderParam("u_IndirectStrength", "Float", default=1.0),
        ShaderParam("u_SpecularIntensity", "Float", default=0.9),
        ShaderParam("u_EmissionPow", "Float", default=0.8),
    ]
    baseline = {
        "u_Color": [0.85, 0.84, 0.70, 1.0],
        "u_ShadowColor1": [0.7, 0.82, 0.82, 1.0],
        "u_RimColor": [0.68, 1.0, 0.87, 1.0],
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_NormalTex_ST": [1.0, 1.0, 0.0, 0.0],
        "u_AlphaTestValue": 0.5,
        "u_SkyRotateX": 231.0,
        "u_SkyRotateY": 255.0,
        "u_TexPower": 1.7,
        "u_GammaPower": 2.2,
        "u_Saturation": 0.86,
        "u_Contrast": 1.0,
        "u_NormalScale": 0.9,
        "u_IndirectStrength": 1.4,
        "u_SpecularIntensity": 0.9,
        "u_EmissionPow": 0.8,
    }

    zero_start = build_zero_searchable_initial_params(baseline, shader_params)

    assert zero_start["u_Color"] == [0.0, 0.0, 0.0, 1.0]
    assert zero_start["u_ShadowColor1"] == [0.0, 0.0, 0.0, 1.0]
    assert zero_start["u_RimColor"] == [0.0, 0.0, 0.0, 1.0]
    assert zero_start["u_TexPower"] == 0.0
    assert zero_start["u_GammaPower"] == 0.0
    assert zero_start["u_Saturation"] == 0.0
    assert zero_start["u_Contrast"] == 0.0
    assert zero_start["u_NormalScale"] == 0.0
    assert zero_start["u_IndirectStrength"] == 0.0
    assert zero_start["u_SpecularIntensity"] == 0.0
    assert zero_start["u_EmissionPow"] == 0.0
    assert zero_start["u_MainTex_ST"] == [1.0, 1.0, 0.0, 0.0]
    assert zero_start["u_NormalTex_ST"] == [1.0, 1.0, 0.0, 0.0]
    assert zero_start["u_AlphaTestValue"] == 0.5
    assert zero_start["u_SkyRotateX"] == 231.0
    assert zero_start["u_SkyRotateY"] == 255.0


def test_round_trip_preserves_structure(tmp_path, real_lmat, real_shader) -> None:
    """No-op round trip must leave the .lmat byte-identical."""
    laya_params = lmat_io.extract_params(real_lmat)
    initial = build_initial_params(laya_params, real_shader.params)

    out = tmp_path / "1580_body.lmat"
    lmat_io.write_candidate_lmat(REAL_LMAT, out, initial, allow_missing_keys=True)

    assert REAL_LMAT.read_bytes() == out.read_bytes(), (
        "no-op round trip changed the .lmat at byte level"
    )


def test_imported_textures_are_preserved_across_writes(tmp_path, real_lmat) -> None:
    """User-imported textures live under ``props.textures[]``. They must be
    preserved verbatim across every write path, including when the optimiser
    proposes scalar-uniform changes. (Regression test for the user concern
    that the algorithm might delete imported texture bindings.)"""
    original_textures = real_lmat["props"]["textures"]
    assert isinstance(original_textures, list) and len(original_textures) > 0, (
        "fixture lmat is expected to have at least one imported texture"
    )

    out = tmp_path / "1580_body.lmat"
    lmat_io.write_candidate_lmat(
        REAL_LMAT,
        out,
        {"u_Metallic": 0.42, "u_BaseColor": [0.5, 0.5, 0.5, 1.0]},
    )
    rewritten = lmat_io.load_lmat(out)
    assert rewritten["props"]["textures"] == original_textures, (
        "props.textures[] was modified by a scalar-only param update"
    )


def test_apply_params_cannot_clobber_textures_array(real_lmat) -> None:
    """Even if a caller maliciously passes 'textures' in params, the strict
    apply_params must refuse rather than overwriting imported bindings."""
    with pytest.raises(LmatWriteError):
        lmat_io.apply_params(real_lmat, {"textures": []})


def test_apply_params_rejects_new_keys(real_lmat) -> None:
    """The exact bug that broke the user's model: writing a sampler default."""
    with pytest.raises(LmatWriteError) as exc:
        lmat_io.apply_params(real_lmat, {"u_BaseMap": "white"})
    assert "u_BaseMap" in str(exc.value)


def test_apply_params_drops_unknown_when_allow_missing(real_lmat) -> None:
    result = lmat_io.apply_params(
        real_lmat,
        {"u_BaseMap": "white", "u_Metallic": 0.5},
        allow_missing_keys=True,
    )
    props = result["props"]
    assert "u_BaseMap" not in props, "allow_missing_keys must drop, not add, unknown keys"
    assert props["u_Metallic"] == 0.5


def test_apply_params_rejects_shape_change_list_to_scalar(real_lmat) -> None:
    """Replacing vec4 ``u_BaseColor`` with a scalar must raise, not be silently saved."""
    with pytest.raises(LmatWriteError) as exc:
        lmat_io.apply_params(real_lmat, {"u_BaseColor": 0.5})
    msg = str(exc.value)
    assert "u_BaseColor" in msg
    assert "list[4]" in msg and "number" in msg


def test_apply_params_rejects_shape_change_list_length(real_lmat) -> None:
    with pytest.raises(LmatWriteError) as exc:
        lmat_io.apply_params(real_lmat, {"u_BaseColor": [1, 1, 1]})  # rgb instead of rgba
    assert "u_BaseColor" in str(exc.value)


def test_apply_params_rejects_reserved_keys(real_lmat) -> None:
    """type / renderQueue / textures / s_* are not optimiser-writable."""
    with pytest.raises(LmatWriteError):
        lmat_io.apply_params(real_lmat, {"type": "evil/shader"})
    with pytest.raises(LmatWriteError):
        lmat_io.apply_params(real_lmat, {"s_Cull": 1})
    with pytest.raises(LmatWriteError):
        lmat_io.apply_params(real_lmat, {"textures": []})


def test_apply_params_accepts_valid_numeric_tweak(real_lmat) -> None:
    out = lmat_io.apply_params(real_lmat, {"u_Metallic": 0.5, "u_BaseColor": [0.9, 0.8, 0.7, 1.0]})
    assert out["props"]["u_Metallic"] == 0.5
    assert out["props"]["u_BaseColor"] == [0.9, 0.8, 0.7, 1.0]


def test_write_candidate_lmat_validates_after_save(tmp_path, real_lmat) -> None:
    """A successful write_candidate_lmat must produce a parseable file with
    the same shape as the source."""
    out = tmp_path / "candidate.lmat"
    lmat_io.write_candidate_lmat(
        REAL_LMAT,
        out,
        {"u_Metallic": 0.42, "u_BaseColor": [0.5, 0.5, 0.5, 1.0]},
    )
    reloaded = lmat_io.load_lmat(out)
    assert reloaded["props"]["u_Metallic"] == 0.42
    assert reloaded["props"]["u_BaseColor"] == [0.5, 0.5, 0.5, 1.0]
    diffs = lmat_io.diff_shapes(real_lmat, reloaded)
    assert not diffs, f"shape diffs after write_candidate_lmat: {diffs}"


def test_write_candidate_lmat_refuses_corrupt_payload(tmp_path, real_lmat) -> None:
    """When the optimiser somehow produces a bad payload, the candidate
    file must NOT be left on disk in a half-written state."""
    _ = real_lmat
    out = tmp_path / "candidate.lmat"
    with pytest.raises(LmatWriteError):
        lmat_io.write_candidate_lmat(
            REAL_LMAT,
            out,
            {"u_BaseColor": "not-a-vec4"},
        )
    assert not out.exists(), "broken candidate .lmat must not remain on disk"
