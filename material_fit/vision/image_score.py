from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def score_images(reference_path: str | Path, candidate_path: str | Path, mask_path: str | Path | None = None) -> dict[str, Any]:
    """Compare two images and return a lower-is-better score.

    Pillow is used when available. If it is not installed, the framework returns
    a structured pending result so the rest of the pipeline can still be wired.
    """

    try:
        from PIL import Image
    except ImportError:
        return {"score": math.inf, "status": "pending", "reason": "Pillow is not installed"}

    reference = Image.open(reference_path).convert("RGBA")
    candidate = Image.open(candidate_path).convert("RGBA")
    if reference.size != candidate.size:
        candidate = candidate.resize(reference.size)

    mask = Image.open(mask_path).convert("L") if mask_path else None
    if mask and mask.size != reference.size:
        mask = mask.resize(reference.size)

    ref_pixels = reference.load()
    cand_pixels = candidate.load()
    mask_pixels = mask.load() if mask else None

    total = 0.0
    count = 0
    width, height = reference.size
    for y in range(height):
        for x in range(width):
            weight = (mask_pixels[x, y] / 255.0) if mask_pixels else 1.0
            if weight <= 0.0:
                continue
            diff = 0.0
            for channel in range(3):
                diff += abs(ref_pixels[x, y][channel] - cand_pixels[x, y][channel]) / 255.0
            total += (diff / 3.0) * weight
            count += 1

    score = total / max(count, 1)
    return {"score": score, "status": "ok", "metric": "rgb_mae", "pixels": count}


def load_rgba_pair(reference_path: str | Path, candidate_path: str | Path, mask_path: str | Path | None = None):
    """Load a reference/candidate/mask image tuple with consistent sizes.

    This helper intentionally keeps Pillow imports local so the framework can be
    imported even on machines where image dependencies have not been installed
    yet. Callers should catch ImportError and return a structured pending result.
    """

    from PIL import Image

    reference = Image.open(reference_path).convert("RGBA")
    candidate = Image.open(candidate_path).convert("RGBA")
    if reference.size != candidate.size:
        candidate = candidate.resize(reference.size)

    mask = Image.open(mask_path).convert("L") if mask_path else None
    if mask and mask.size != reference.size:
        mask = mask.resize(reference.size)
    return reference, candidate, mask
