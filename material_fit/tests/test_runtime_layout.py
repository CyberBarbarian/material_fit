"""Runtime layout checks for this standalone checkout."""

from __future__ import annotations

from pathlib import Path


def test_tools_namespace_resolves_current_checkout_packages():
    import tools.material_fit as material_fit_pkg
    import tools.material_fit_ui as material_fit_ui_pkg

    repo_root = Path(__file__).resolve().parents[2]
    assert Path(material_fit_pkg.__file__).resolve().parent == repo_root / "material_fit"
    assert repo_root / "material_fit_ui" in [
        Path(path).resolve() for path in material_fit_ui_pkg.__path__
    ]


def test_launcher_uses_current_checkout_root():
    from material_fit_ui import launch

    assert (launch.REPO_ROOT / "material_fit" / "fit_material.py").exists()
    assert (launch.REPO_ROOT / "material_fit_ui" / "backend" / "main.py").exists()


def test_backend_loader_uses_current_checkout_artifact_dirs():
    from material_fit_ui.backend.case_loader import LoaderConfig

    repo_root = Path(__file__).resolve().parents[2]
    config = LoaderConfig()
    assert config.project_root == repo_root
    assert config.output_dir == repo_root / "material_fit" / "output"
    assert config.image_root == (repo_root / "material_fit").resolve()
