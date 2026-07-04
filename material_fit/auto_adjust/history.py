from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any


def load_warm_start_history(
    auto_dir: Path,
    *,
    limit: int,
) -> list[tuple[dict[str, Any], float]]:
    """Scan ``auto_adjust/iter_*/`` for completed ``(params, fit_score)`` pairs."""

    if limit <= 0 or not auto_dir.is_dir():
        return []
    out: list[tuple[int, dict[str, Any], float]] = []
    for entry in auto_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("iter_"):
            continue
        try:
            idx = int(entry.name[len("iter_"):])
        except ValueError:
            continue
        decision_path = entry / "decision.json"
        if not decision_path.exists():
            continue
        try:
            decision = json.loads(decision_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(decision, dict):
            continue
        params = _embedded_score_aligned_params(decision)
        if params is None:
            params_path = entry / "candidate" / "params.json"
            if not params_path.exists():
                continue
            try:
                params = json.loads(params_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(params, dict):
                continue
        fit_score = decision.get("fit_score_before")
        if not isinstance(fit_score, (int, float)) or not math.isfinite(float(fit_score)):
            continue
        out.append((idx, params, float(fit_score)))
    out.sort(key=lambda item: item[0])
    return [(params, fit_score) for _, params, fit_score in out[-limit:]]


def load_elite_archive_warm_start_history(
    auto_dir: Path,
    *,
    limit: int,
) -> list[tuple[dict[str, Any], float]]:
    """Load top scored candidates from ``optimizer_candidate_archive.json``."""

    if limit <= 0:
        return []
    archive_path = auto_dir / "optimizer_candidate_archive.json"
    if not archive_path.exists():
        return []
    try:
        payload = json.loads(archive_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    out: list[tuple[dict[str, Any], float]] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        fit_score = item.get("fit_score")
        if not isinstance(fit_score, (int, float)) or not math.isfinite(float(fit_score)):
            continue
        params = _embedded_score_aligned_params(item)
        if params is None:
            params_path = _resolve_archive_params_path(auto_dir, item)
            if params_path is None:
                continue
            try:
                params = json.loads(params_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(params, dict):
                continue
        out.append((params, float(fit_score)))
        if len(out) >= limit:
            break
    return out


def _embedded_score_aligned_params(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("scored_params", "candidate_params"):
        value = payload.get(key)
        if isinstance(value, dict):
            return copy.deepcopy(value)
    return None


def _resolve_archive_params_path(auto_dir: Path, candidate: dict[str, Any]) -> Path | None:
    raw_path = candidate.get("params_path")
    candidates: list[Path] = []
    if isinstance(raw_path, str) and raw_path.strip():
        params_path = Path(raw_path)
        if params_path.is_absolute():
            candidates.append(params_path)
        else:
            candidates.extend([auto_dir / params_path, auto_dir.parent / params_path])
    iter_id = candidate.get("iter_id")
    if isinstance(iter_id, str) and iter_id.strip():
        candidates.append(auto_dir / iter_id / "candidate" / "params.json")
    iteration = candidate.get("iteration")
    if isinstance(iteration, int):
        candidates.append(auto_dir / f"iter_{iteration:04d}" / "candidate" / "params.json")
    for path in candidates:
        if path.exists():
            return path
    return None
