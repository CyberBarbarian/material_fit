"""FastAPI entrypoint for the Material Fit UI backend.

Run from the project root:

    python -m uvicorn tools.material_fit_ui.backend.main:app --port 8000

The frontend (``tools/material_fit_ui/frontend``) is configured with a
Vite proxy so requests to ``/api/...`` are forwarded here during dev.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Body, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import (
    case_loader,
    file_dialog,
    job_manager,
    preanalysis,
    preflight,
    project_store,
    region_picker,
)
from .case_loader import LoaderConfig


app = FastAPI(title="Material Fit UI", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


def _config() -> LoaderConfig:
    return LoaderConfig()


# ---------- Health ----------


@app.get("/api/health")
def health() -> dict[str, Any]:
    config = _config()
    return {
        "status": "ok",
        "project_root": str(config.project_root),
        "output_dir": str(config.output_dir),
        "output_dir_exists": config.output_dir.exists(),
    }


# ---------- Cases (legacy + project) ----------


@app.get("/api/cases")
def api_list_cases() -> list[dict[str, Any]]:
    return case_loader.list_cases(_config())


@app.get("/api/cases/{case_id}/overview")
def api_case_overview(case_id: str) -> dict[str, Any]:
    try:
        return case_loader.get_case_overview(case_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/iterations")
def api_case_iterations(case_id: str) -> list[dict[str, Any]]:
    try:
        return case_loader.list_iterations(case_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/report")
def api_case_report(case_id: str) -> dict[str, Any]:
    try:
        return case_loader.get_case_report(case_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases/{case_id}/iterations/{iter_id}")
def api_iteration_detail(case_id: str, iter_id: str) -> dict[str, Any]:
    try:
        return case_loader.get_iteration_detail(case_id, iter_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/image")
def api_image(path: str = Query(..., min_length=1, max_length=1024)) -> FileResponse:
    try:
        resolved = case_loader.resolve_image_path(path, _config())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(resolved)


@app.get("/api/files/preview")
def api_files_preview(path: str = Query(..., min_length=1, max_length=2048)) -> FileResponse:
    try:
        resolved = case_loader.resolve_external_preview_path(path, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(resolved)


# ---------- Projects ----------


@app.get("/api/projects")
def api_list_projects() -> list[dict[str, Any]]:
    return project_store.list_projects(_config())


@app.post("/api/projects")
def api_create_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return project_store.create_project(
            project_id=str(payload.get("id", "")),
            name=str(payload.get("name", "") or payload.get("id", "")),
            description=str(payload.get("description", "") or ""),
            config=_config(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str) -> dict[str, Any]:
    try:
        return project_store.get_project(project_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/projects/{project_id}")
def api_patch_project(project_id: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return project_store.patch_project(project_id, patch, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str) -> dict[str, Any]:
    try:
        return project_store.delete_project(project_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------- File picker ----------


@app.post("/api/files/pick")
def api_pick_file(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    payload = payload or {}
    return file_dialog.pick(
        mode=str(payload.get("mode", "open")),
        title=payload.get("title"),
        initial_dir=payload.get("initial_dir"),
        initial_file=payload.get("initial_file"),
        filetypes=payload.get("filetypes"),
    )


@app.post("/api/files/pick_region")
def api_pick_region(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """Pop a fullscreen overlay so the user drags a Laya capture rectangle.

    Optional body: ``{"laya_window": {"process_pattern": str, "title_pattern": str}}``
    — when present, we also look up the Laya window's current rect and
    return ``laya_window_rect`` + a precomputed ``anchor`` (offset_x,
    offset_y, width, height) so the frontend can save it directly into
    ``project.inputs.laya_capture_anchor``. This is the foundation of
    the "anchor capture region to Laya window" mode.

    Returns ``{"region": {...}, "laya_window_rect"?, "anchor"?}`` on success
    or ``{"region": null}`` if the user pressed Esc / the picker was cancelled.
    """

    laya_window = payload.get("laya_window") if isinstance(payload, dict) else None
    return region_picker.pick_region(
        laya_window=laya_window if isinstance(laya_window, dict) else None,
    )


@app.get("/api/files/info")
def api_file_info(path: str = Query(..., min_length=1, max_length=2048)) -> dict[str, Any]:
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}
    try:
        stat = p.stat()
    except OSError as exc:
        return {"path": str(p), "exists": True, "error": str(exc)}
    return {
        "path": str(p),
        "exists": True,
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "name": p.name,
        "suffix": p.suffix,
    }


# ---------- Preanalysis ----------


@app.post("/api/projects/{project_id}/preanalyze")
def api_preanalyze(project_id: str) -> dict[str, Any]:
    try:
        return preanalysis.run_preanalysis(project_id, _config())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"preanalysis failed: {exc}") from exc


@app.get("/api/projects/{project_id}/preanalysis")
def api_get_preanalysis(project_id: str) -> dict[str, Any]:
    result = preanalysis.get_preanalysis(project_id, _config())
    if result is None:
        raise HTTPException(status_code=404, detail="preanalysis not yet run for this project")
    return result


# ---------- Preflight: Laya refresh probe (E-007 / ExperimentLog.md) ----------


@app.post("/api/projects/{project_id}/preflight/laya_refresh")
def api_run_laya_refresh_preflight(
    project_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Run the magenta-probe refresh check.

    Body is optional. Supported override:

    * ``probe_param``: string, defaults to ``"u_BaseColor"``. Use a
      different Color uniform if your shader does not have BaseColor or
      if BaseColor is masked/textured to the point that a magenta probe
      wouldn't visibly change anything (rare; the reason we also write
      ``preflight/baseline.png`` so you can look at the picture).
    """

    probe_param = str(payload.get("probe_param") or "u_BaseColor")
    try:
        return preflight.run_laya_refresh_preflight(
            project_id,
            config=_config(),
            probe_param=probe_param,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"preflight failed: {exc}") from exc


@app.get("/api/projects/{project_id}/preflight/laya_refresh")
def api_get_last_laya_refresh_preflight(project_id: str) -> dict[str, Any]:
    """Return the most recent preflight result for this project, or 404."""
    result = preflight.get_last_preflight(project_id, config=_config())
    if result is None:
        raise HTTPException(status_code=404, detail="no preflight has been run for this project yet")
    return result


@app.put("/api/projects/{project_id}/manual_mapping")
def api_set_manual_mapping(
    project_id: str, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Replace ``manual_param_mapping`` and re-run preanalysis.

    Body: ``{"manual_param_mapping": {"<unity_param_name>": "<laya_param_name>", ...}}``.
    Set the value to an empty string ``""`` to mark a Unity property as
    intentionally unmapped (suppresses fuzzy fallback for that row).
    """

    mapping = payload.get("manual_param_mapping")
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="manual_param_mapping must be an object")
    cleaned: dict[str, str] = {}
    for k, v in mapping.items():
        if not isinstance(k, str):
            continue
        if v is None:
            continue
        if not isinstance(v, str):
            raise HTTPException(status_code=400, detail=f"value for {k!r} must be string or null")
        cleaned[k] = v
    try:
        project_store.patch_project(project_id, {"manual_param_mapping": cleaned}, _config())
        return preanalysis.run_preanalysis(project_id, _config())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"manual mapping save failed: {exc}") from exc


# ---------- Jobs ----------


@app.post("/api/projects/{project_id}/jobs")
def api_start_job(project_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return job_manager.start_job(project_id, config=_config(), overrides=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/jobs")
def api_list_jobs(project_id: str) -> list[dict[str, Any]]:
    try:
        return job_manager.list_jobs(project_id, _config())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict[str, Any]:
    try:
        return job_manager.get_job(job_id, _config())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str) -> dict[str, Any]:
    try:
        return job_manager.cancel_job(job_id, _config())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/log")
def api_job_log(job_id: str, tail_kb: int = 64) -> dict[str, Any]:
    try:
        text = job_manager.get_job_log(job_id, _config(), tail_kb=max(1, min(tail_kb, 1024)))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "tail_kb": tail_kb, "text": text}


# ---------- Errors ----------


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):  # type: ignore[no-untyped-def]
    return JSONResponse(status_code=500, content={"detail": f"internal error: {exc}"})
