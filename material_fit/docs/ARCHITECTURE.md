# Architecture

## Runtime flow

```text
asset adapter
    -> immutable scene/material/profile paths
    -> target renderer creates eight private PNGs
    -> target renderer stops
    -> candidate renderer starts once
    -> optimizer submits material patches through the persistent queue
    -> browser returns score and residual vectors
    -> optimizer selects the best material
    -> artifact renderer writes final eight-view PNGs
    -> report and process cleanup audits run
```

The renderer is persistent. Chromium, the scene, shaders, meshes, and textures
are loaded once per run. An optimization iteration changes material state,
renders eight views in the same browser, and returns numeric feedback without
encoding eight PNG files. PNGs are written for target, start, scorer checks, and
final evidence only.

## Python packages

### `material_fit.assets`

Resolves asset files and capture profiles. Asset adapters contain paths,
material roles, camera framing, and scene-specific names. They do not select an
optimizer or alter its proposal policy.

`material_stage1.py` exposes the fish, turtle, and crocodile pairs used by the
main experiment. `fish_scene.py` validates the packaged fish scene and Unity
references by hash.

### `material_fit.experiments`

Owns experiment orchestration and reports.

- `material_human_reference_stage1.py`: the shared Stage 1 runner
- `stage1_profiles.py`: V86 routing and verified policy snapshot loader
- `material_phase05_recovery.py`: perturb-and-recover validation
- `material_phase05_multistart.py`: Phase 0.5 robustness matrix
- `fish_core_experiment.py`: Pattern16 cross-engine fish baseline
- `fish_visual_contract_experiment.py`: camera and pose contract check

Experiment modules may create private audit files, but optimizer configuration
must not contain target materials or target parameters.

### `material_fit.optimizer`

Contains proposal strategies and parameter encoders. The Stage 1 mainline uses
`material_discrete_joint_strategy.py` to combine legal hard-state candidates
with continuous material search. `structured_material_space.py` defines the
shared 40 material and six scene/light coordinates.

V86 child policies are data files under `material_fit/config/stage1_v86/`.
Their hashes are checked before a run. Historical V3-V85 Python branches are
not part of the runtime tree.

The joint strategy is split by responsibility:

- `material_discrete_joint_strategy.py`: state machine and continuous handoff
- `material_discrete_joint_rescan.py`: hard-state rescans and branch races
- `material_discrete_joint_support.py`: feedback quantization and validation

### Fit execution

`fit_material.py` owns CLI orchestration, configuration, scoring helpers, and
the stable compatibility entry points. Candidate execution is isolated in
`fit_single_execution.py`; ask-many/tell-many CMA execution is isolated in
`fit_batch_execution.py`. The wrappers preserve the existing call signatures
so the UI and external scripts do not depend on the internal split.

### `material_fit.laya_capture`

Runs the profile-driven browser renderer and owns its lifecycle.

- `run_runtime_renderer.js`: Playwright process and static asset server
- `runtime_renderer.html`: LayaAir scene, capture, and browser-side scorer
- `managed_runtime.py`: process-group startup, readiness, retry, and cleanup
- `persistent_queue_daemon.py`: request/result queue worker

Every renderer has a state directory and PID record. Cleanup targets only the
owned process tree.

### `material_fit.vision`

Implements artifact scoring and diagnostics. Online scoring happens in the
browser for speed; Python recomputes the final score from emitted PNGs. Geometry
and material quality remain separate. Candidates are never translated, scaled,
flipped, or warped to improve their material score.

## JavaScript and engine runtime

`package-lock.json` pins Playwright and its browser protocol. Chromium itself is
installed into the user's Playwright cache. The LayaAir files required by the
runtime page are pinned under `vendor/layaair-3.4.0/libs/` and checked by hash in
`material_fit.doctor`.

## Platform boundary

Python and JavaScript contain the experiment logic. Platform scripts do only
three things: choose the virtual-environment Python path, set Linux Chromium
flags, and pass repository-local dependency paths. Windows and Linux wrappers
must call the same module with the same profile and budget.
