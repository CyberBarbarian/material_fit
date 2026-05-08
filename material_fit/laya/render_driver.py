from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class RenderDriver:
    """Bridge between Python fitting code and the real Laya render scene.

    The first framework version supports two modes:
    - ``dry_run``: only writes candidate parameter files.
    - external command: invokes a user-provided renderer command later wired to
      the Laya benchmark scene and screenshot process.
    """

    def __init__(
        self,
        output_dir: str | Path,
        command: list[str] | None = None,
        dry_run: bool = True,
        capture_config: dict[str, Any] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.command = command or []
        self.dry_run = dry_run
        self.capture_config = capture_config or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render_candidate(self, iteration: int, params: dict[str, Any]) -> dict[str, Any]:
        iteration_dir = self.output_dir / "iterations" / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        params_path = iteration_dir / "params.json"
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

        if self.dry_run or not self.command:
            return {"status": "dry_run", "params_path": str(params_path), "screenshots": []}

        completed = subprocess.run(
            [*self.command, str(params_path), str(iteration_dir)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return {
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "params_path": str(params_path),
            "screenshots": [str(path) for path in iteration_dir.glob("*.png")],
        }

    def capture_candidate(self, iteration: int, params: dict[str, Any]) -> dict[str, Any]:
        """Write candidate params and invoke the configured screenshot command.

        The default command shape is intentionally simple and product-friendly:
        ``command <capture_request.json> <output.png>``. The provided
        ``vision/capture_laya.js`` helper implements this contract using
        Puppeteer, but teams may replace it with any renderer/capture program.
        """

        iteration_dir = self.output_dir / "iterations" / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        params_path = iteration_dir / "params.json"
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        screenshot_path = iteration_dir / "laya_capture.png"
        request_path = iteration_dir / "capture_request.json"
        request = {**self.capture_config, "paramsPath": str(params_path)}
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        capture_command = self.capture_config.get("command") or self.command
        if self.dry_run or not capture_command:
            return {
                "status": "dry_run",
                "params_path": str(params_path),
                "capture_request_path": str(request_path),
                "screenshots": [],
            }

        completed = subprocess.run(
            [*capture_command, str(request_path), str(screenshot_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return {
            "status": "ok" if completed.returncode == 0 and screenshot_path.exists() else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "params_path": str(params_path),
            "capture_request_path": str(request_path),
            "screenshots": [str(screenshot_path)] if screenshot_path.exists() else [],
        }
