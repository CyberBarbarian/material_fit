from __future__ import annotations

from pathlib import Path

from PIL import Image

from material_fit.laya_capture.prepare_browser_assets import prepare_browser_assets


def test_prepare_browser_assets_converts_tga_to_png_cache(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = project_root / "assets" / "tex" / "sample.tga"
    source.parent.mkdir(parents=True)
    Image.new("RGBA", (4, 3), (32, 64, 96, 255)).save(source)

    converted = prepare_browser_assets(project_root)

    output = project_root / ".material_fit_browser_assets" / "assets" / "tex" / "sample.tga.png"
    assert converted == [output]
    assert output.exists()
    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert image.size == (4, 3)


def test_prepare_browser_assets_reuses_fresh_cache(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = project_root / "assets" / "tex" / "sample.tga"
    source.parent.mkdir(parents=True)
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(source)
    first = prepare_browser_assets(project_root)[0]
    first_mtime = first.stat().st_mtime

    second = prepare_browser_assets(project_root)[0]

    assert second == first
    assert second.stat().st_mtime == first_mtime
