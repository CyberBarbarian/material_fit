# Material Fit Inspector

Material Fit Inspector is a local research tool for aligning material appearance across renderers, mainly Unity reference renders and Laya `.lmat` materials.

The project does not train an end-to-end model. It runs a black-box optimization loop:

```text
Unity reference PNGs
  -> write candidate Laya .lmat parameters
  -> ask Laya to render the same views
  -> compare images
  -> propose the next parameter set
```

The current recommended workflow uses Laya Editor scripts to render screenshots from inside the Laya project. That part is required for real closed-loop runs.

## Repository Layout

```text
.
├── README.md
├── Editor/
│   ├── CameraCapture.ts
│   └── CameraCaptureEnv.ts
├── tools/
├── material_fit/
│   ├── fit_material.py
│   ├── fit_cli.py
│   ├── fit_artifacts.py
│   ├── auto_adjust/
│   ├── laya/
│   ├── laya_capture/
│   ├── optimizer/
│   ├── unity/
│   ├── vision/
│   ├── tests/
│   └── docs/
└── material_fit_ui/
    ├── launch.py
    ├── launch.bat
    ├── backend/
    ├── frontend/
    └── requirements.txt
```

Important directories:

- `Editor/`: Laya Editor extension scripts. Copy these into the target Laya project.
- `material_fit/`: optimization, `.lmat` IO, image scoring, render drivers, tests, and docs.
- `material_fit/laya_capture/`: Python side of Laya Editor / runtime capture.
- `material_fit/optimizer/`: black-box optimization strategies.
- `material_fit/vision/`: render comparison and scoring.
- `material_fit_ui/`: local FastAPI + Vue control panel.
- `tools/`: compatibility namespace for legacy `tools.material_fit.*` imports. Keep it.

## What You Need

For basic development:

- Python 3.10+
- Node.js 18+ and npm, only for the UI frontend
- A Laya project containing the target `.lmat`, shader, scene, camera, and target model
- Unity reference renders, usually PNGs from the same view set

Install Python dependencies:

```powershell
python -m pip install -r material_fit_ui/requirements.txt
python -m pip install pytest
```

The UI launcher can run `npm install` for the frontend automatically. To install manually:

```powershell
cd material_fit_ui/frontend
npm install
```

## Laya Project Setup

Real optimization runs require Laya-side scripts. Copy these files from this repository:

```text
Editor/CameraCapture.ts      -> <LayaProject>/assets/Editor/CameraCapture.ts
Editor/CameraCaptureEnv.ts   -> <LayaProject>/assets/Editor/CameraCaptureEnv.ts
Editor/*.meta                -> <LayaProject>/assets/Editor/
```

The scripts watch a command file and render screenshots from Laya Editor. The command file path should normally be:

```text
<LayaProject>/assets/material_fit_capture_command.json
```

In the UI, set `laya_capture_command_path` to that file. The Python side updates it every iteration; the Laya Editor extension detects the new nonce, refreshes the material asset, renders the requested views, and writes PNGs plus a report JSON.

There is also a runtime fallback script:

```text
material_fit/laya_capture/laya/MaterialFitCapture.ts
```

Use that only if you choose the runtime bridge / HTTP capture path. For normal usage, prefer the `Editor/CameraCapture*.ts` editor workflow.

## Start The UI

From the repository root:

```powershell
python material_fit_ui/launch.py
```

Useful options:

```powershell
python material_fit_ui/launch.py --no-browser
python material_fit_ui/launch.py --backend-only
python material_fit_ui/launch.py --frontend-only
```

On Windows you can also run:

```text
material_fit_ui/launch.bat
```

The UI is the recommended entrypoint for creating a project, selecting files, running preanalysis, running the Laya refresh probe, starting optimization jobs, and inspecting iteration images.

## Run From CLI

Use module mode from the repository root:

```powershell
python -m tools.material_fit.fit_material --help
```

Do not run `python material_fit/fit_material.py` directly; the package uses relative imports and the compatibility namespace.

A typical CLI run looks like this:

```powershell
python -m tools.material_fit.fit_material `
  --config material_fit/output/<project_id>/runs/<run_id>/fit_config.json `
  --auto-adjust `
  --iterations 100 `
  --target-score 0.98 `
  --optimizer semantic_group `
  --fit-score-mode human_accept `
  --apply-lmat
```

`material_fit/fit_config.example.json` documents the config shape. It is illustrative, not directly runnable; replace all Laya/Unity paths with local paths.

## Expected Speed

If `laya_editor_capture.enabled=true`, each iteration includes:

```text
write .lmat
  -> Laya Editor reimport / refresh
  -> render one or more views
  -> score images
  -> write iteration artifacts
```

For this mode, around 4 seconds per iteration is a normal baseline. For example, 90 iterations in about 6 minutes is roughly 4 seconds per iteration and is not obviously misconfigured.

Parallel candidate evaluation is limited when the workflow shares one `material_fit_capture_command.json`; parallel workers cannot safely write the same command file at the same time. Speed work should focus on persistent renderer processes, reducing reimport/render overhead, or switching to a runtime bridge designed for batched requests.

## Outputs And Files Not To Commit

Generated runtime data is intentionally ignored:

```text
material_fit/output/
material_fit_ui/frontend/node_modules/
material_fit_ui/frontend/dist/
artifacts/
LayaAirIDE-*/
laya_project_minimal/
unity_references/
__pycache__/
.pytest_cache/
.codex/
.agents/
```

Commit source code, tests, docs, and config templates. Do not commit local Laya projects, Unity projects, generated screenshots, optimizer run directories, or machine-specific absolute-path configs.

## Tests

Run:

```powershell
python -m pytest material_fit/tests -q
```

The suite covers `.lmat` IO, scoring, optimizer behavior, UI backend config generation, Laya capture command handling, runtime bridge behavior, and legacy compatibility paths.

## Key Docs

- `material_fit/docs/README.md`: documentation index.
- `material_fit/docs/Project_Architecture.md`: architecture and data flow.
- `material_fit/docs/File_Layout_And_Artifacts.md`: output and artifact layout.
- `material_fit/docs/Laya_Multiview_Capture.md`: Laya Editor and runtime capture details.
- `material_fit/docs/Core_Algorithms_and_Metrics.md`: core algorithms and metrics.
- `material_fit/docs/Scoring_Mechanism_Design.md`: scoring design.
- `material_fit/docs/learned_incremental_optimizer_design.html`: theoretical learned optimizer design.

## Common Problems

### Laya script seems missing

The required Laya Editor scripts are in repository root `Editor/`. Copy them to `<LayaProject>/assets/Editor/`.

### UI runs but optimization cannot capture images

Check:

- `laya_editor_capture.enabled` is true for the editor workflow.
- `laya_capture_command_path` points to `<LayaProject>/assets/material_fit_capture_command.json`.
- `CameraCapture.ts` and `CameraCaptureEnv.ts` are present under `<LayaProject>/assets/Editor/`.
- The Laya scene contains the configured `camera_name` and `target_name`.
- Laya Editor is open and has loaded the extension.

### Iterations are slower than expected

Check how many views are rendered per iteration, whether scene reload is enabled, and whether material reimport waits are large. Shared command-file editor capture is mostly serialized by design.

### Import says `tools.material_fit` is missing

Run commands from the repository root and keep the `tools/` directory. It provides the compatibility namespace.

## Provenance And License

This public repository was prepared from a local `material_fit` workspace and keeps the original upstream history reference:

- Upstream: `https://github.com/mcy233/material_fit.git`
- Current public mirror: `https://github.com/CyberBarbarian/material_fit`

The implementation and design refer to Unity ShaderLab/material workflows, LayaAir Shader3D/material workflows, CMA-ES and warm-start CMA-ES style black-box optimization, SSIM/perceptual image similarity, foreground masking, and multi-view aggregation.

There is currently no explicit `LICENSE` file in this repository. Until a license is added by the repository owner, treat this as source-available research code with provenance notes, not as a formally licensed open-source release.
