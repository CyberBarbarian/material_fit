# Material Fit

Material Fit searches LayaAir material parameters from rendered images. The
renderer is treated as a black box: the optimizer submits a material, receives
eight PNG views, and updates its proposal from image scores and residuals.

The repository ships one reproducible Stage 1 task for three assets:

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

On Linux, Chromium also needs system libraries. When bootstrap runs as root it
installs them through Playwright. For an unprivileged account, install them
once before bootstrap with:

```bash
sudo npx playwright install-deps chromium
```

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

The check verifies Python, Node.js, Playwright 1.61.1, Chromium, the vendored
LayaAir files, all three example assets, the Stage 1 policy hashes, and all
three Stage 2 Unity reference sets.

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
- `stage1_contact_sheet.png`: target, original start, and best render
- `initial_score_router/initial_score_route_report.json`: selected V86 route
- `stage1_discrete_search_space_report.json`: legal hard-state search space
- `optimizer_boundary_report.json`: proof that target parameters stayed private
- `output/auto_adjust/best/params.json`: final optimizer parameters

The process exits with code `0` only when the run passes the score, renderer,
artifact, speed, and process-cleanup gates. A configured target score is an
early-stop threshold, not a substitute for the final report.

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
coordinates and, where required, six scene/light coordinates. Scene coordinates
and the selected hard state are frozen before the final material refinement.
All proposals are ranked from target PNG scores and signed image residuals.

Accepted and clean-install reference runs are recorded in
[`material_fit/docs/EXPERIMENTS.md`](material_fit/docs/EXPERIMENTS.md).

## Other Tasks

`scripts/run_fish_finetune.*` retains the Pattern16 cross-engine fish baseline
against the packaged Unity reference PNGs. `scripts/run_fish_zero_start.*` is a
hard-start research variant: it zeros only the 16 searchable appearance
parameters and preserves textures, UV transforms, alpha state, shader toggles,
and render state.

Real Unity Stage 2 reference sets for fish, turtle, and crocodile are isolated
under `examples/stage2_unity_refs/`. Audit a set before material optimization:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_intake \
  --asset fish \
  --output-dir artifacts/stage2_fish_intake
```

The Stage 2 geometry and scoring contract is documented in
[`material_fit/docs/STAGE2.md`](material_fit/docs/STAGE2.md).

Phase 0.5 material-recovery experiments remain available through
`material_fit.experiments.material_phase05_recovery`. They are validation tools,
not the default installation check.

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
