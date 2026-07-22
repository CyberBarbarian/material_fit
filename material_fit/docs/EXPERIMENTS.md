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

`disabled` means that the renderer sets Animator speed to zero, sleeps it, and
disables the component without calling `Animator.play`. It does not sample a
named animation state at time zero.

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

On 2026-07-18, commit `622db84` was installed from fresh Git checkouts that
contained no virtual environment, Node modules, Playwright browser, or prior
run output. Linux used the shallow clone command from the README. Both systems
used V86 with 1,499 proposals and the same tracked assets and policy snapshots.

| System | Initial | Best | Fit time | Stable mean / P50 / P95 | Cleanup |
| --- | ---: | ---: | ---: | ---: | ---: |
| Windows 11 | 0.774738 | 0.987781 | 297.9 s | 192.1 / 187.2 / 208.9 ms | 0 owned PIDs |
| Linux x86-64 | 0.774743 | 0.990940 | 422.2 s | 273.2 / 264.2 / 329.2 ms | 0 owned PIDs |

Each report passed the 500 ms stable-iteration gate and contained eight target,
optimizer-target, start, and best renders. The small score difference is normal
for separate browser and operating-system rendering stacks; the experiment
contract and acceptance decision were identical.

## Static-pose correction

An audit on 2026-07-18 found that the old runtime interpreted
`animation_mode=disabled` as “play the default state at normalized time zero,
then pause.” The packaged fish capture bundle also contained an older
`idle1@0.21875` pre-freeze. Those runs remain useful as optimizer and throughput
history, but their images are not canonical static-pose evidence.

The corrected runtime never plays an animation in disabled mode. A full Windows
fish Stage 1 run, `stage1_fish_human_png_20260718_141032`, passed with an initial
score of `0.774138`, a best score of `0.984523`, 1,475 scored materials, and
stable iteration mean/P50/P95 of `274.2/248.0/284.2 ms`. It emitted eight target,
start, and best renders and left zero owned processes.

## Phase 0.5

Phase 0.5 renders a target material, applies a known perturbation to the 40
continuous material coordinates, and asks the optimizer to recover the target
from PNGs. Six scene/light coordinates remain fixed. It is useful for testing a
new asset adapter before attempting Stage 1.

The accepted 12-start robustness run is
`phase05_multistart_v6_adaptive_12x600_20260710_234725`: all 12 starts reached
at least 0.98, with mean/min/max `0.986467/0.980295/0.995001`.

## Single-view three-stage evidence

The current single-view policy uses the public
`v86_budget1500_initial_score_routed_unified` contract. The early Stage 1/2
search uses `foreground_dists_aligned_rgb_v3`; final refinement and every
acceptance decision use `foreground_dists_aligned_rgb_v6`. V6 combines DISTS,
aligned RGB, and a generic multi-scale local-contrast term. The switch is fixed
before the run and does not depend on asset identity or target parameters.

Accepted Linux Phase 0.5 campaign
`linux_phase05_turtle_v52_v6_localcontrast_20260722` exercised two
independent starts:

| Case | Initial | Best | Decisions | Stable mean | Hard-state audit |
| --- | ---: | ---: | ---: | ---: | --- |
| `joint_mild_seed53` | 0.781523 | 0.981888 | 268 | 450.6 ms | passed |
| `mixed_mild_seed71` | 0.766466 | 0.980053 | 608 | 442.2 ms | passed |

Both cases used only target PNGs at the optimizer boundary, recovered legal
known coordinates, passed the `500 ms` speed gate, and left zero owned PIDs.

Accepted Stage 1 run
`linux_stage1_turtle_v52_v6_localcontrast_20260722` started from the
original turtle material and fitted the privately rendered human target PNG:

- V6 score `0.764382 -> 0.953396`;
- 1 initial score plus 1,498 observed proposals, within the 1,500-material cap;
- target hard-state recovery passed;
- stable mean/P50/P95 `437.7/432.1/487.2 ms`;
- target parameters and target hard-state values absent from optimizer input;
- zero owned PIDs after cleanup.

The preceding V5 wrapper and policy also passed on Windows 11 as
`stage1_turtle_human_png_20260722_194936`: V5 score
`0.811871 -> 0.935444`, 1,499 scored materials, correct hard-state recovery,
stable mean/P50/P95 `474.9/423.0/744.5 ms`, and zero owned PIDs. The maintained
cross-platform Stage 1 gate is `0.93`. The V6 implementation passes the Windows
doctor and unit suite; the accepted V6 end-to-end evidence recorded here is
Linux.

Accepted Stage 2 run `linux_stage2_turtle_v52_v6_localcontrast_20260722` replaced the
target with the tracked Unity top-view PNG while keeping the policy and budget:

| Material | V6 score | DISTS distance | Local-contrast fit |
| --- | ---: | ---: | ---: |
| Original Laya start | 0.722325 | 0.252450 | 0.533847 |
| Offline human-adjusted Laya | 0.830535 | 0.189697 | 0.878065 |
| Optimized Laya best | 0.833833 | 0.189769 | 0.885981 |

The best/start DISTS-distance ratio was `0.751708`, below the `0.85` gate. The
run scored exactly 1,500 unique materials, had stable mean/P50/P95
`412.9/409.0/454.6 ms`, reranked 20 existing archive elites without new
proposals, and left zero owned PIDs. The human material was loaded only for the
post-run comparison sheet and did not participate in routing, proposals,
stopping, reranking, or acceptance.

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
