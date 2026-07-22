"""Small filesystem helpers shared by Stage 2 experiment modules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def iteration_count(path: Path) -> int:
    payload = read_json(path)
    rows = payload if isinstance(payload, list) else payload.get("iterations", [])
    return len(rows) if isinstance(rows, list) else 0


__all__ = [
    "image_size",
    "iteration_count",
    "read_json",
    "sha256_file",
    "write_json",
]
