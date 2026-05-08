from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from ..shared.models import ShaderDefine, ShaderInfo, ShaderParam


_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse_laya_shader(path: str | Path) -> ShaderInfo:
    """Parse the Laya Shader3D metadata needed by the fitting tool.

    The parser intentionally focuses on the configuration area: shader name,
    ``uniformMap`` parameters and ``defines``. GLSL code is left untouched.
    """

    shader_path = Path(path)
    text = shader_path.read_text(encoding="utf-8")
    info = ShaderInfo(path=shader_path, name=_parse_laya_shader_name(text))

    uniform_map = _extract_named_block(text, "uniformMap")
    if uniform_map:
        info.params = _parse_laya_uniform_map(uniform_map)

    defines_block = _extract_named_block(text, "defines")
    if defines_block:
        info.defines = _parse_laya_defines(defines_block)

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


def _parse_laya_shader_name(text: str) -> str:
    match = re.search(r"name\s*:\s*\"([^\"]+)\"", text)
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


def _parse_laya_uniform_map(block: str) -> list[ShaderParam]:
    params: list[ShaderParam] = []
    for name, body in _iter_object_entries(block):
        param_type = _read_field(body, "type") or "Unknown"
        default = _parse_value(_read_field(body, "default"))
        range_value = _parse_value(_read_field(body, "range"))
        hidden = _parse_string(_read_field(body, "hidden"))
        range_min = None
        range_max = None
        if isinstance(range_value, list) and len(range_value) >= 2:
            range_min = _try_float(range_value[0])
            range_max = _try_float(range_value[1])
        params.append(
            ShaderParam(
                name=name,
                param_type=str(param_type),
                default=default,
                range_min=range_min,
                range_max=range_max,
                hidden=hidden,
                source="laya_uniformMap",
            )
        )
    return params


def _parse_laya_defines(block: str) -> list[ShaderDefine]:
    defines: list[ShaderDefine] = []
    for name, body in _iter_object_entries(block):
        defines.append(
            ShaderDefine(
                name=name,
                define_type=str(_read_field(body, "type") or "bool"),
                default=_parse_value(_read_field(body, "default")),
                position=_parse_string(_read_field(body, "position")),
            )
        )
    return defines


def _iter_object_entries(block: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    pattern = re.compile(r"\b(?P<name>\w+)\s*:\s*\{", re.MULTILINE)
    pos = 0
    while True:
        match = pattern.search(block, pos)
        if not match:
            break
        start = match.end() - 1
        depth = 0
        end = start
        for index in range(start, len(block)):
            if block[index] == "{":
                depth += 1
            elif block[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        entries.append((match.group("name"), block[start + 1:end]))
        pos = end + 1
    return entries


def _read_field(body: str, field_name: str) -> Optional[str]:
    # Order matters: try bracketed/quoted forms BEFORE the [^,\n}]+ catch-all
    # so values like ``default: [1, 1, 1, 1]`` are not split at the first comma.
    match = re.search(
        rf"\b{field_name}\b\s*:\s*(\[[^\]]*\]|\"[^\"]*\"|[^,\n}}]+)",
        body,
    )
    return match.group(1).strip() if match else None


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


def _parse_string(value: Optional[str]) -> Optional[str]:
    parsed = _parse_value(value)
    return parsed if isinstance(parsed, str) else None


def _try_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
