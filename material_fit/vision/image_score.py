from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path
from threading import Lock
from typing import Any

_REFERENCE_IMAGE_CACHE_MAX = 32
_REFERENCE_IMAGE_CACHE: OrderedDict[tuple[str, str, int, int], Any] = OrderedDict()
_REFERENCE_IMAGE_CACHE_LOCK = Lock()


def score_images(reference_path: str | Path, candidate_path: str | Path, mask_path: str | Path | None = None) -> dict[str, Any]:
    """Compare two images and return a lower-is-better score.

    Pillow is used when available. If it is not installed, the framework returns
    a structured pending result so the rest of the pipeline can still be wired.
    """

    try:
        from PIL import Image
    except ImportError:
        return {"score": math.inf, "status": "pending", "reason": "Pillow is not installed"}

    reference = _load_rgba_image(reference_path)
    candidate = _load_rgba_image(candidate_path)
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


def load_rgba_pair(
    reference_path: str | Path,
    candidate_path: str | Path,
    mask_path: str | Path | None = None,
    *,
    reference_cache_key: str | None = None,
):
    """Load a reference/candidate/mask image tuple with consistent sizes.

    This helper intentionally keeps Pillow imports local so the framework can be
    imported even on machines where image dependencies have not been installed
    yet. Callers should catch ImportError and return a structured pending result.
    """

    from PIL import Image

    reference = _load_rgba_image(reference_path, cache_key=reference_cache_key)
    candidate = _load_rgba_image(candidate_path)
    if reference.size != candidate.size:
        candidate = candidate.resize(reference.size)

    mask = Image.open(mask_path).convert("L") if mask_path else None
    if mask and mask.size != reference.size:
        mask = mask.resize(reference.size)
    return reference, candidate, mask


def _load_rgba_image(path: str | Path, *, cache_key: str | None = None):
    from PIL import Image

    image_path = Path(path)
    if cache_key:
        cached = _load_cached_rgba_image(image_path, cache_key=cache_key)
        if cached is not None:
            return cached

    if image_path.suffix.lower() != ".rgba":
        return Image.open(image_path).convert("RGBA")

    sidecar = _raw_rgba_sidecar_path(image_path)
    metadata = _read_raw_rgba_metadata(sidecar)
    width = int(metadata["width"])
    height = int(metadata["height"])
    raw = image_path.read_bytes()
    expected = width * height * 4
    if len(raw) != expected:
        raise ValueError(f"raw RGBA byte count mismatch for {image_path}: got {len(raw)}, expected {expected}")
    return Image.frombytes("RGBA", (width, height), raw)


def _load_cached_rgba_image(path: Path, *, cache_key: str):
    cache_identity = _reference_cache_identity(path, cache_key)
    if cache_identity is None:
        return None
    with _REFERENCE_IMAGE_CACHE_LOCK:
        cached = _REFERENCE_IMAGE_CACHE.get(cache_identity)
        if cached is not None:
            _REFERENCE_IMAGE_CACHE.move_to_end(cache_identity)
            return cached.copy()

    loaded = _load_rgba_image(path, cache_key=None)
    with _REFERENCE_IMAGE_CACHE_LOCK:
        _REFERENCE_IMAGE_CACHE[cache_identity] = loaded.copy()
        _REFERENCE_IMAGE_CACHE.move_to_end(cache_identity)
        while len(_REFERENCE_IMAGE_CACHE) > _REFERENCE_IMAGE_CACHE_MAX:
            _REFERENCE_IMAGE_CACHE.popitem(last=False)
    return loaded


def _reference_cache_identity(path: Path, cache_key: str) -> tuple[str, str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (cache_key, str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))


def _raw_rgba_sidecar_path(path: Path) -> Path:
    candidates = [
        path.with_suffix(path.suffix + ".json"),
        path.with_suffix(".json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"raw RGBA sidecar not found for {path}")


def _read_raw_rgba_metadata(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    width = payload.get("width")
    height = payload.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError(f"invalid raw RGBA metadata in {path}")
    if payload.get("format") not in (None, "raw_rgba"):
        raise ValueError(f"unsupported raw image format in {path}: {payload.get('format')!r}")
    return payload
