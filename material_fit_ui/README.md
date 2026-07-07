# material_fit_ui

This directory contains the local browser UI for Material Fit Inspector:

- FastAPI backend for project configs, jobs, artifacts, and image serving.
- Vue frontend for selecting inputs, launching runs, and reviewing iterations.
- Launch scripts that start backend and frontend together.

Use the repository root [README.md](../README.md) for full environment setup and the recommended fast Laya runtime path.

## Start

From the repository root:

```powershell
python material_fit_ui/launch.py
```

On Windows:

```text
material_fit_ui/launch.bat
```

Useful options:

```powershell
python material_fit_ui/launch.py --no-browser
python material_fit_ui/launch.py --backend-only
python material_fit_ui/launch.py --frontend-only
python material_fit_ui/launch.py --no-npm-install
```

The launcher checks Python backend dependencies, installs frontend packages when needed, starts FastAPI on `127.0.0.1:8000`, and starts Vite on `localhost:5173`.

## Manual Backend

```powershell
python -m pip install -r material_fit_ui/requirements.txt
python -m uvicorn material_fit_ui.backend.main:app --reload --port 8000
```

Run from the repository root so local package imports resolve.

## Manual Frontend

```powershell
cd material_fit_ui/frontend
npm install
npm run dev
```

## Build Frontend

```powershell
cd material_fit_ui/frontend
npm run build
```

The build output is `material_fit_ui/frontend/dist/`.

## Main Subdirectories

```text
material_fit_ui/
├── backend/       # FastAPI routes, project store, job manager, preanalysis
├── frontend/      # Vue application
├── launch.py      # Cross-platform launcher
├── launch.bat     # Windows convenience launcher
└── requirements.txt
```
