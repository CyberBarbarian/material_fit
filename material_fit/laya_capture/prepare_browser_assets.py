from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


SUPPORTED_SOURCE_SUFFIXES = {".tga"}
CACHE_DIR_NAME = ".material_fit_browser_assets"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare browser-decodable assets for the Laya runtime renderer.")
    parser.add_argument("--project-root", required=True, help="Laya project root.")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    converted = prepare_browser_assets(project_root)
    print(json.dumps({"ok": True, "converted": [str(path) for path in converted]}, ensure_ascii=False, indent=2))
    return 0


def prepare_browser_assets(project_root: Path) -> list[Path]:
    if not project_root.exists():
        raise FileNotFoundError(project_root)
    converted: list[Path] = []
    cache_root = project_root / CACHE_DIR_NAME
    for source in sorted(project_root.rglob("*")):
        if not source.is_file():
            continue
        if CACHE_DIR_NAME in source.parts:
            continue
        if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        relative = source.relative_to(project_root)
        output = cache_root / relative.with_suffix(relative.suffix + ".png")
        if output.exists() and output.stat().st_mtime >= source.stat().st_mtime:
            converted.append(output)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.convert("RGBA").save(output, "PNG")
        converted.append(output)
    return converted


def browser_asset_for(project_root: Path, asset_path: Path) -> Path | None:
    try:
        relative = asset_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return None
    if asset_path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
        return None
    candidate = project_root / CACHE_DIR_NAME / relative.with_suffix(relative.suffix + ".png")
    return candidate if candidate.exists() else None


if __name__ == "__main__":
    raise SystemExit(main())
