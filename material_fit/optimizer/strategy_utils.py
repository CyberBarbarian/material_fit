"""Small shared helpers for optimizer strategy implementations."""

from __future__ import annotations

import math
from typing import Any


def _normalize_restart_center_mode(value: object) -> str:
    mode = str(value or "best").strip().lower()
    return mode if mode in {"best", "random", "alternate"} else "best"


def _normalize_warm_start_source(value: object) -> str:
    source = str(value or "elite_archive_first").strip().lower()
    aliases = {
        "archive": "elite_archive_first",
        "archive_first": "elite_archive_first",
        "elite_archive": "elite_archive_first",
        "combined": "elite_archive_first",
        "archive_only": "elite_archive_only",
        "elite_only": "elite_archive_only",
        "history": "iteration_history",
        "iter_history": "iteration_history",
        "iteration": "iteration_history",
        "off": "none",
        "disabled": "none",
        "false": "none",
    }
    source = aliases.get(source, source)
    return source if source in {"elite_archive_first", "elite_archive_only", "iteration_history", "none"} else "elite_archive_first"


def _normalize_restart_population_schedule(value: object) -> str:
    schedule = str(value or "ipop").strip().lower()
    return schedule if schedule in {"ipop", "bipop"} else "ipop"


def _normalize_initial_design_method(value: object) -> str:
    method = str(value or "latin_hypercube").strip().lower()
    return method if method in {"latin_hypercube", "local_coordinate_probe"} else "latin_hypercube"


def _normalize_initial_design_local_step_ratio(value: object) -> float:
    ratio = _optional_float(value)
    if ratio is None or not math.isfinite(ratio) or ratio <= 0.0:
        return 0.05
    return min(float(ratio), 0.5)


def _vector_key(vector: "Any") -> tuple[float, ...]:
    return tuple(round(float(x), 12) for x in vector)


def _coerce_initial_design_pairs(value: object) -> list[tuple[int, dict[str, Any]]]:
    if not isinstance(value, list):
        return []
    out: list[tuple[int, dict[str, Any]]] = []
    for item in value:
        if not (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[1], dict)
        ):
            continue
        try:
            out.append((int(item[0]), dict(item[1])))
        except (TypeError, ValueError):
            continue
    return out


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _clone_params(params: dict[str, Any]) -> dict[str, Any]:
    cloned: dict[str, Any] = {}
    for name, value in params.items():
        if isinstance(value, list):
            cloned[name] = list(value)
        else:
            cloned[name] = value
    return cloned


def _params_key(params: dict[str, Any]) -> tuple[Any, ...]:
    items: list[tuple[str, Any]] = []
    for name in sorted(params):
        value = params[name]
        if isinstance(value, list):
            items.append((name, tuple(round(_to_number(item), 8) for item in value)))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            items.append((name, round(float(value), 8)))
        else:
            items.append((name, value))
    return tuple(items)


def _to_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _isclose(a: float, b: float, *, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol
