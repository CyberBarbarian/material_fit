# Material Fit

Material Fit is a black-box material-parameter fitting project. It adjusts
Laya `.lmat` parameters, renders the asset in Laya, compares the output PNGs
with Unity reference PNGs, and chooses the next parameter proposal.

This repository does not train a neural network for the maintained fish
baseline. The core loop is:

```text
.lmat params -> Laya render PNGs -> Unity/Laya image score -> next params
```

The current maintained task is documented in:

```text
material_fit/docs/Canonical_Fish_Task.md
```

If older notes conflict with that file, use the canonical task document and
`AGENTS.md` as the source of truth.

## Maintained Mainline

The maintained fish baseline is the accepted material-start 16-dimensional
pattern search experiment:

```text
entrypoint: python -m material_fit.experiments.fish_core_experiment --mode finetune --optimizer pattern16
script wrappers: scripts/run_fish_finetune.ps1 and scripts/run_fish_finetune.sh
experiment: fish_finetune_pattern16
optimizer: 16D coordinate pattern search
start params: real fish_jxs_test.lmat material state
initial_params_mode: material
views: 8 yaw views, pitch 0
animation: fixed idle1 at time 0
capture size: 900x700
score metric: browser_fast_rgba_mae_v1
```

This is the route that produced the strong early fish comparison with columns
such as:

```text
unity_ref / start_laya_default / best_120 / best_500
```

`cold_start_hybrid`, CMA-ES, semantic-group, response-search, and zero-start
runs are retained as research/debug paths. They are not the default baseline.

## Repository Layout

```text
material_fit/
  experiments/
    fish_core_experiment.py                # maintained fish baseline runner
  optimizer/
    pattern16_strategy.py                  # 16D search space, bounds, steps
  assets/
    fish_scene.py                          # canonical fish source-zip resolver
  laya/                                    # .lmat and render-driver helpers
  laya_capture/                            # no-IDE Laya capture runtime
  vision/                                  # scoring and image utilities

examples/
  fish_unity_refs/                         # Unity reference PNGs for inspection

artifacts/source_archives/20260612_original_fish_inputs/
  laya_project_minimal(3).zip              # local input asset, ignored by git
  unity_references(1).zip                  # local input asset, ignored by git
```

Generated outputs go under `artifacts/` and are not committed.

## Install

Use Python 3.10+ and Node.js 18+.

Install Python dependencies from the repository root:

```powershell
python -m pip install -r material_fit_ui/requirements.txt
```

On Linux:

```bash
python -m pip install -r material_fit_ui/requirements.txt
```

The local runtime installs `playwright-chromium` under ignored
`artifacts/real_laya_run/` on first use.

## Laya Engine Libraries

Windows runtime runs need the Laya engine `libs` directory containing:

```text
laya.core.js
laya.webgl_2D.js
laya.d3.js
laya.webgl_3D.js
```

The runner checks `LAYA_ENGINE_LIBS` first. If it is unset on Windows, it tries:

```text
%LOCALAPPDATA%\Programs\LayaAirIDE\resources\engine\libs
```

Set it explicitly when needed:

```powershell
$env:LAYA_ENGINE_LIBS = "D:\LayaAirIDE\resources\engine\libs"
```

Generic Linux runtime runs also need `LAYA_ENGINE_LIBS`. On the Volcano server,
the maintained fast path loads the original zip project through the runtime
renderer and only reuses Laya engine/Chromium binaries from:

```text
/vepfs-mlp2/c20250508/lizikang/material_fit_render_oracle
```

It does not reuse the global oracle webroot by default, because that webroot is
mutable and can point at the wrong material. The explicit `oracle` backend is
reserved for diagnostics and historical forensics.

## Source Assets

Place the original fish zip inputs here:

```text
artifacts/source_archives/20260612_original_fish_inputs/
  laya_project_minimal(3).zip
  unity_references(1).zip
```

Validate and extract them:

```powershell
python -m material_fit.assets.fish_scene --repo-root .
```

Linux uses the same command:

```bash
python -m material_fit.assets.fish_scene --repo-root .
```

The resolver extracts to:

```text
artifacts/original_zip_probe_20260612/
```

For maintained fish work, do not silently switch to `1504_body.lmat`. It is a
non-default historical/ablation material.

## Run The Mainline Experiment

Windows local runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_fish_finetune.ps1 `
  -Iterations 120 `
  -TargetScore 0.98 `
  -RunName fish_finetune_pattern16_windows
```

Volcano Linux fast runtime:

```bash
bash scripts/run_fish_finetune.sh \
  --iterations 120 \
  --target-score 0.98 \
  --run-name fish_finetune_pattern16_linux
```

On Linux, the wrapper defaults Chromium to the EGL/WebGL path:

```text
--ignore-gpu-blocklist --enable-webgl --enable-gpu-rasterization --use-gl=egl --disable-gpu-sandbox
```

On the Volcano server, if the GPU keepalive guard is running on every GPU,
temporarily free the GPU used by Chromium before the run, then restore the guard
immediately after the run. The tested setup frees GPU 0 by guarding only
`1,2,3` during the experiment, and restores `0,1,2,3` afterward. Do not treat a
white/blank Linux contact sheet with a high score as success; check
`renderer_logs/runtime_renderer_stderr.log` for WebGL/page errors.

Each successful run writes:

```text
artifacts/<run_name>/
  fit_config.json
  summary.json
  fish_contact_sheet.png
  raw_scene_render/
  output/
  logs/
```

Use `summary.json` for the numeric result and
`fish_contact_sheet.png` for visual verification.

## Zero-Start Is Separate

Zero-start is a hard-start research route, not the current release gate.

When zero-start is used, it means:

```text
initial_params_mode = zero_searchable
```

Only optimizer-searchable appearance parameters may be initialized to zero.
Locked/material-validity values must stay inherited from the valid baseline
material. Never interpret zero-start as "zero every numeric `.lmat` field".

## Troubleshooting

If a render is grey, blue, textureless, black, or blank, treat it as a
renderer/path/material-state bug first. Check:

```text
run_dir
entrypoint
backend
asset resolver / scene path
start params path
reference dir
score metric
capture size
contact sheet path
summary.json path
```

Do not label a raw scene render as "Material start". Do not mix columns from
different asset roots, material files, renderer paths, or historical runs.

## Tests

Run unit tests from the repository root:

```powershell
python -m pytest material_fit/tests -q
```

Linux:

```bash
python -m pytest material_fit/tests -q
```

## Git Hygiene

Commit source, tests, docs, and scripts. Do not commit generated artifacts or
local source zips:

```text
artifacts/
material_fit/output/
material_fit_ui/frontend/node_modules/
material_fit_ui/frontend/dist/
__pycache__/
.pytest_cache/
```

## Provenance

This repository was prepared from a local `material_fit` workspace with upstream
history reference:

- Upstream: `https://github.com/mcy233/material_fit.git`
- Public mirror: `https://github.com/CyberBarbarian/material_fit`

There is currently no explicit `LICENSE` file. Until one is added, treat this
as source-available research code with provenance notes.
