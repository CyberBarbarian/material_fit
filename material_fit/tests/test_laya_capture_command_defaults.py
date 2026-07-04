from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.laya_capture.capture_server import build_command  # noqa: E402
from tools.material_fit.laya_capture import editor_command  # noqa: E402


def _minimal_capture_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "unity_metadata": "",
        "command_json": "",
        "output_dir": "",
        "host": "127.0.0.1",
        "port": 8787,
        "camera_name": "",
        "target_name": "model",
        "width": 320,
        "height": 240,
        "center": "",
        "target_size": "",
        "distance_scale": 2.2,
        "min_distance": 1.0,
        "fov": None,
        "use_orthographic": "auto",
        "orthographic_vertical_size": None,
        "capture_mode": "rotate_target",
        "yaw_offset": 0.0,
        "pitch_offset": 0.0,
        "target_yaw_sign": -1.0,
        "target_pitch_sign": -1.0,
    }
    values.update(overrides)
    return Namespace(**values)


def test_capture_server_defaults_to_render_alpha(tmp_path: Path) -> None:
    command = build_command(_minimal_capture_args(output_dir=str(tmp_path)), tmp_path)

    assert command["alpha_source"] == "render_alpha"


def test_editor_command_honors_alpha_source_override(tmp_path: Path, monkeypatch) -> None:
    laya_project = tmp_path / "laya_project"
    command_out = laya_project / "assets" / "material_fit_capture_command.json"
    output_dir = tmp_path / "captures"
    argv = [
        "editor_command",
        "--laya-project",
        str(laya_project),
        "--command-out",
        str(command_out),
        "--output-dir",
        str(output_dir),
        "--alpha-source",
        "silhouette_mask",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert editor_command.main() == 0

    command = json.loads(command_out.read_text(encoding="utf-8"))
    assert command["alpha_source"] == "silhouette_mask"
    assert command["zero_transparent_rgb"] is True
