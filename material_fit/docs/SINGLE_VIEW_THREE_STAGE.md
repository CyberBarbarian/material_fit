# Single-view three-stage material fitting

## Purpose

This line separates optimizer validation from the extra uncertainty introduced
by a second renderer. Every scored candidate uses one fixed semantic top view.
The maintained reference case is turtle 1506 `v000_yaw0_pitch0`.

The stages are ordered and share one material representation:

1. **Phase 0.5:** recover known Laya-to-Laya perturbations from target PNGs.
2. **Stage 1:** fit the original Laya material to a PNG rendered from the
   human-adjusted Laya material.
3. **Stage 2:** freeze the accepted policy, replace the target with a Unity PNG,
   and fit without reading the human material or parameters.

The human-adjusted material is development evidence. Stage 1 may inspect its
parameters only in `private_audit/` after optimization. Stage 2 loads it only
after the optimizer and candidate renderer have stopped, to render the third
column of the comparison sheet.

## Render contract

- one top-view PNG per scored material;
- yaw `0`, pitch `0`, and zero view offsets;
- animation disabled before settling;
- fixed camera, projection, framing, white background, scene, and environment;
- target capture stopped before the persistent candidate renderer starts;
- owned browser and helper PIDs recorded under the run directory and removed
  during cleanup.

Stage 2 additionally uses one silhouette-derived uniform scale and translation.
The transform is calibrated before optimization and remains fixed for every
candidate. It cannot absorb material changes during search.

## Search space

The material search contains:

- 40 normalized continuous coordinates from
  `STRUCTURED_MATERIAL_ONLY_COORDINATES`;
- 16 legal hard states formed by `NORMALMAP`, `NORMALMAP_Y_INVERT`,
  `RIMSMOOTHNESS`, and `s_BlendSrc`;
- six scene/light rotation coordinates for Stage 1 and Stage 2.

Phase 0.5 holds the six scene/light coordinates fixed because its target and
candidate share the same scene. Stage 1 and Stage 2 may adjust them during the
early joint search. The selected hard state and all six scene/light coordinates
are frozen before the final 40-coordinate material refinement.

Texture bindings, texture `*_ST` transforms, cutoff/alpha validity values, and
hidden material-validity fields are inherited from the original material. The
optimizer starts from the real original continuous and discrete state. It does
not copy a target define, bool, render state, continuous value, or asset-specific
hint into the start.

## Image objectives

The policy uses two fixed, asset-independent objectives. Both normalize the
detected foreground to a square white canvas and use the same pretrained DISTS
network.

The acceptance objective is `foreground_dists_aligned_rgb_v6`:

```text
score_v6 = 0.75 * exp(-DISTS distance)
         + 0.05 * aligned normalized-RGB fit
         + 0.20 * normalized local-contrast fit
```

It is used for the initial route, Phase 0.5, the final Stage 1/2 refinement,
archive reranking, final reports, and acceptance. Its residual contains DISTS,
signed normalized-RGB, multi-scale signed luminance contrast and gradient
quantiles, and generic material-distribution features. The local-contrast term
is asset-independent and penalizes compressed highlights and shadows without
using target material parameters or asset-specific color constants.

The early inverse-search objective is `foreground_dists_aligned_rgb_v3`:

```text
score_v3 = 0.15 * exp(-DISTS distance)
         + 0.85 * aligned normalized-RGB fit
```

The stronger pixel term gives a useful local direction when the source is far
from the target. The final search switches back to V6 so that a pixel-colored
but perceptually poor candidate cannot win acceptance. Neither objective uses a
target material, target parameter, asset name, or target color constant.

Before optimization, independent same-parameter renders plus tiny and mild
perturbations verify determinism, continuity, and ordering. A failed sanity
gate stops the run.

## Optimizer and budget

The public policy is `v86_budget1500_initial_score_routed_unified`. It is a
deterministic black-box optimizer, not a trained optimizer model.

1. Score the source once with V6 and select one immutable low, medium, or high
   child schedule from that scalar only.
2. Probe the 16 legal hard states and begin joint continuous search with V3.
3. Rescan the common hard-state space after continuous progress.
4. Continue inverse search, then switch to V6 for a final hard-state rescan and
   material polish.
5. Freeze the hard state and six scene/light coordinates before the last
   material-only refinement.

The exact proposal allocation is `16 + 1 + 366 + 16 + 834 + 16 + 250 = 1,499`.
Including the source material, one run scores at most 1,500 unique materials.
The router and optimizer receive only image scores and residual vectors.

## Phase 0.5

Phase 0.5 builds a target with the same Laya renderer, perturbs known material
coordinates, then asks the production policy to recover the target. Target
parameters and material files are stored under `private_audit/`; the runtime
configuration references target PNGs only.

The maintained campaign includes a continuous joint perturbation and a mixed
continuous plus hard-state perturbation:

```bash
python -m material_fit.experiments.single_view_phase05_v86 \
  --asset turtle \
  --case joint_mild_seed53 \
  --case mixed_mild_seed71
```

Acceptance requires independent target stability, near-one same-parameter
score, continuous perturbation ordering, V6 score at least `0.98`, legal
hard-state recovery, the 1,500-material budget, the `500 ms` stable-iteration
gate, real target/start/best PNGs, and zero owned process residue.

## Stage 1

Stage 1 renders the human-adjusted material once, stops that renderer, and fits
the original material using only the resulting PNG. The private parameter audit
checks whether image convergence is consistent with the known endpoint; it is
not optimizer input.

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_stage1.ps1 -Asset turtle
```

Linux:

```bash
bash scripts/run_stage1.sh turtle
```

The maintained cross-platform Stage 1 acceptance score is `0.93`. Phase 0.5
keeps the stricter `0.98` gate because its target is generated from the same
renderer and scene.

## Stage 2

Stage 2 replaces the target with the tracked Unity top-view PNG. The main loop
scores raw `450x350` Laya readbacks against a once-transformed Unity reference.
After 1,499 proposals, the 20 archived elites are rendered and reranked at full
resolution against the original Unity frame. Reranking creates no new material
proposals.

```bash
python -m material_fit.experiments.material_cross_engine_stage2_single_view \
  --asset turtle \
  --view-id v000_yaw0_pitch0
```

The comparison sheet is always ordered as Unity reference, original Laya start,
offline human-adjusted Laya reference, and optimized Laya best. The human column
is reporting evidence only.

Stage 2 is accepted when the V6 payload's DISTS distance for the final best is at most
`0.85` of the original distance and all scorer, budget, timing, and cleanup
gates pass.

## Accepted Linux evidence

The current turtle runs were recorded on 2026-07-22:

| Stage | Run | Start | Best | Scored materials | Stable mean |
| --- | --- | ---: | ---: | ---: | ---: |
| Phase 0.5 joint | `linux_phase05_turtle_v52_v6_localcontrast_20260722` | 0.781523 | 0.981888 | 269 | 450.6 ms |
| Phase 0.5 mixed | same campaign | 0.766466 | 0.980053 | 609 | 442.2 ms |
| Stage 1 Linux | `linux_stage1_turtle_v52_v6_localcontrast_20260722` | 0.764382 | 0.953396 | 1,499 | 437.7 ms |
| Stage 1 Windows (V5 evidence) | `stage1_turtle_human_png_20260722_194936` | 0.811871 | 0.935444 | 1,499 | 474.9 ms |
| Stage 2 | `linux_stage2_turtle_v52_v6_localcontrast_20260722` | 0.722325 | 0.833833 | 1,500 | 412.9 ms |

Both Stage 1 evidence runs recovered the target hard state, passed the same
`0.93` acceptance gate, and left zero owned processes. The Windows row predates
V6; the current V6 scorer passes the Windows doctor and unit suite, while its
accepted end-to-end evidence above is Linux. Stage 2 used no human material or
parameters, improved the DISTS distance ratio to `0.751708`, and scored above
the offline human reference (`0.830535`) under the frozen V6 acceptance metric.

## Evidence files

Every accepted run records:

- `fit_config.json` and immutable policy hashes;
- optimizer-boundary and hard-state-space reports;
- scorer sanity and target stability reports;
- actual target, start, and best PNGs;
- proposal-budget and iteration-timing reports;
- final score payloads and process-cleanup audit.

Generated experiment output belongs under `artifacts/` and is not committed.

## References

- Ding et al., [Image Quality Assessment: Unifying Structure and Texture
  Similarity](https://arxiv.org/abs/2004.07728), 2020.
- Wan et al., [Think Global and Act Local: Bayesian Optimisation over
  High-Dimensional Categorical and Mixed Search
  Spaces](https://proceedings.mlr.press/v139/wan21b.html), 2021.
- Ghildyal and Liu, [Shift-tolerant Perceptual Similarity
  Metric](https://www.ecva.net/papers/eccv_2022/papers_ECCV/html/1551_ECCV_2022_paper.php),
  2022.
