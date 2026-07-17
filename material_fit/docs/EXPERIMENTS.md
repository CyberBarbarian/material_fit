# Experiment Contracts

## Shared Stage 1

Stage 1 asks whether the optimizer can recover a human-adjusted Laya material
from its rendered PNGs. It is an optimizer and scorer test, not yet a direct
Unity-to-Laya fit.

The start is each asset's original continuous and discrete material state. The
target renderer loads the human-adjusted material and writes eight private
reference images. The target process is stopped before the candidate renderer
starts. The optimizer receives only PNG-derived score and residual data.

The capture contract is fixed for every asset:

- yaw `0, 45, 90, 135, 180, 225, 270, 315`
- pitch `0`
- yaw and pitch offsets `0`
- model-bounds auto-framing
- animation disabled before startup settling
- white comparison background

The hard-state space contains 16 legal combinations derived without target
information. The continuous space contains 40 material coordinates and six
scene/light coordinates. V86 chooses its policy from the initial PNG score, not
from the asset name. The run scores at most 1,500 materials: one initial state
and 1,499 proposals.

Accepted Linux evidence:

| Asset | Run | Initial | Best | Scored materials | Mean iteration |
| --- | --- | ---: | ---: | ---: | ---: |
| Fish | `shared_stage1_joint_discrete_v162_fish_v86reference400_gpu2_20260716` | 0.774743 | 0.990940 | 1,475 | 280.9 ms |
| Turtle | `shared_stage1_joint_discrete_v164_turtle_v86strict1500_gpu2_20260716` | 0.719121 | 0.990812 | 1,499 | 285.8 ms |
| Crocodile | `shared_stage1_joint_discrete_v170_crocodile_v86latecommon1500_gpu2_20260716` | 0.882472 | 0.990112 | 1,499 | 366.7 ms |

These are evidence records, not hard-coded expected scores. A new machine must
pass renderer stability, scorer sanity, target-privacy, artifact, cleanup, and
speed audits in its own `stage1_report.json`.

## Clean-install reproduction

On 2026-07-18, the packaged fish task was installed and run from source trees
that contained no virtual environment, Node modules, Playwright browser, prior
run output, or Git metadata. Both systems used V86 with 1,499 proposals and the
same tracked assets and policy snapshots.

| System | Initial | Best | Fit time | Stable mean / P50 / P95 | Cleanup |
| --- | ---: | ---: | ---: | ---: | ---: |
| Windows 11 | 0.776088 | 0.987674 | 367.3 s | 237.4 / 195.2 / 228.9 ms | 0 owned PIDs |
| Linux x86-64 | 0.776126 | 0.990880 | 442.2 s | 284.6 / 274.0 / 339.8 ms | 0 owned PIDs |

Each report passed the 500 ms stable-iteration gate and contained eight target,
optimizer-target, start, and best renders. The small score difference is normal
for separate browser and operating-system rendering stacks; the experiment
contract and acceptance decision were identical.

## Phase 0.5

Phase 0.5 renders a target material, applies a known perturbation to the 40
continuous material coordinates, and asks the optimizer to recover the target
from PNGs. Six scene/light coordinates remain fixed. It is useful for testing a
new asset adapter before attempting Stage 1.

The accepted 12-start robustness run is
`phase05_multistart_v6_adaptive_12x600_20260710_234725`: all 12 starts reached
at least 0.98, with mean/min/max `0.986467/0.980295/0.995001`.

## Pattern16

Pattern16 is the retained cross-engine fish baseline. It searches 16 appearance
coordinates from the active fish material against the packaged Unity reference
PNGs. Texture bindings, UV transforms, alpha/cutoff values, shader toggles,
render state, and scene/light orientation remain locked.

Zero-start means those 16 searchable appearance coordinates begin at zero. It
does not mean every numeric field in the material is zeroed.

## Acceptance

A run is accepted only if all of these hold:

1. Independent target renders are stable.
2. Same-parameter PNG score is near 1.0 and a tiny perturbation remains high.
3. The optimizer boundary contains no target material, target parameters, or
   target hard-state hint.
4. Target, start, and best each contain eight real PNGs at one resolution.
5. The final Python PNG score reaches the configured success threshold.
6. Stable decision iterations satisfy the configured speed gate.
7. Owned browser, queue, renderer, and helper processes are gone after cleanup.

The early-stop `target_score` and final `success_score` are separate settings.
