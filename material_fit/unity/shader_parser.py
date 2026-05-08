from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from ..shared.models import ShaderInfo, ShaderParam


_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse_unity_shaderlab(path: str | Path) -> ShaderInfo:
    """Parse a traditional Unity ShaderLab ``Properties`` block.

    This is a first-pass parser for framework wiring. Complex ShaderGraph output
    and non-standard property declarations can be added in later phases.
    """

    shader_path = Path(path)
    text = shader_path.read_text(encoding="utf-8-sig")
    info = ShaderInfo(path=shader_path, name=_parse_unity_shader_name(text))
    properties = _extract_named_block(text, "Properties")
    if not properties:
        return info

    pattern = re.compile(
        r"(?P<name>_\w+)\s*\(\s*\"(?P<display>[^\"]*)\"\s*,\s*"
        r"(?P<type>Range\s*\([^)]*\)|Color|Vector|2D|Cube|Float|Int)\s*\)\s*=\s*"
        r"(?P<default>[^\n{}]+|\([^)]*\))",
        re.MULTILINE,
    )
    for match in pattern.finditer(properties):
        param_type = match.group("type").strip()
        range_min = None
        range_max = None
        range_match = re.match(r"Range\s*\(([^,]+),([^\)]+)\)", param_type)
        if range_match:
            param_type = "Range"
            range_min = _try_float(range_match.group(1))
            range_max = _try_float(range_match.group(2))

        info.params.append(
            ShaderParam(
                name=match.group("name"),
                display_name=match.group("display"),
                param_type=param_type,
                default=_parse_value(match.group("default").strip()),
                range_min=range_min,
                range_max=range_max,
                source="unity_shaderlab",
            )
        )
    return info


def shader_info_to_dict(info: ShaderInfo) -> dict[str, Any]:
    return {
        "path": str(info.path),
        "name": info.name,
        "params": [param.__dict__ for param in info.params],
        "defines": [define.__dict__ for define in info.defines],
    }


def write_shader_info(info: ShaderInfo, output_path: str | Path) -> None:
    Path(output_path).write_text(
        json.dumps(shader_info_to_dict(info), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_unity_shader_name(text: str) -> str:
    match = re.search(r"Shader\s+\"([^\"]+)\"", text)
    return match.group(1) if match else ""


def _extract_named_block(text: str, name: str) -> str:
    match = re.search(rf"\b{name}\b\s*:?\s*\{{", text)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return ""


def _parse_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = value.strip().rstrip(",")
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [_parse_value(part.strip()) for part in value[1:-1].split(",") if part.strip()]
    if value.startswith("(") and value.endswith(")"):
        return [_parse_value(part.strip()) for part in value[1:-1].split(",") if part.strip()]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    if _NUMBER_RE.match(value):
        return float(value) if "." in value else int(value)
    return value


def _try_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
