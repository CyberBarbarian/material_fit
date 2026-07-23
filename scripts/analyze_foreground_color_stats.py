"""Summarize foreground RGB, saturation, and luminance for PNG directories."""

from __future__ import annotations

import argparse
import colorsys
import json
from pathlib import Path

import numpy as np
from PIL import Image

from material_fit.vision.cross_engine_alignment import foreground_mask


def summarize(root: Path) -> dict[str, object]:
    pixels: list[np.ndarray] = []
    for path in sorted(root.glob("*.png")):
        image = Image.open(path).convert("RGBA")
        mask, _ = foreground_mask(image)
        rgb = np.asarray(image, dtype=np.float32)[:, :, :3] / 255.0
        pixels.append(rgb[mask])
    if not pixels:
        raise ValueError(f"no PNG foreground pixels found: {root}")
    values = np.concatenate(pixels, axis=0)
    hsv = np.asarray([colorsys.rgb_to_hsv(*row) for row in values], dtype=np.float32)
    luma = values @ np.asarray([0.299, 0.587, 0.114], dtype=np.float32)
    return {
        "pixel_count": int(len(values)),
        "rgb_mean": values.mean(axis=0).tolist(),
        "rgb_p10": np.quantile(values, 0.10, axis=0).tolist(),
        "rgb_p50": np.quantile(values, 0.50, axis=0).tolist(),
        "rgb_p90": np.quantile(values, 0.90, axis=0).tolist(),
        "saturation_mean": float(hsv[:, 1].mean()),
        "saturation_p50": float(np.quantile(hsv[:, 1], 0.50)),
        "luma_mean": float(luma.mean()),
        "luma_p10": float(np.quantile(luma, 0.10)),
        "luma_p50": float(np.quantile(luma, 0.50)),
        "luma_p90": float(np.quantile(luma, 0.90)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_dir", type=Path)
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = {
        "reference": summarize(args.reference_dir),
        "candidate": summarize(args.candidate_dir),
    }
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
