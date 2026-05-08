"""Native screen-region picker, wrapping the existing CLI overlay.

Spawns ``region_picker_helper.py`` as a short-lived subprocess so the
fullscreen tkinter overlay never collides with the uvicorn event loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


HELPER_PATH = Path(__file__).with_name("region_picker_helper.py")


def pick_region(
    *,
    timeout_seconds: float = 600.0,
    laya_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the overlay and return the picked region.

    When ``laya_window`` is provided ({"process_pattern", "title_pattern"}),
    we also look up the Laya editor window's *current* rectangle at the
    moment the user finishes picking, and return both ``laya_window_rect``
    and a precomputed ``anchor`` dict expressing the picked region as
    offsets from the Laya window's top-left. This is the foundation
    for the "anchor capture region to Laya window" feature — by
    capturing the offsets at pick time, later auto-adjust runs survive
    the user dragging or resizing the Laya editor.
    """

    args = [sys.executable, str(HELPER_PATH)]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return {"region": None, "error": "region picker timed out"}
    except FileNotFoundError as exc:
        return {"region": None, "error": f"helper not found: {exc}"}

    if proc.returncode not in (0, 1):
        return {
            "region": None,
            "error": (proc.stderr or "").strip() or f"helper exit {proc.returncode}",
        }

    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"region": None, "error": "helper returned non-JSON"}
    if not isinstance(payload, dict):
        return {"region": None, "error": "helper returned non-object"}

    region = payload.get("region")
    if isinstance(region, dict) and isinstance(laya_window, dict):
        try:
            from tools.material_fit.laya.window_focus import (
                FocusTarget,
                get_laya_window_rect,
            )
            rect = get_laya_window_rect(
                FocusTarget(
                    process_pattern=str(laya_window.get("process_pattern", "LayaAirIDE")),
                    title_pattern=str(laya_window.get("title_pattern", "")),
                )
            )
        except Exception as exc:  # noqa: BLE001
            payload["laya_window_rect"] = None
            payload["anchor"] = None
            payload["anchor_error"] = f"window lookup raised: {exc}"
            return payload

        if rect is None:
            payload["laya_window_rect"] = None
            payload["anchor"] = None
            payload["anchor_error"] = (
                "no Laya window matched the project's process/title pattern at pick time; "
                "the absolute region was saved but the anchor will fall back to absolute "
                "coords if the Laya window moves later"
            )
            return payload

        payload["laya_window_rect"] = rect.to_dict()
        payload["anchor"] = {
            "offset_x": int(region["x"]) - int(rect.left),
            "offset_y": int(region["y"]) - int(rect.top),
            "width": int(region["width"]),
            "height": int(region["height"]),
        }
    return payload
