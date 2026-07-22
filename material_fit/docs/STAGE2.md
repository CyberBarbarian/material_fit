# Stage 2: Unity-to-Laya material fitting

## Objective

Stage 2 fits a Laya material to a PNG rendered by Unity. The two images do not
share a renderer, camera implementation, pivot, rasterizer, shader, or color
pipeline. Geometry alignment and material optimization are therefore handled
as separate contracts.

The optimizer is PNG-only. It cannot read Unity materials, Unity shader values,
the human-adjusted Laya material, or human-adjusted parameters.

## Inputs

Tracked Unity captures live under `examples/stage2_unity_refs/`. Intake checks
file names, dimensions, alpha silhouettes, metadata, hashes, clipping, and view
mapping:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_intake \
  --asset turtle \
  --output-dir artifacts/stage2_turtle_intake
```

The turtle 1506 set is the maintained geometry-ready Stage 2 case. Fish 1504
and crocodile 1503 remain tracked, but their current Unity captures contain
clipped views and are not accepted multi-view inputs.

## Frozen geometry calibration

Turtle sampling is defined by
`material_fit/assets/stage2_sampling/1506.json`. It preserves the original Laya
perspective camera, field of view, prefab-editor environment, disabled
animation, and white canvas.

For each view, calibration estimates only a full-canvas uniform scale and
translation from silhouettes. It does not crop, flip, change the 3D camera,
inject lighting, inspect candidate material values, or refit per proposal. The
profile is bound to the Unity metadata hash and fails closed if the reference
set changes.

The current single-view task uses `v000_yaw0_pitch0`. The Unity target is mapped
once into the raw Laya frame for the fast loop. Final evidence maps each Laya
render back through the same frozen transform and compares it with the original
full-resolution Unity PNG.

## Material policy

Stage 2 uses the same public policy as Stage 1:
`v86_budget1500_initial_score_routed_unified`.

- start from the original continuous and discrete Laya material state;
- search all 16 legal hard states without target-state information;
- search 40 material coordinates and six scene/light rotations;
- choose the child schedule from the initial V6 image score only;
- freeze the selected hard state and six scene/light coordinates before the
  final material-only refinement;
- allow 1,499 proposals plus the initial material.

The six scene/light coordinates are nuisance variables that can account for a
different directional-light convention across Unity and Laya. They are searched
during the early joint stage, then frozen so the final material refinement
cannot keep moving the lighting solution.

## Scoring schedule

Stage 2 uses two fixed views of the same generic scorer family.

`foreground_dists_aligned_rgb_v3` emphasizes signed normalized-RGB residuals
and supplies a strong inverse-search direction while the candidate is far from
the target. `foreground_dists_aligned_rgb_v6` combines pretrained DISTS,
aligned normalized RGB, and a multi-scale local highlight/shadow descriptor and
is the canonical acceptance metric. The final 266 proposals switch to V6, so
the accepted material cannot be selected only by the pixel-heavy objective.

Both objectives normalize the detected foreground and contain no asset-specific
color constants. The target representation is cached by the persistent scorer.
The main loop uses a `450x350` readback. After optimization, the 20 archived
elites are rendered, registered with the frozen transform, and reranked with V6
at full resolution. This rerank consumes no proposal budget.

Before search, two independent source renders plus tiny and mild perturbations
must pass identity, determinism, continuity, and ordering checks.

## Command

```bash
python -m material_fit.experiments.material_cross_engine_stage2_single_view \
  --asset turtle \
  --view-id v000_yaw0_pitch0
```

## Code layout

Stage 2 is split by runtime responsibility:

- `material_cross_engine_stage2_single_view.py` prepares inputs, starts or
  resumes optimization, and coordinates the fixed stages;
- `stage2_archive.py` owns the budgeted registered refinement and
  full-resolution archive rerank;
- `stage2_evidence.py` captures Unity/start/human/best evidence and writes the
  final acceptance report;
- `stage2_scoring.py` owns canonical score summaries and scorer sanity checks;
- `stage2_io.py` contains the small shared evidence-file helpers.

Asset sampling and geometry calibration remain under `material_fit/assets/`
and `material_fit/vision/`; optimizer policy remains under
`material_fit/optimizer/`. Adding another asset must not add an asset-name
branch to these Stage 2 experiment modules.

The run writes `stage2_single_view_report.json` and
`unity_start_human_best_back_view_full_v86.png`. The four columns are fixed:
Unity reference, original Laya start, offline human-adjusted Laya reference,
and optimized Laya best. The human material is loaded only after optimization
and the optimizer renderer have stopped.

## Acceptance

A run passes when:

1. scorer sanity passes;
2. no target or human material state crosses the optimizer boundary;
3. at most 1,500 unique materials are scored;
4. stable decision time is at most `500 ms` per proposal;
5. the final V6 payload's DISTS distance is at most `0.85` of the source distance;
6. full-resolution Unity/start/human/best evidence exists;
7. cleanup leaves zero owned processes.

The dark underside produced by the original Laya game environment is retained.
Stage 2 does not add ambient fill, SH, or a replacement IBL. Existing custom
reflection Cubemaps remain bound exactly as the asset defines them.

## Accepted result

Linux run `linux_stage2_turtle_v52_v6_localcontrast_20260722` is accepted:

| Quantity | Value |
| --- | ---: |
| Original Laya V6 score | 0.722325 |
| Offline human Laya V6 score | 0.830535 |
| Optimized Laya V6 score | 0.833833 |
| Source DISTS distance | 0.252450 |
| Best DISTS distance | 0.189769 |
| Distance ratio | 0.751708 |
| Best local-contrast fit | 0.885981 |
| Unique scored materials | 1,500 |
| Stable mean / P50 / P95 | 412.9 / 409.0 / 454.6 ms |
| Owned processes after cleanup | 0 |

The best was archive rank 4 from proposal 1,462 and won the independent
full-resolution V6 rerank. Relative to the preceding V5 best, its foreground
dark-pixel fraction below luminance `0.10` increased from `10.83%` to `18.40%`,
and its local-contrast descriptor error fell from `0.03262` to `0.02032`. The
report records that human material and parameters
were not visible to routing, proposals, stopping, reranking, or acceptance.
