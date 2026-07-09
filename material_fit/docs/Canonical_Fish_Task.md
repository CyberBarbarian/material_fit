# Canonical Fish Task Contract

> Purpose: prevent experiment/path drift. This document is the working contract
> for the maintained fish material-fitting task.

## 1. What We Are Solving

The project fits Laya `.lmat` material parameters so that a real Laya render
matches Unity reference renders from the same camera views.

This repository is currently a black-box optimization system. It is not a
trained AI model, and the maintained fish baseline does not train a neural
network. The loop is:

```text
params -> render Laya PNGs -> compare with Unity PNGs -> propose next params
```

The success criterion is visual and metric improvement against the Unity
reference images, with the actual rendered PNGs used as the final evidence.

## 2. Current Mainline Experiment

The mainline experiment is the accepted historical fish finetune baseline:

```text
experiment: fish_finetune_pattern16
optimizer: 16D coordinate pattern search
entrypoint: python -m material_fit.experiments.fish_core_experiment --mode finetune --optimizer pattern16
script wrappers: scripts/run_fish_finetune.ps1 and scripts/run_fish_finetune.sh
start params: the real fish_jxs_test.lmat material state
initial_params_mode: material
views: 8 yaw views, pitch 0
animation: fixed idle1 at time 0
capture size: 900x700
score metric: browser_fast_rgba_mae_v1
report background: white contact sheet
```

This experiment is the route that reproduced the strong early result with
columns like:

```text
unity_ref / start_laya_default / best_120 / best_500
```

For repository verification, this is the experiment that must run on both
Windows and Linux first. Linux should load the same original zip project through
the runtime backend by default. It may reuse server-local Laya engine/Chromium
binaries, but it must not silently reuse a mutable global oracle webroot as the
source scene. On headless Linux, Chromium must use the EGL/WebGL path configured
by `scripts/run_fish_core_experiment.sh`; on the Volcano server, GPU keepalive
guard coverage may need to exclude the Chromium GPU during the run and must be
restored immediately after the run.

## 3. Search Space

`fish_finetune_pattern16` searches exactly these 16 appearance parameters:

```text
u_GammaPower
u_Saturation
u_TexPower
u_AoPower
u_EmissionPow
u_IndirectStrength
u_NormalScale
u_ShadowSmoothness
u_ShadowThreshold1
u_ShadowThreshold2
u_SpecularIntensity
u_SpecularPower
u_SpecularThreshold
u_SpecularSmoothness
u_RimIntensity
u_RimWidth
```

The bounds and initial step sizes are defined in:

```text
material_fit/optimizer/pattern16_strategy.py
```

Material-validity parameters are not part of this 16D search space. Texture
bindings, texture ST values, alpha/cutoff values, light/sky orientation values,
hidden shader params, bool params, and render-state params must remain inherited
from the valid baseline material/state.

## 4. Baseline Assets And Start State

The accepted cross-platform finetune run starts from the canonical
`fish_jxs_test.lmat` material in the original fish source zip.

Do not replace this start with remote forensic `start_params.json` snapshots.
Those snapshots are useful for exact remote-run investigations, but they are
not the maintained Windows/Linux material-start experiment.

The canonical asset resolver remains:

```text
material_fit.assets.fish_scene.resolve_fish_scene_assets
```

It resolves the original fish input zips under:

```text
artifacts/source_archives/20260612_original_fish_inputs/
```

Those zip files are local input assets and are intentionally not tracked by git.

## 5. What Is Not The Mainline Experiment

The following are not the maintained mainline fish experiment unless explicitly
requested for debugging or ablation:

- `1504_body.lmat`.
- `1506` or other non-fish/non-main scenes.
- Raw Laya scene render. It is only a renderer/asset sanity check.
- Legacy `examples/fish_laya_project` output when it differs from the original
  source zip scene.
- CMA-ES, cold-start hybrid, semantic-group, response-search, or other
  exploratory optimizers.
- Any run where the contact sheet is grey, blue, textureless, black, or blank
  because the renderer loaded the wrong scene/material/webroot.
- A Linux `oracle` run that loads a global `build/current_web/resources/game.ls`
  pointing at `1504_body.lmat` instead of the canonical `fish_jxs_test.lmat`.

If the visual output is blue/textureless, treat it as a render/path/material
state bug first. Do not report it as an optimizer result.

If a Linux contact sheet is blank or white while the numeric score is high,
that is also a renderer failure, not an optimizer win. Check
`renderer_logs/runtime_renderer_stderr.log` for WebGL context loss or page
errors before accepting the run.

## 6. Zero-Start Status

Zero-start is a separate hard-start research route. It is useful for exploring
the algorithm's upper limit, but it is not the current release gate.

When zero-start is used, it means:

```text
initial_params_mode = zero_searchable
```

That only zeros optimizer-searchable appearance parameters. It must not zero
all numeric `.lmat` fields.

For the fish pattern16 family, the zero-searchable set is the same 16 appearance
parameters listed above. Locked/material-validity values must stay inherited
from the valid baseline.

## 7. Required Reporting Discipline

Every visual claim must state:

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

For the mainline experiment, the expected comparison is:

```text
Unity reference / Pattern16 start / Pattern16 best
```

Extended historical comparisons may also include:

```text
Unity reference / Pattern16 start / best_120 / best_500
```

Do not label a raw scene render as "Material start". Do not mix columns from
different asset roots, different material files, or different renderer paths.

## 8. Current Work Order

The maintained project work order is:

1. Keep `fish_finetune_pattern16` as the mainline fish finetune experiment.
2. Make that exact experiment reproducible on Windows and Linux.
3. Use the produced PNG contact sheets and `summary.json` as evidence.
4. Clean README/scripts so the default path points to this experiment.
5. Keep zero-start documented as experimental until it is separately stabilized.
