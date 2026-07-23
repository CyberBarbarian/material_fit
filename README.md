# Material Fit

Material Fit searches LayaAir material parameters from rendered images. The
renderer is treated as a black box: the optimizer submits a material, receives
one or eight PNG views, and updates its proposal from image scores and residuals.

The repository ships one reproducible single-view Stage 1 task for three assets:

| Asset | Start material | Image target |
| --- | --- | --- |
| Fish 1504 | `1504_new_test.lmat` | render of `1504_body.lmat` |
| Turtle 1506 | `1506_test.lmat` | render of `1506_mat.lmat` |
| Crocodile 1503 | `1503_test.lmat` | render of `1503_body.lmat` |

The target materials are used only to render private reference PNGs. Their
parameters and hard states are not exposed to the optimizer.

## Requirements

- Python 3.10 or newer
- Git
- Windows 10/11 or a current x86-64 Linux distribution

Windows requires Node.js 18 or newer on `PATH`. On Linux x86-64,
`bootstrap.sh` uses a system Node.js 18+ when available; otherwise it downloads
and verifies Node.js 22.17.1 under `.runtime/`. The Linux fallback requires
`curl` or `wget`, `sha256sum`, and a `tar` build with xz support.

LayaAirIDE is not required. The nine LayaAir 3.4.0 runtime files used by the
headless renderer are checked in under `vendor/layaair-3.4.0/libs/`.

On Debian or Ubuntu, install the Python virtual-environment module and Chromium
system libraries once before bootstrap:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
sudo npx playwright install-deps chromium
```

When bootstrap runs as root, Playwright installs the Chromium system libraries
automatically. Other Linux distributions must provide their equivalent Python
`venv` and Chromium runtime packages.

An NVIDIA GPU is optional. CPU or software WebGL can reproduce the pipeline.
Record the active WebGL backend when comparing performance across machines;
renderer choice can matter more than the operating system.

## Install

Clone the repository and run the platform bootstrap. The scripts create
`.venv`, install the Python package, install the locked Node dependencies, fetch
the matching Chromium build, and run the checkout doctor.

Windows PowerShell:

```powershell
git clone --depth 1 --branch main https://github.com/CyberBarbarian/material_fit.git
Set-Location material_fit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

Linux:

```bash
git clone --depth 1 --branch main https://github.com/CyberBarbarian/material_fit.git
cd material_fit
bash scripts/bootstrap.sh
```

Rerun the environment check at any time:

```powershell
.venv\Scripts\python.exe -m material_fit.doctor
```

```bash
.venv/bin/python -m material_fit.doctor
```

The check verifies Python, the DISTS/PyTorch scorer, Node.js, Playwright 1.61.1,
Chromium, the vendored LayaAir files, public Windows/Linux entrypoints, all four
example assets, the tracked 1613 experimental-best snapshot, the Stage 1 policy
hashes, and all four Stage 2 Unity reference sets.

The installation and fish Stage 1 command were verified from dependency-free
source trees on Windows 11 and Linux x86-64. Exact run records are in
[`material_fit/docs/EXPERIMENTS.md`](material_fit/docs/EXPERIMENTS.md).

## Run Stage 1

The maintained optimizer is
`v86_budget1500_initial_score_routed_unified`. One run scores the original
material once, then allows at most 1,499 optimizer proposals.

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stage1.ps1 -Asset fish
```

Linux:

```bash
bash scripts/run_stage1.sh fish
```

Replace `fish` with `turtle` or `crocodile` to use the other packaged scene.
The wrappers use the same Python entry point, policy files, Laya runtime, image
contract, and iteration accounting on both systems.

Run output is written under `artifacts/stage1_<asset>_human_png_<timestamp>/`.
The files to inspect first are:

- `stage1_report.json`: acceptance result, score, timing, and cleanup audit
- `human_target_start_best_single_view.png`: target, original start, and best render
- `initial_score_router/initial_score_route_report.json`: selected V86 route
- `stage1_discrete_search_space_report.json`: legal hard-state search space
- `optimizer_input_boundary_report.json`: proof that target parameters stayed private
- `output/auto_adjust/best/params.json`: final optimizer parameters

The process exits with code `0` only when the run reaches the maintained `0.93`
acceptance score and passes the renderer, artifact, speed, and process-cleanup
gates. A configured target score is an early-stop threshold, not a substitute
for the final report.

## Algorithm

V86 begins from the original continuous and discrete material state. It builds
the same 16 legal hard-state candidates for every asset and uses the initial
full-resolution PNG score to select one of three fixed policies:

| Initial score | Policy snapshot | Online score size |
| --- | --- | --- |
| below 0.75 | `low_v85.json` | width 400, native aspect ratio |
| 0.75 to 0.85 | `medium_v42.json` | width 720, native aspect ratio |
| 0.85 and above | `high_v30.json` | width 544, native aspect ratio |

The route does not receive the asset name. Continuous search covers 40 material
coordinates and six scene/light coordinates. Scene coordinates and the selected
hard state are frozen before the final material refinement. The early search
uses a pixel-directed inverse objective; the final hard-state rescan, material
polish, reporting, and acceptance use the perceptual V6 objective. Both consume
target PNG scores and signed image residuals only.

Accepted and clean-install reference runs are recorded in
[`material_fit/docs/EXPERIMENTS.md`](material_fit/docs/EXPERIMENTS.md).

## Three-stage workflow

The single-top-view line uses one V86 mixed material policy across three ordered
tasks: known Laya perturbation recovery, fitting to a human-adjusted Laya PNG,
and fitting to a Unity PNG. It combines one inverse-search objective with one
frozen acceptance objective. Its contract and commands are documented in
[`material_fit/docs/SINGLE_VIEW_THREE_STAGE.md`](material_fit/docs/SINGLE_VIEW_THREE_STAGE.md).

Run a Phase 0.5 recovery case with:

```bash
python -m material_fit.experiments.single_view_phase05_v86 \
  --asset turtle \
  --case joint_mild_seed53
```

Run the matching Stage 1 task with:

```bash
python -m material_fit.experiments.material_human_reference_stage1 \
  --asset turtle \
  --single-view \
  --optimizer material_discrete_joint \
  --joint-profile v86_budget1500_initial_score_routed_unified \
  --iterations 1499
```

`scripts/run_fish_finetune.*` retains the Pattern16 cross-engine fish baseline
against the packaged Unity reference PNGs. `scripts/run_fish_zero_start.*` is a
hard-start research variant: it zeros only the 16 searchable appearance
parameters and preserves textures, UV transforms, alpha state, shader toggles,
and render state.

Real Unity Stage 2 reference sets for fish, turtle, crocodile, and holiday 1613 are isolated
under `examples/stage2_unity_refs/`. Audit a set before material optimization:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_intake \
  --asset fish \
  --output-dir artifacts/stage2_fish_intake
```

Holiday 1613 uses the same shared-parameter material optimizer for every
non-empty reference subset. The platform wrappers run all eight tracked views
by default:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_1613_fit.ps1
```

```bash
bash scripts/run_1613_fit.sh
```

Pass any non-empty tracked subset with `--view-ids`. Reference count changes
only the images aggregated by the loss; one parameter vector is written to one
ordinary `.lmat`, and the shader, mesh, texture contents, and camera stay
fixed. The current 1613 run is experimental and must not be reported accepted
unless its independent eight-view score reaches the configured `0.98` gate.

Package a completed run for handoff:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package_1613_result.ps1 -RunDir artifacts\<run>
```

```bash
RUN_DIR=artifacts/<run> bash scripts/package_1613_result.sh
```

The run-backed packager refuses incomplete output: it requires the report,
parameter JSON, all eight best-render PNGs, and a contact sheet. With no
arguments, the same wrapper packages the tracked parameter-only best
(`0.8841877893703689`, explicitly not accepted) so a fresh checkout always has
a reproducible handoff artifact. Every ZIP contains the complete runtime
project with the selected material installed, a parameter JSON, hashes, and a
resolved-texture audit.

Turtle 1506 has a frozen Stage 2 geometry profile. Render the untouched Laya
start material on the Unity canvas and run the pre-optimization gate with:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_capture \
  --asset turtle \
  --material start \
  --output-dir artifacts/stage2_turtle_capture
```

To fit only the turtle back view with the single-view V86 policy, run:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_single_view \
  --asset turtle \
  --view-id v000_yaw0_pitch0
```

The command retains the original material start, all 16 legal discrete states,
V86 score routing, and a hard limit of 1,500 unique scored materials, including
the start. It jointly searches 40 material and six scene/light coordinates,
then freezes the scene/light solution before final material refinement. The
shared loop uses a `450x350` readback. Its early inverse objective switches to
the V6 acceptance objective for the last 266 proposals, and the 20 archived
elites are reranked at full resolution without creating new proposals.
Human-adjusted parameters are never loaded by the optimizer. Current evidence
and acceptance requirements are recorded in the Stage 2 document below.

Stage 2 result sheets always use four columns in this order: Unity reference,
original Laya start, offline human-adjusted Laya reference, and optimized Laya
best. The human-adjusted material is rendered only after optimization has
stopped and is used for reporting, never for routing or proposals.

The Stage 2 geometry and scoring contract is documented in
[`material_fit/docs/STAGE2.md`](material_fit/docs/STAGE2.md).

The older eight-view Phase 0.5 runner remains available through
`material_fit.experiments.material_phase05_recovery`. It is a validation tool,
not the default installation check or the single-view three-stage entry point.

## Development

Run the maintained test suite with:

```bash
.venv/bin/python -m pytest -q
```

On Windows use `.venv\Scripts\python.exe` in the same command. Generated runs,
browser caches, virtual environments, and source archives are ignored by Git.
Do not add experiment output to the repository.

The module map and experiment contracts are documented in
[`material_fit/docs/ARCHITECTURE.md`](material_fit/docs/ARCHITECTURE.md) and
[`material_fit/docs/EXPERIMENTS.md`](material_fit/docs/EXPERIMENTS.md).
Third-party origins are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
