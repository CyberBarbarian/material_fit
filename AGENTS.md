# Material Fit Repository Rules

## Shell and process safety

- On Windows, keep PowerShell commands explicit. Do not pipe directly after a
  closing script block. For nested Python, SSH, or Bash logic, write a UTF-8
  script instead of stacking quoted one-liners.
- Every experiment owns its browser, queue, renderer, and helper processes.
  Record PIDs under the run directory, terminate the owned process tree in a
  `finally`/`trap`, and verify that no owned process remains.
- Never mass-kill Chrome, Node.js, Python, LayaAirIDE, Codex, or user browser
  processes. A readiness failure must stop the process it started before
  raising.
- On the Volcano server, inspect the GPU guard and active compute jobs before a
  run. GPU 0 is reserved for the StarCraft workload. Material Fit normally uses
  GPU 2 when it is free. Do not stop, reset, or reconfigure an unrelated job.
  If a guarded device is freed for a bounded test, record and restore the exact
  original guard configuration before reporting completion.

## Packaged runtime

- Runtime experiments must resolve assets from the tracked projects under
  `examples/`, not ignored `artifacts/` directories or forensic snapshots.
- Use the repository Playwright installation under `node_modules/` and the
  vendored LayaAir 3.4.0 files under `vendor/layaair-3.4.0/libs/`.
- `python -m material_fit.doctor` must pass before a real experiment.
- Source ZIP archives under `artifacts/source_archives/` are optional provenance
  records. They are not installation dependencies.

## Capture contract

- Fish, turtle, crocodile, and new adapters use yaw
  `0,45,90,135,180,225,270,315`, pitch `0`, zero yaw/pitch offsets, model-bounds
  framing, and a white comparison background.
- Disable animation before startup settling. Do not restore the historical fish
  `idle1@0.21875` exception or copy an editor camera tilt into optimizer
  profiles.
- A source `.lmat` copied to another project must preserve valid texture
  bindings. Fail when any `res://UUID` texture cannot be resolved.
- Render target and scorer sanity first, stop the target renderer, then start
  the candidate renderer. Do not keep two WebGL scenes alive during a long run.

## Shared Stage 1

- The canonical entry point is
  `python -m material_fit.experiments.material_human_reference_stage1`; platform
  wrappers are `scripts/run_stage1.ps1` and `scripts/run_stage1.sh`.
- The only public policy is
  `v86_budget1500_initial_score_routed_unified`. It permits one initial score
  plus at most 1,499 proposals. Child policy snapshots are immutable JSON under
  `material_fit/config/stage1_v86/` and are verified by hash.
- Start from each asset's original continuous and discrete state. Build the 16
  legal hard-state candidates without target information. Do not copy target
  defines, bools, render state, continuous parameters, or asset-specific hints
  into the optimizer start.
- V86 may use only the initial full-resolution PNG score to choose its low,
  medium, or high route. The router and optimizer must not receive the asset
  name, target material, target parameters, or human-adjusted parameters.
- Freeze the selected hard state and all six scene/light coordinates before the
  final 40-coordinate material refinement.
- Browser iterations return score and residual vectors only. Target, start,
  scorer-sanity, and final evidence captures emit the eight PNG files.
- Judge the `<=500 ms` speed gate from isolated stable decision iteration time,
  excluding startup and report generation.

Accepted Linux evidence is recorded in
`material_fit/docs/EXPERIMENTS.md`. Old V3-V85 strategy experiments are not
runtime APIs and must not be reintroduced as branches in the main runner.

## Phase 0.5

- Phase 0.5 perturbs and recovers the same 40 material coordinates while keeping
  six scene/light coordinates fixed. Asset adapters and optimizer policy remain
  separate.
- The optimizer-visible config may reference target PNGs only. Target material
  and target parameters belong under `private_audit/` and must not appear in
  `fit_config.json`.
- Require stable independent target renders, near-1.0 same-parameter score, high
  tiny-perturbation score, eight real target/start/best PNGs, and a cleanup
  audit before accepting a run.

## Pattern16 and zero start

- Pattern16 remains the fish cross-engine baseline against the tracked Unity
  reference PNGs. It searches exactly the 16 names in
  `PATTERN16_PARAM_ORDER`.
- Zero start means `initial_params_mode=zero_searchable`: zero the 16 searchable
  appearance values and inherit all material-validity state from the baseline
  `.lmat`.
- Never zero texture bindings, texture `*_ST` transforms, alpha/cutoff values,
  hidden shader values, bool/toggle values, render state, or scene/light
  orientation. A fully numeric all-zero material is a destructive stress test,
  not the maintained experiment.
- If a best render is flat, blue, grey, black, or textureless, audit locked
  values before changing the optimizer.

## Repository maintenance

- Keep the root README limited to current installation and runnable workflows.
  Historical experiment narratives belong in Git history, not executable
  branches or active wrappers.
- New assets add adapter data and tests; they do not add asset-name branches to
  optimizer code.
- Run `python -m pytest -q` after changes. For deployment changes, also test the
  documented bootstrap and a real run on both Windows and Linux.
