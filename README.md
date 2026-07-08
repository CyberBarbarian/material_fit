# Material Fit Inspector

Material Fit Inspector is a local research tool for aligning material appearance across renderers. The main target is:

```text
Unity reference renders
  -> optimize Laya .lmat parameters
  -> render the same views in Laya
  -> compare images
  -> keep proposing better parameters
```

This is not an end-to-end trained model. The current system is a black-box optimizer around a render-and-score loop. New projects default to the no-IDE fast path: a persistent queue daemon plus a long-lived Laya runtime page running in Chromium.

## Repository Layout

```text
.
├── README.md
├── Editor/                         # Optional Laya Editor fallback scripts
├── material_fit/                   # Optimizer, .lmat IO, render bridge, scoring, tests
│   ├── fit_material.py
│   ├── fit_config.example.json
│   ├── auto_adjust/
│   ├── laya/
│   ├── laya_capture/
│   ├── optimizer/
│   ├── unity/
│   ├── vision/
│   ├── tests/
│   └── docs/
├── material_fit_ui/                # FastAPI + Vue local control panel
│   ├── launch.py
│   ├── launch.bat
│   ├── backend/
│   ├── frontend/
│   └── requirements.txt
├── examples/                       # Fish Laya project and reference PNGs
├── scripts/                        # Queue daemon and local renderer launchers
└── tools/                          # Compatibility namespace for module imports
```

Important modules:

- `material_fit/optimizer/`: black-box optimization strategies and parameter encoders.
- `material_fit/laya/`: Laya shader parsing and `.lmat` read/write helpers.
- `material_fit/laya_capture/`: persistent queue daemon, HTTP capture bridge, and local runtime renderer.
- `material_fit/vision/`: image loading, masking, perceptual scoring, and diff analysis.
- `material_fit_ui/`: browser UI for creating projects, deriving configs, launching jobs, and inspecting iterations.
- `scripts/`: operational entrypoints for the fast path.

Keep the `tools/` directory because it preserves compatibility with older configs that refer to `tools.material_fit...`. New commands should use the direct package path, for example `python -m material_fit.fit_material ...` from the repository root.

## Environment

The supported default setup is a Windows local run. You do not need a remote
machine for the included fish example or for normal local optimization.

Required for Windows local runs:

- Windows 10/11.
- Python 3.10+.
- Node.js 18+ and npm.
- Chromium runtime supplied by `playwright-chromium`; the local launcher installs it under ignored `artifacts/real_laya_run/`.
- Pillow, installed through `material_fit_ui/requirements.txt`, for image scoring and browser-compatible `.tga` texture cache generation.
- Laya engine JavaScript files from a local LayaAirIDE install.
- Unity reference PNGs rendered from the target view set.
- A Laya `.lmat` target material and, for real asset runs, the Laya scene/model/shader assets that should be rendered.

On Windows, the local renderer first checks `LAYA_ENGINE_LIBS`. If it is not set, it looks under the normal per-user LayaAirIDE install location:

```text
%LOCALAPPDATA%/Programs/LayaAirIDE/resources/engine/libs
```

If your LayaAirIDE is elsewhere, set:

```powershell
$env:LAYA_ENGINE_LIBS = "D:\path\to\LayaAirIDE\resources\engine\libs"
```

The directory must contain files such as:

```text
laya.core.js
laya.webgl_2D.js
laya.d3.js
laya.webgl_3D.js
```

## Install

Install these external tools first:

```text
1. Python 3.10+
2. Node.js 18+ from https://nodejs.org/ ; this also installs npm
3. LayaAirIDE, or another local copy of Laya engine libs
```

Then install Python dependencies from the repository root:

```powershell
python -m pip install -r material_fit_ui/requirements.txt
```

The renderer launcher installs its own Chromium automation dependency
(`playwright-chromium`) under `artifacts/real_laya_run/` on first run.

The UI launcher installs frontend npm packages automatically when
`material_fit_ui/frontend/node_modules/` is missing. To install them manually:

```powershell
cd material_fit_ui/frontend
npm install
```

Optional, only for running tests:

```powershell
python -m pip install pytest
```

## Windows Quick Start

For the included fish example, use this order:

```powershell
cd C:\path\to\material_fit
python -m pip install -r material_fit_ui/requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_windows_quickstart.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_laya_runtime_renderer.ps1
```

`check_windows_quickstart.ps1` verifies Python packages, Node/npm, the Laya
engine files, and the included fish example assets before you start the renderer.
If LayaAirIDE is not installed in the default location, set `LAYA_ENGINE_LIBS`
first:

```powershell
$env:LAYA_ENGINE_LIBS = "D:\path\to\LayaAirIDE\resources\engine\libs"
```

Keep that renderer terminal open. In another terminal, start the UI:

```powershell
cd C:\path\to\material_fit
python material_fit_ui/launch.py
```

In the UI, create a project with these example paths:

```text
Laya material: examples/fish_laya_project/assets/resources/model/1504/mat/1504_body.lmat
Laya shader:   examples/fish_laya_project/assets/resources/shader/Custom_low.shader
Unity refs:    examples/fish_unity_refs/
```

The renderer loads `examples/fish_laya_project/assets/resources/game.ls` by
default, so the example does not require copying a separate Laya project or
starting LayaAirIDE.

## Recommended Fast Path

The default pipeline is:

```text
fit_material.py
  -> writes candidate .lmat values
  -> writes a request JSON into persistent_queue/queue/
  -> persistent_queue_daemon.py exposes the request over HTTP
  -> Chromium opens material_fit/laya_capture/runtime_renderer.html
  -> Laya runtime renders the candidate and computes browser_score
  -> daemon writes persistent_queue/results/<request>.result.json
  -> optimizer uses that score for the next candidate
```

New UI projects derive this shape automatically:

```json
{
  "use_laya_editor_capture": false,
  "laya_capture": {
    "persistent_queue": {
      "enabled": true,
      "state_dir": "material_fit/output/<project_id>/persistent_queue",
      "cap_port": 8787
    },
    "browser_score": {
      "enabled": true
    }
  },
  "browser_score_context_render": {
    "enabled": true
  }
}
```

Start the local renderer in a separate terminal. With the files included in this
repository, this command loads the fish Laya project by default:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_laya_runtime_renderer.ps1
```

The defaults resolve to:

```text
ProjectRoot: examples/fish_laya_project
Scene:       examples/fish_laya_project/assets/resources/game.ls
```

For another Laya project, pass both values explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_laya_runtime_renderer.ps1 `
  -ProjectRoot D:\path\to\laya_project `
  -Scene D:\path\to\laya_project\assets\resources\game.ls
```

Then run the UI or CLI optimization job. The optimizer-side queue daemon is started by the generated `ensure_command`; it creates:

```text
<state_dir>/ready.json
<state_dir>/queue/
<state_dir>/results/
```

You can also manage the daemon manually:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ensure_persistent_laya_queue.ps1 -StateDir <state_dir> -Port 8787
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop_persistent_laya_queue.ps1 -StateDir <state_dir>
```

The included `runtime_renderer.html` is a no-IDE Laya 3D harness. It now loads
the real fish Laya scene through a local static server, builds an AssetDb-style
UUID manifest for `res://` references, applies candidate material values in the
live scene, and returns a browser-side `browser_score`. A fallback test object is
kept only as a diagnostic path when the configured scene cannot be opened.

This fast path is part of this repository snapshot. It is not expected to exist
unchanged in the original upstream repository: the local tree includes additional
runtime capture and queue-worker code such as
`material_fit/laya_capture/persistent_queue_daemon.py`,
`material_fit/laya_capture/runtime_renderer.html`, and the enhanced
`MaterialFitCapture.ts` runtime script.

The `.sh` scripts are auxiliary launchers from internal experiments; they are not
the default deployment path and are not required for the fish example.

## Replaying The 2026-07-02 Successful Run On Windows

The 2026-07-02 recovery run can be replayed locally without a Linux server after
you have the Windows fast replay snapshot archive:

```text
exact_repro_20260702_181010_runtime_snapshot_windows_fast.tar.gz
sha256: e3dc50993769e763346e72a39520d56b9ee8c7c9bc5aff5a5889ee1e4e92be47
```

This is a data artifact, not source code. It contains the forensic run snapshot
plus a complete `runtime/operational_webroot` for the local no-IDE fast path.
Put it under `artifacts/` or any other local directory, then extract it into a
`snapshot/` folder:

```powershell
cd C:\path\to\material_fit
New-Item -ItemType Directory -Force -Path artifacts\exact_repro_20260702_181010_runtime_snapshot\snapshot | Out-Null
tar -xzf C:\path\to\exact_repro_20260702_181010_runtime_snapshot_windows_fast.tar.gz `
  -C artifacts\exact_repro_20260702_181010_runtime_snapshot\snapshot
```

The older forensic-only archive is useful for auditing, but it does not contain
the complete local webroot by itself. Use the `_windows_fast` archive for a clean
Windows replay.

If you have not run the normal Windows quick start on this checkout yet, install
the Chromium automation dependency used by the replay worker:

```powershell
New-Item -ItemType Directory -Force -Path artifacts\real_laya_run | Out-Null
Push-Location artifacts\real_laya_run
npm.cmd init -y
npm.cmd install playwright-chromium --no-save
Pop-Location
```

Run a short local verification first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_remote_exact_snapshot_replay.ps1 `
  -SnapshotRoot artifacts\exact_repro_20260702_181010_runtime_snapshot\snapshot `
  -OutputDir artifacts\local_exact_replay_check `
  -Iterations 1 `
  -MaxRuntimeSec 300
```

Then run the same experiment budget from the captured `run.sh`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_remote_exact_snapshot_replay.ps1 `
  -SnapshotRoot artifacts\exact_repro_20260702_181010_runtime_snapshot\snapshot `
  -OutputDir artifacts\local_exact_replay_1000
```

The replay script parses the captured `success_run/scripts/run.sh`, so the
default long run uses the original settings: `ITERATIONS=1000`,
`TARGET_SCORE=0.985`, `optimizer=cma_cold`, population size `8`, sigma `0.32`,
and seed `20260702`.

This replay path is still the no-IDE fast path. It starts a local persistent
Chromium worker, serves the Laya web build, regenerates local target/start
renders from the captured target/start requests, and then runs
`python -m material_fit.fit_material` against the extracted release code. The
PNG files stored inside the forensic archive are preserved as evidence, but the
local optimizer uses the locally regenerated target/start renders because
Windows Chromium/GPU output is not expected to be bit-identical to the remote
Linux render.

## Input Files

A practical run needs:

- Unity reference image directory, with filenames such as `unity_ref_v000_yaw0_pitch0.png`.
- Laya `.lmat` file to modify.
- Laya shader file, when shader parsing or parameter discovery is needed.
- Optional Unity shader/material exports for parameter mapping and semantic hints.
- Laya scene/model assets if the renderer should display the real asset.

Generated project configs and run outputs live under `material_fit/output/`.

This repository includes a small fish example:

```text
examples/fish_laya_project/
examples/fish_unity_refs/
```

For that example, use:

```text
Laya material: examples/fish_laya_project/assets/resources/model/1504/mat/1504_body.lmat
Laya shader:   examples/fish_laya_project/assets/resources/shader/Custom_low.shader
Laya scene:    examples/fish_laya_project/assets/resources/game.ls
Unity refs:    examples/fish_unity_refs/
```

See `examples/README.md` for the asset layout. The Chromium runtime prepares a
browser-decodable PNG cache for `.tga` textures before building the Laya AssetDb
manifest, so the included fish scene can load its light map in the no-IDE path.
The current probe is still expected to log a missing collider component script;
that warning is nonfatal for material rendering.

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

The UI is the recommended entrypoint for creating a project, selecting files, running preanalysis, starting optimization jobs, and inspecting iteration images.

## Run From CLI

Use module mode from the repository root:

```powershell
python -m material_fit.fit_material --help
```

Do not run `python material_fit/fit_material.py` directly; the package uses relative imports and expects module mode.

A typical run:

```powershell
python -m material_fit.fit_material `
  --config material_fit/output/<project_id>/runs/<run_id>/fit_config.json `
  --auto-adjust `
  --iterations 100 `
  --target-score 0.98 `
  --optimizer semantic_group `
  --fit-score-mode human_accept `
  --apply-lmat
```

`material_fit/fit_config.example.json` documents the config shape. Replace all example asset paths before using it.

## Optional Editor Fallback

The old command-file capture path is still available when a project must render inside LayaAirIDE. Enable it with:

```json
{
  "algorithm_config": {
    "use_laya_editor_capture": true
  }
}
```

Then copy the fallback scripts into the Laya project:

```text
Editor/CameraCapture.ts      -> <LayaProject>/assets/Editor/CameraCapture.ts
Editor/CameraCaptureEnv.ts   -> <LayaProject>/assets/Editor/CameraCaptureEnv.ts
Editor/*.meta                -> <LayaProject>/assets/Editor/
```

Set `laya_capture_command_path` to:

```text
<LayaProject>/assets/material_fit_capture_command.json
```

This mode is slower because each iteration depends on Editor refresh/reimport behavior.

## Expected Speed

The fast path keeps the renderer alive and returns `browser_score` directly, avoiding most per-iteration editor startup, screenshot discovery, and Python-side image scoring overhead.

Local no-IDE Laya runtime benchmark on this machine:

```text
100 requests
320x240 render size
total: 16.44 s
mean: 0.157 s/request
median: 0.094 s/request
p90: 0.328 s/request
throughput: 6.08 requests/s
```

The current default renderer loads the included fish Laya scene. Real cost depends on model complexity, shader cost, view count, texture IO, and browser/GPU availability, so remeasure on the target machine before comparing optimization algorithms.

Editor fallback mode is usually much slower. A run like 90 iterations in about 6 minutes is roughly 4 seconds per iteration and is not surprising for Editor-driven capture.

## Outputs Not To Commit

Generated runtime data is ignored:

```text
material_fit/output/
material_fit_ui/frontend/node_modules/
material_fit_ui/frontend/dist/
artifacts/
LayaAirIDE-*/
laya_project_minimal/
unity_references/
examples/fish_laya_project/output/
examples/fish_laya_project/.material_fit_browser_assets/
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

The suite covers `.lmat` IO, scoring, optimizer behavior, UI backend config generation, Laya capture command handling, runtime bridge behavior, and compatibility paths.

## Troubleshooting

### Renderer cannot load Laya

Check `LAYA_ENGINE_LIBS` and confirm it points to the directory containing `laya.core.js`, `laya.d3.js`, and the WebGL libraries.

### Optimization waits forever for capture

Check:

- The runtime renderer script is still running.
- The queue daemon has `<state_dir>/ready.json`.
- The daemon port matches the renderer server URL.
- `laya_capture.persistent_queue.enabled` is true.
- `browser_score.enabled` is true.

### Editor fallback does not capture

Check:

- `use_laya_editor_capture` is true.
- `laya_capture_command_path` points to the Laya project command file.
- The Editor scripts are present under `<LayaProject>/assets/Editor/`.
- LayaAirIDE has the project open and the scene contains the configured camera and target.

### Import says `material_fit` is missing

Run commands from the repository root. Keep the `tools/` directory only for older configs that still import `tools.material_fit...`.

## Further Docs

- `material_fit/docs/Project_Architecture.md`: architecture and data flow.
- `material_fit/docs/File_Layout_And_Artifacts.md`: output and artifact layout.
- `material_fit/docs/Laya_Multiview_Capture.md`: Laya capture details.
- `material_fit/docs/Core_Algorithms_and_Metrics.md`: core algorithms and metrics.
- `material_fit/docs/Scoring_Mechanism_Design.md`: scoring design.
- `material_fit/docs/learned_incremental_optimizer_design.html`: learned optimizer design proposal.

## Provenance And License

This public repository was prepared from a local `material_fit` workspace and keeps the original upstream history reference:

- Upstream: `https://github.com/mcy233/material_fit.git`
- Current public mirror: `https://github.com/CyberBarbarian/material_fit`

The implementation and design refer to Unity ShaderLab/material workflows, LayaAir Shader3D/material workflows, CMA-ES and warm-start CMA-ES style black-box optimization, SSIM/perceptual image similarity, foreground masking, and multi-view aggregation.

There is currently no explicit `LICENSE` file in this repository. Until a license is added by the repository owner, treat this as source-available research code with provenance notes, not as a formally licensed open-source release.
