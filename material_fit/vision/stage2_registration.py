"""Frozen canvas registration applied after renderer-faithful Stage 2 capture."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


def apply_frozen_stage2_registration(
    *,
    raw_dir: Path,
    output_dir: Path,
    views: Iterable[dict[str, Any]],
    registration: dict[str, Any],
) -> dict[str, Any]:
    if registration.get("mode") != "frozen_per_view_similarity":
        raise ValueError("unsupported Stage 2 registration mode")
    output_size = tuple(int(value) for value in registration.get("output_size", ()))
    if len(output_size) != 2 or min(output_size) <= 0:
        raise ValueError("Stage 2 registration requires a positive output_size")
    transforms = registration.get("transforms")
    if not isinstance(transforms, list):
        raise ValueError("Stage 2 registration requires transforms")
    by_view = {str(item.get("view_id")): item for item in transforms}
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for view in views:
        view_id = str(view["view_id"])
        transform = by_view.get(view_id)
        if transform is None:
            raise ValueError(f"Stage 2 registration has no transform for {view_id}")
        source_path = raw_dir / str(view["candidate_file_name"])
        output_path = output_dir / str(view["candidate_file_name"])
        with Image.open(source_path) as source:
            rendered = register_canvas(
                source.convert("RGB"),
                output_size=output_size,
                scale=float(transform["scale"]),
                dx=float(transform["dx"]),
                dy=float(transform["dy"]),
            )
        rendered.save(output_path)
        reports.append(
            {
                "view_id": view_id,
                "source_path": str(source_path),
                "output_path": str(output_path),
                "scale": float(transform["scale"]),
                "dx": float(transform["dx"]),
                "dy": float(transform["dy"]),
                "source_sha256": _sha256(source_path),
                "output_sha256": _sha256(output_path),
            }
        )
    return {
        "contract": "material_fit_stage2_frozen_registration_v1",
        "mode": registration["mode"],
        "output_size": list(output_size),
        "renderer_environment_changed": False,
        "per_proposal_registration": False,
        "views": reports,
    }


def register_canvas(
    image: Image.Image,
    *,
    output_size: tuple[int, int],
    scale: float,
    dx: float,
    dy: float,
) -> Image.Image:
    if scale <= 0.0:
        raise ValueError("Stage 2 registration scale must be positive")
    source = image.convert("RGB")
    if source.size != output_size:
        raise ValueError(f"Stage 2 raw capture size {source.size} != {output_size}")
    width, height = output_size
    inverse = 1.0 / scale
    center_x = width * 0.5
    center_y = height * 0.5
    matrix = (
        inverse,
        0.0,
        center_x - (center_x + dx) * inverse,
        0.0,
        inverse,
        center_y - (center_y + dy) * inverse,
    )
    return source.transform(
        output_size,
        Image.Transform.AFFINE,
        matrix,
        resample=Image.Resampling.BICUBIC,
        fillcolor="white",
    )


def reference_in_source_frame(
    image: Image.Image,
    *,
    output_size: tuple[int, int],
    scale: float,
    dx: float,
    dy: float,
) -> Image.Image:
    """Map a registered reference back into the renderer's raw canvas frame."""

    if scale <= 0.0:
        raise ValueError("Stage 2 registration scale must be positive")
    rgba = image.convert("RGBA")
    source = Image.new("RGB", rgba.size, "white")
    source.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
    return register_canvas(
        source,
        output_size=output_size,
        scale=1.0 / scale,
        dx=-dx / scale,
        dy=-dy / scale,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "apply_frozen_stage2_registration",
    "reference_in_source_frame",
    "register_canvas",
]
