from __future__ import annotations

import math
from io import BytesIO
from typing import Any


DEFAULT_VISUAL_QUALITY_GUARD: dict[str, Any] = {
    "enabled": True,
    "min_foreground_pixels": 128,
    "min_unique_foreground_rgb": 32,
    "min_rgb_range": 16,
    "alpha_threshold": 0,
    "max_sample_pixels": 120000,
}


def default_visual_quality_guard() -> dict[str, Any]:
    return dict(DEFAULT_VISUAL_QUALITY_GUARD)


def visual_quality_guard_enabled(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    return _bool_config(config.get("enabled"), False)


def analyze_png_capture_quality(image_bytes: bytes, guard_config: Any) -> dict[str, Any]:
    """Return a small foreground/color-diversity report for a posted PNG.

    The guard is intentionally conservative and opt-in. It catches the known
    failure mode where Laya reports readiness after a missing scene/resource and
    returns an almost solid cyan silhouette instead of a textured asset render.
    """

    if not visual_quality_guard_enabled(guard_config):
        return {"enabled": False, "ok": True}

    cfg = {**DEFAULT_VISUAL_QUALITY_GUARD, **(guard_config if isinstance(guard_config, dict) else {})}
    try:
        from PIL import Image, UnidentifiedImageError
    except Exception as exc:  # pragma: no cover - depends on runtime image stack.
        return {
            "enabled": True,
            "ok": False,
            "reason": "pillow_unavailable",
            "error": str(exc),
        }

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            total_pixels = max(1, width * height)
            max_sample_pixels = max(1, int(cfg.get("max_sample_pixels") or DEFAULT_VISUAL_QUALITY_GUARD["max_sample_pixels"]))
            step = max(1, int(math.ceil(math.sqrt(total_pixels / max_sample_pixels))))
            pixels = rgba.load()
            alpha_threshold = int(cfg.get("alpha_threshold") or 0)
            foreground_sampled = 0
            sampled_total = 0
            unique_rgb: set[tuple[int, int, int]] = set()
            unique_cap = max(1024, int(cfg.get("min_unique_foreground_rgb") or 32) * 4)
            rgb_min = [255, 255, 255]
            rgb_max = [0, 0, 0]

            for y in range(0, height, step):
                for x in range(0, width, step):
                    sampled_total += 1
                    r, g, b, a = pixels[x, y]
                    if a <= alpha_threshold:
                        continue
                    foreground_sampled += 1
                    if len(unique_rgb) < unique_cap:
                        unique_rgb.add((int(r), int(g), int(b)))
                    if r < rgb_min[0]:
                        rgb_min[0] = int(r)
                    if g < rgb_min[1]:
                        rgb_min[1] = int(g)
                    if b < rgb_min[2]:
                        rgb_min[2] = int(b)
                    if r > rgb_max[0]:
                        rgb_max[0] = int(r)
                    if g > rgb_max[1]:
                        rgb_max[1] = int(g)
                    if b > rgb_max[2]:
                        rgb_max[2] = int(b)
    except UnidentifiedImageError as exc:
        return {"enabled": True, "ok": False, "reason": "invalid_png", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "ok": False, "reason": "quality_probe_failed", "error": str(exc)}

    foreground_pixels = int(round(foreground_sampled * (total_pixels / max(1, sampled_total))))
    if foreground_sampled == 0:
        return {
            "enabled": True,
            "ok": False,
            "reason": "no_foreground_pixels",
            "width": width,
            "height": height,
            "foreground_pixels": 0,
            "sample_step": step,
        }

    rgb_range = [rgb_max[index] - rgb_min[index] for index in range(3)]
    min_foreground_pixels = int(cfg.get("min_foreground_pixels") or 128)
    min_unique_rgb = int(cfg.get("min_unique_foreground_rgb") or 32)
    min_rgb_range = int(cfg.get("min_rgb_range") or 16)
    unique_count = len(unique_rgb)
    low_diversity = unique_count < min_unique_rgb and max(rgb_range) < min_rgb_range
    ok = foreground_pixels >= min_foreground_pixels and not low_diversity
    reason = "" if ok else ("low_foreground_rgb_diversity" if low_diversity else "too_few_foreground_pixels")
    return {
        "enabled": True,
        "ok": ok,
        "reason": reason,
        "width": width,
        "height": height,
        "foreground_pixels": foreground_pixels,
        "sampled_foreground_pixels": foreground_sampled,
        "sample_step": step,
        "unique_foreground_rgb": unique_count,
        "rgb_min": rgb_min,
        "rgb_max": rgb_max,
        "rgb_range": rgb_range,
        "thresholds": {
            "min_foreground_pixels": min_foreground_pixels,
            "min_unique_foreground_rgb": min_unique_rgb,
            "min_rgb_range": min_rgb_range,
        },
    }


def _bool_config(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
        return default
    return bool(value)
