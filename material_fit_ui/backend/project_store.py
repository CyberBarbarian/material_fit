"""Project model & on-disk store.

A *project* wraps everything needed to drive `tools.material_fit.fit_material`
end-to-end from the UI:

- ``inputs`` — absolute paths to user-provided shader/.lmat/reference files
  (these can live anywhere on the user's machine, not just inside our repo).
- ``algorithm_config`` — ``max_iterations``, ``target_score``, ``apply_lmat``,
  screen-capture region, etc. We map this 1:1 to the existing CLI flags.
- ``preanalysis`` — cached output of the shader parsers + Unity↔Laya param
  mapping; populated by ``preanalysis.run_preanalysis``.
- ``jobs`` — pointer/log of every fit run kicked off from the UI.

Persistence:

```
tools/material_fit/output/<project_id>/
├── project.json          # this module owns it
├── fit_config.json       # generated on demand from project.json (the CLI eats this)
├── inputs/               # optional copies of small reference assets
├── auto_adjust/          # written by fit_material.py per iteration
├── jobs/<job_id>.json    # job_manager owns these
└── preanalysis.json      # preanalysis module owns
```

We deliberately *do not* delete any of the existing ``case_loader`` paths;
projects coexist with legacy cases (e.g., ``fish_1580_smoke``) which simply
do not have a ``project.json``.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .case_loader import LoaderConfig, _to_rel_posix


PROJECT_FILE = "project.json"
FIT_CONFIG_FILE = "fit_config.json"
PREANALYSIS_FILE = "preanalysis.json"
INPUTS_DIR = "inputs"
JOBS_DIR = "jobs"

_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class ProjectPaths:
    project_dir: Path
    project_json: Path
    fit_config_json: Path
    preanalysis_json: Path
    inputs_dir: Path
    jobs_dir: Path


def project_paths(project_id: str, config: LoaderConfig) -> ProjectPaths:
    project_dir = (config.output_dir / project_id).resolve()
    return ProjectPaths(
        project_dir=project_dir,
        project_json=project_dir / PROJECT_FILE,
        fit_config_json=project_dir / FIT_CONFIG_FILE,
        preanalysis_json=project_dir / PREANALYSIS_FILE,
        inputs_dir=project_dir / INPUTS_DIR,
        jobs_dir=project_dir / JOBS_DIR,
    )


def list_projects(config: LoaderConfig | None = None) -> list[dict[str, Any]]:
    config = config or LoaderConfig()
    if not config.output_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(config.output_dir.iterdir(), key=lambda path: path.name.lower()):
        if not entry.is_dir():
            continue
        project_file = entry / PROJECT_FILE
        if not project_file.exists():
            continue
        data = _read_json(project_file)
        if not isinstance(data, dict):
            continue
        out.append(_summary(data, entry, config))
    return out


def get_project(project_id: str, config: LoaderConfig | None = None) -> dict[str, Any]:
    config = config or LoaderConfig()
    paths = project_paths(project_id, config)
    _ensure_within(paths.project_dir, config.output_dir.resolve())
    if not paths.project_json.exists():
        raise FileNotFoundError(f"project not found: {project_id}")
    data = _read_json(paths.project_json)
    if not isinstance(data, dict):
        raise FileNotFoundError(f"project.json malformed: {project_id}")
    data["_summary"] = _summary(data, paths.project_dir, config)
    return data


def create_project(
    *,
    project_id: str,
    name: str,
    description: str = "",
    config: LoaderConfig | None = None,
) -> dict[str, Any]:
    if not _PROJECT_ID_RE.match(project_id or ""):
        raise ValueError("project id must match [a-zA-Z0-9_-]{1,64}")
    config = config or LoaderConfig()
    paths = project_paths(project_id, config)
    _ensure_within(paths.project_dir, config.output_dir.resolve())
    if paths.project_dir.exists():
        raise FileExistsError(f"project directory already exists: {project_id}")
    paths.project_dir.mkdir(parents=True, exist_ok=False)
    paths.inputs_dir.mkdir(parents=True, exist_ok=True)
    paths.jobs_dir.mkdir(parents=True, exist_ok=True)

    now = _now_iso()
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": project_id,
        "name": name or project_id,
        "description": description or "",
        "created_at": now,
        "updated_at": now,
        "inputs": {
            "unity_shader_path": None,
            "unity_material_params_path": None,
            "unity_reference_image_path": None,
            "laya_shader_path": None,
            "laya_material_lmat_path": None,
            "laya_capture_region": None,
            "laya_capture_dir": None,
            "laya_capture_state_file": None,
            "laya_capture_prefix": "laya_candidate",
            # E-007 (ExperimentLog.md): Laya editor pauses rendering
            # when its window loses focus. Before each .lmat write
            # and each capture, the pipeline brings this window to
            # the foreground. Set process_pattern='' to disable.
            "laya_window": {
                "process_pattern": "LayaAirIDE",
                "title_pattern": "",
                "settle_ms": 250,
            },
            # E-008 follow-up: anchor the capture region to the Laya
            # window's top-left corner so dragging/resizing the editor
            # between auto-adjust runs doesn't break the screenshot.
            # ``offset_x/y`` and ``width/height`` are populated when the
            # user picks a region — we capture the Laya window's
            # current rect at that moment and store the relative
            # offsets. ``enabled`` defaults to True because there is
            # essentially no downside (we still keep the absolute
            # region as a fallback).
            "laya_capture_anchor": {
                "enabled": True,
                "offset_x": 0,
                "offset_y": 0,
                "width": 0,
                "height": 0,
            },
        },
        "algorithm_config": {
            "max_iterations": 6,
            "target_score": 0.5,
            "apply_lmat": True,
            "capture_screen_after_apply": True,
            "rerender_wait_ms": 1500,
            "use_capture_contract": False,
            "dry_run": False,
            "fit_score_mode": "perceptual",
            # E-007: run the magenta-probe refresh check before each
            # auto-adjust run, to guarantee Laya is actually re-rendering
            # after .lmat writes. Saves debugging hours when Laya is in
            # background or some other window stole focus.
            "laya_refresh_check": True,
            # E-006 (ExperimentLog.md): optimizer is now pluggable.
            # 'heuristic' is the default safe path. Switch to 'cma_warm'
            # once you have ≥2 prior heuristic iterations to seed the
            # warm-start MGD; 'cma_cold' for vanilla CMA-ES with no
            # prior. UI surface is in AlgoConfigView.vue.
            "optimizer": "heuristic",
            "cma_es": {
                "mode": "warm",
                "warm_start_iters": 12,
                "population_size": None,
                "sigma": None,
                "seed": None,
                # E-010: blend channel-level adjustment_hints into each
                # CMA-ES proposal. 0 disables, 0.30 is the recommended
                # default, > 0.5 is heavy expert-driven exploration.
                "hint_bias_mix_ratio": 0.30,
            },
        },
        "manual_param_mapping": {},
        "llm_config": {
            "enabled": False,
            "provider": None,
            "note": "Future: LLM will analyze each iteration's diff and propose param adjustments.",
        },
        "preanalysis_path": None,
        "active_job_id": None,
        "last_job_id": None,
    }
    save_project(data, config=config)
    return data


def save_project(data: dict[str, Any], config: LoaderConfig | None = None) -> dict[str, Any]:
    config = config or LoaderConfig()
    project_id = data.get("id")
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        raise ValueError("project.json missing valid 'id'")
    paths = project_paths(project_id, config)
    _ensure_within(paths.project_dir, config.output_dir.resolve())
    if not paths.project_dir.exists():
        raise FileNotFoundError(f"project dir missing: {project_id}")
    data = dict(data)
    data.pop("_summary", None)
    data["updated_at"] = _now_iso()
    paths.project_json.parent.mkdir(parents=True, exist_ok=True)
    paths.project_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def patch_project(project_id: str, patch: dict[str, Any], config: LoaderConfig | None = None) -> dict[str, Any]:
    config = config or LoaderConfig()
    current = get_project(project_id, config)
    current.pop("_summary", None)
    merged = _deep_merge(current, patch)
    return save_project(merged, config=config)


def delete_project(project_id: str, config: LoaderConfig | None = None) -> dict[str, Any]:
    """Move the project dir into an ``output/.trash/`` sibling so it's recoverable."""

    config = config or LoaderConfig()
    paths = project_paths(project_id, config)
    _ensure_within(paths.project_dir, config.output_dir.resolve())
    if not paths.project_dir.exists():
        raise FileNotFoundError(f"project not found: {project_id}")
    trash_root = config.output_dir / ".trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = trash_root / f"{project_id}_{stamp}_{secrets.token_hex(3)}"
    shutil.move(str(paths.project_dir), str(target))
    return {"id": project_id, "trash_path": _to_rel_posix(target, config.project_root)}


def derive_fit_config(project_id: str, config: LoaderConfig | None = None) -> dict[str, Any]:
    """Generate a CLI-compatible ``fit_config.json`` payload from project state.

    The returned dict mirrors ``tools/material_fit/fit_config.example.json``
    schema, so it can be written and fed straight into ``fit_material.py``.
    """

    config = config or LoaderConfig()
    project = get_project(project_id, config)
    inputs = project.get("inputs", {})
    algo = project.get("algorithm_config", {})

    def _abs(value: Any) -> str:
        return str(value) if isinstance(value, str) and value else ""

    laya_shader = _abs(inputs.get("laya_shader_path"))
    laya_lmat = _abs(inputs.get("laya_material_lmat_path"))
    if not laya_shader or not laya_lmat:
        raise ValueError(
            "project missing required inputs: laya_shader_path and laya_material_lmat_path",
        )

    paths = project_paths(project_id, config)
    # ``fit_material._resolve_path`` treats relative paths as relative to its
    # own assumed project root (config_path.resolve().parents[2]), which is
    # wrong when the config is nested under output/<project>/. Always emit
    # absolute paths so fit_material uses them verbatim.
    output_dir_abs = str(paths.project_dir.resolve())

    image_pairs: list[dict[str, str]] = []
    ref = _abs(inputs.get("unity_reference_image_path"))
    if ref:
        image_pairs.append(
            {
                "reference": ref,
                "candidate": "latest",
                "candidate_dir": _abs(inputs.get("laya_capture_dir"))
                or str((config.image_root / "vision" / "test_image").resolve()),
                "candidate_prefix": _abs(inputs.get("laya_capture_prefix")) or "laya_candidate",
            }
        )

    optimizer_value = str(algo.get("optimizer", "heuristic")).strip().lower()
    if optimizer_value not in ("heuristic", "cma_cold", "cma_warm"):
        optimizer_value = "heuristic"
    raw_cma_es = algo.get("cma_es") if isinstance(algo.get("cma_es"), dict) else {}
    raw_mix = raw_cma_es.get("hint_bias_mix_ratio", 0.30)
    try:
        mix_ratio_value = float(raw_mix) if raw_mix is not None else 0.30
    except (TypeError, ValueError):
        mix_ratio_value = 0.30
    if mix_ratio_value < 0.0:
        mix_ratio_value = 0.0
    if mix_ratio_value > 1.0:
        mix_ratio_value = 1.0
    cma_es_payload: dict[str, Any] = {
        "mode": str(raw_cma_es.get("mode", "warm")).strip().lower() or "warm",
        "warm_start_iters": int(raw_cma_es.get("warm_start_iters", 12) or 0),
        "population_size": _coerce_optional_int(raw_cma_es.get("population_size")),
        "sigma": _coerce_optional_float(raw_cma_es.get("sigma")),
        "seed": _coerce_optional_int(raw_cma_es.get("seed")),
        # E-010: persisted to fit_config.json so the subprocess
        # picks up the mix ratio even if no CLI override is set.
        "hint_bias_mix_ratio": mix_ratio_value,
    }

    fit_config: dict[str, Any] = {
        "case_name": project.get("id"),
        "laya_shader_path": laya_shader,
        "laya_material_path": laya_lmat,
        "unity_shader_path": _abs(inputs.get("unity_shader_path")),
        "unity_material_params_path": _abs(inputs.get("unity_material_params_path")),
        "image_pairs": image_pairs,
        "auto_adjust_target_score": float(algo.get("target_score", 0.5)),
        "capture_screen_after_apply": bool(algo.get("capture_screen_after_apply", False)),
        "rerender_wait_ms": int(algo.get("rerender_wait_ms", 1200)),
        "screen_capture": {
            "capture_dir": _abs(inputs.get("laya_capture_dir"))
            or str((config.image_root / "vision" / "test_image").resolve()),
            "state_file": _abs(inputs.get("laya_capture_state_file")) or "",
            "prefix": _abs(inputs.get("laya_capture_prefix")) or "laya_candidate",
            "region": _format_region(inputs.get("laya_capture_region")),
            # E-012: cap the rolling ``laya_candidate_NN.png`` pool so
            # auto-adjust runs don't accumulate gigabytes of historical
            # captures. ``0`` keeps everything (legacy behavior); the
            # default 30 retains roughly the last N iterations across
            # all recent runs, which is enough for the UI's iter detail
            # panel and post-mortem diagnostics.
            "max_keep": int(inputs.get("laya_capture_max_keep") or 30),
        },
        "output_dir": output_dir_abs,
        "dry_run": bool(algo.get("dry_run", False)),
        "render_command": [],
        "laya_capture": {},
        "fit_score_mode": str(algo.get("fit_score_mode", "linear")).lower(),
        "optimizer": optimizer_value,
        "cma_es": cma_es_payload,
        "laya_window": _normalize_laya_window(inputs.get("laya_window")),
        "laya_capture_anchor": _normalize_capture_anchor(
            inputs.get("laya_capture_anchor"),
            inputs.get("laya_window"),
        ),
    }
    return fit_config


def write_fit_config(project_id: str, config: LoaderConfig | None = None) -> Path:
    config = config or LoaderConfig()
    fit_config = derive_fit_config(project_id, config)
    paths = project_paths(project_id, config)
    paths.fit_config_json.parent.mkdir(parents=True, exist_ok=True)
    paths.fit_config_json.write_text(
        json.dumps(fit_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths.fit_config_json


def _summary(data: dict[str, Any], project_dir: Path, config: LoaderConfig) -> dict[str, Any]:
    inputs = data.get("inputs") or {}
    required_filled = all(
        bool(inputs.get(key))
        for key in ("laya_shader_path", "laya_material_lmat_path")
    )
    optional_filled = sum(
        1
        for key in (
            "unity_shader_path",
            "unity_material_params_path",
            "unity_reference_image_path",
            "laya_capture_region",
        )
        if inputs.get(key)
    )
    auto_dir = project_dir / "auto_adjust"
    auto_iters = 0
    if auto_dir.exists():
        for entry in auto_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("iter_"):
                auto_iters += 1
    return {
        "id": data.get("id"),
        "name": data.get("name") or data.get("id"),
        "description": data.get("description") or "",
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "inputs_required_filled": required_filled,
        "inputs_optional_filled": optional_filled,
        "preanalysis_present": bool(data.get("preanalysis_path"))
        and (config.project_root / data.get("preanalysis_path")).exists()
        if isinstance(data.get("preanalysis_path"), str)
        else False,
        "iterations_count": auto_iters,
        "active_job_id": data.get("active_job_id"),
        "last_job_id": data.get("last_job_id"),
        "output_dir": _to_rel_posix(project_dir, config.project_root),
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_capture_anchor(value: Any, laya_window_value: Any) -> dict[str, Any]:
    """Normalize the project's laya_capture_anchor block into a fit_config dict.

    Pulls ``process_pattern`` / ``title_pattern`` from the *separate*
    ``laya_window`` block — they are the same identifiers as for
    focusing, so we don't make the user enter them twice.
    """
    if not isinstance(value, dict):
        value = {}
    window = laya_window_value if isinstance(laya_window_value, dict) else {}
    return {
        "enabled": bool(value.get("enabled", False)),
        "offset_x": int(value.get("offset_x", 0) or 0),
        "offset_y": int(value.get("offset_y", 0) or 0),
        "width": int(value.get("width", 0) or 0),
        "height": int(value.get("height", 0) or 0),
        "process_pattern": str(window.get("process_pattern", "LayaAirIDE")),
        "title_pattern": str(window.get("title_pattern", "")),
    }


def _normalize_laya_window(value: Any) -> dict[str, Any]:
    """Normalize the project's laya_window block into a fit_config-ready dict.

    Always returns a dict with all three keys filled in (so fit_material's
    ``_build_focus_callback`` can read it without further None-checks).
    Empty ``process_pattern`` means "disable focus", which is preserved.
    """
    if not isinstance(value, dict):
        value = {}
    return {
        "process_pattern": str(value.get("process_pattern", "LayaAirIDE")),
        "title_pattern": str(value.get("title_pattern", "")),
        "settle_ms": int(value.get("settle_ms", 250) or 0),
    }


def _format_region(region: Any) -> str:
    if not isinstance(region, dict):
        return ""
    keys = ("x", "y", "width", "height")
    if not all(k in region for k in keys):
        return ""
    try:
        x, y, w, h = (int(region[k]) for k in keys)
    except (TypeError, ValueError):
        return ""
    return f"{x},{y},{w},{h}"


def _ensure_within(target: Path, root: Path) -> None:
    try:
        target.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path {target} outside of {root}") from exc


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if (
            isinstance(value, dict)
            and isinstance(out.get(key), dict)
            and key not in {"laya_capture_region", "laya_capture_anchor"}
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
