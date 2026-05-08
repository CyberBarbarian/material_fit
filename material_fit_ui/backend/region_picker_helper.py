"""Spawn a fullscreen Tk overlay so the user can drag a screen rectangle.

Run as a one-shot subprocess by ``region_picker.pick_region`` to keep tkinter
out of the long-running uvicorn process. We reuse ``select_region_interactively``
from ``tools.material_fit.vision.screen_capture`` so the picker UX (overlay,
crosshair cursor, hint text, Esc to cancel) is identical to the CLI workflow.

stdout payload (JSON, single line):
    {"region": {"x": int, "y": int, "width": int, "height": int}}
or on cancel / error:
    {"region": null, "error": "<msg>"}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    try:
        from tools.material_fit.vision.screen_capture import select_region_interactively
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"region": None, "error": f"import failed: {exc}"}))
        return 2

    try:
        region = select_region_interactively()
    except RuntimeError as exc:
        sys.stdout.write(json.dumps({"region": None, "error": str(exc)}))
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"region": None, "error": f"picker failed: {exc}"}))
        return 3

    sys.stdout.write(
        json.dumps(
            {
                "region": {
                    "x": int(region.x),
                    "y": int(region.y),
                    "width": int(region.width),
                    "height": int(region.height),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
