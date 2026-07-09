from __future__ import annotations

from pathlib import Path


def test_runtime_renderer_material_patch_preserves_vector_uniform_types() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "setVector4" in text
    assert "COLOR_PARAM_NAMES" in text
    assert "COLOR_PARAM_NAMES.has(name)" in text


def test_runtime_renderer_does_not_silently_fallback_when_scene_url_fails() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    assert "allowFallbackScene" in text
    assert "window.__MATERIAL_FIT_READY__ = { ok: false" in text
    assert "scene load failed, falling back to cube" not in text
    assert "capture-result rejected" in text


def test_runtime_renderer_patches_scene_materials_before_scene_ready() -> None:
    renderer = Path(__file__).resolve().parents[1] / "laya_capture" / "runtime_renderer.html"
    text = renderer.read_text(encoding="utf-8")

    scene_patch = "ensureRuntimeMaterialCompatibility(sceneRoot);"
    prefab_patch = "ensureRuntimeMaterialCompatibility(prefab);"

    assert scene_patch in text
    assert prefab_patch in text
    assert text.index(scene_patch) < text.index("await waitFrames(4);")
    assert text.index(scene_patch) < text.index('console.log("[material-fit] loaded scene: " + sceneUrl);')


def test_runtime_renderer_node_exits_on_pageerror() -> None:
    runner = Path(__file__).resolve().parents[1] / "laya_capture" / "run_runtime_renderer.js"
    text = runner.read_text(encoding="utf-8")

    assert "exitOnFatalPageError" in text
    assert "page.on('pageerror'" in text
    assert "process.exit(1);" in text
