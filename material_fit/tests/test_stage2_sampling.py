from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from material_fit.assets.stage2_sampling import resolve_stage2_sampling
from material_fit.vision.stage2_registration import (
    apply_frozen_stage2_registration,
    reference_in_source_frame,
    register_canvas,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_turtle_stage2_sampling_matches_unity_canvas_without_target_material() -> None:
    spec = resolve_stage2_sampling(REPO_ROOT, "turtle", material_variant="start")
    base_profile = json.loads(
        (REPO_ROOT / "material_fit" / "assets" / "profiles" / "turtle_1506.json").read_text(
            encoding="utf-8-sig"
        )
    )
    capture = spec.profile["capture_defaults"]
    camera = spec.profile["runtime"]["camera"]

    assert spec.references.asset_id == "1506"
    assert spec.material_path.name == "1506_test.lmat"
    assert spec.lighting_variant == "baseline"
    assert spec.additional_material_defines == ()
    assert "lighting_presets" not in spec.calibration
    assert "ambient_gradient" not in spec.profile["runtime"]
    assert "ambient_sh_coefficients" not in spec.profile["runtime"]
    assert "ibl_material_texture" not in spec.profile["runtime"]
    assert spec.profile["width"] == 900
    assert spec.profile["height"] == 700
    assert spec.profile["runtime"]["environment"] == {"preset": "laya_prefab_editor"}
    for key in ("environment", "ambient_color", "material_compatibility"):
        assert spec.profile["runtime"][key] == base_profile["runtime"][key]
    assert camera["orthographic"] is False
    assert camera["field_of_view"] == pytest.approx(60.0)
    assert camera["distance"] == pytest.approx(10.293167752060222)
    assert capture["capture_mode"] == "orbit_camera"
    assert "orthographic_vertical_size" not in capture
    assert capture["fov"] == pytest.approx(60.0)
    assert capture["camera_distance"] == pytest.approx(10.293167752060222)
    assert capture["camera_center"] == pytest.approx(
        [1.2377265, -0.0549351, -0.0851226]
    )
    assert capture["animation_mode"] == "disabled"
    assert [view["yaw"] for view in capture["views"]] == [
        0.0,
        45.0,
        90.0,
        135.0,
        180.0,
        225.0,
        270.0,
        315.0,
    ]
    serialized = json.dumps(spec.manifest(), ensure_ascii=False)
    assert "1506_mat.lmat" not in serialized
    registration = spec.calibration["registration"]
    assert registration["mode"] == "frozen_per_view_similarity"
    assert registration["output_size"] == [900, 700]
    assert len(registration["transforms"]) == 8


def test_turtle_stage2_sampling_can_render_human_material_for_offline_audit() -> None:
    spec = resolve_stage2_sampling(REPO_ROOT, "1506", material_variant="human-adjusted")

    assert spec.material_variant == "human-adjusted"
    assert spec.material_path.name == "1506_mat.lmat"
    assert spec.calibration["calibration"]["material_independence_verified"] is True


def test_turtle_stage2_sampling_rejects_unknown_lighting_variant() -> None:
    with pytest.raises(ValueError, match="unsupported Stage 2 lighting variant"):
        resolve_stage2_sampling(REPO_ROOT, "1506", lighting_variant="missing")


def test_stage2_sampling_rejects_clipped_reference_sets_before_calibration_lookup() -> None:
    with pytest.raises(ValueError, match="not geometry-ready"):
        resolve_stage2_sampling(REPO_ROOT, "fish")


def test_stage2_registration_identity_preserves_canvas() -> None:
    source = Image.new("RGB", (16, 12), "white")
    source.putpixel((4, 5), (20, 40, 60))

    result = register_canvas(
        source,
        output_size=(16, 12),
        scale=1.0,
        dx=0.0,
        dy=0.0,
    )

    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def test_stage2_registration_keeps_raw_capture_and_writes_manifest(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "registered"
    raw_dir.mkdir()
    source_path = raw_dir / "laya_v000.png"
    source = Image.new("RGB", (20, 10), "white")
    source.putpixel((5, 5), (0, 0, 0))
    source.save(source_path)
    original_bytes = source_path.read_bytes()

    report = apply_frozen_stage2_registration(
        raw_dir=raw_dir,
        output_dir=output_dir,
        views=[{"view_id": "v000", "candidate_file_name": source_path.name}],
        registration={
            "mode": "frozen_per_view_similarity",
            "output_size": [20, 10],
            "transforms": [{"view_id": "v000", "scale": 1.0, "dx": 2.0, "dy": 0.0}],
        },
    )

    assert source_path.read_bytes() == original_bytes
    assert (output_dir / source_path.name).is_file()
    assert report["renderer_environment_changed"] is False
    assert report["per_proposal_registration"] is False


def test_stage2_registration_rejects_nonmatching_raw_canvas() -> None:
    with pytest.raises(ValueError, match="raw capture size"):
        register_canvas(
            Image.new("RGB", (10, 10), "white"),
            output_size=(20, 20),
            scale=1.0,
            dx=0.0,
            dy=0.0,
        )


def test_stage2_reference_can_be_mapped_back_to_raw_frame() -> None:
    target = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
    for y in range(10, 20):
        for x in range(12, 28):
            target.putpixel((x, y), (30, 80, 140, 255))

    raw_reference = reference_in_source_frame(
        target,
        output_size=(40, 30),
        scale=1.25,
        dx=3.0,
        dy=-2.0,
    )
    restored = register_canvas(
        raw_reference,
        output_size=(40, 30),
        scale=1.25,
        dx=3.0,
        dy=-2.0,
    )

    assert raw_reference.getpixel((0, 0)) == (255, 255, 255)
    assert restored.getbbox() == (0, 0, 40, 30)
    assert restored.getpixel((20, 15))[2] > restored.getpixel((20, 15))[0]


def test_vendored_prefab_environment_matches_recorded_files() -> None:
    expected = {
        "DefaultPrefabEditEnv.ls": "df7635d0811897e1ec7bc96022954ea0d3b8001ccd9b65ac77db1ad3b71244d5",
        "DefaultPrefabEditEnv.ls.meta": "36c5eb1370a2ef5002f6a6857e0c34250bf6734a8317aef1c6c1e831a392729c",
        "DefaultSkyMaterial.lmat": "de7dcb4e87efa4b0c821517feb81dd2275eec38d80b879d36a14c3007fb56183",
        "DefaultSkyMaterial.lmat.meta": "4813c7db25bc47e7064acf28e77291f4fb664bd9cb87f1f3266d4bdd1749d8d6",
        "sky.jpg": "9019d845676466611debe60c67299f1ca3edf0edbb6b367d54340b8a9b22b925",
        "sky.jpg.meta": "e66f9822a9ccf88cd9d9606fe039d210a80c31e24b52bff90f5e856e98b8922a",
    }

    for name, expected_hash in expected.items():
        path = REPO_ROOT / "vendor" / "internal" / name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
