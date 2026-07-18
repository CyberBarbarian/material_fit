# Stage 2: Unity-to-Laya Material Fitting

## Objective

Stage 2 fits a Laya material to PNGs rendered by Unity. Unlike Stage 1, target
and candidate images no longer share a renderer, camera implementation, model
root pivot, rasterizer, color pipeline, or shader implementation. A low image
score is therefore not automatically a material error.

The optimizer remains PNG-only. Unity materials, Unity shader parameters, and
human-adjusted Laya parameters are not optimizer inputs.

## Input contract

The tracked reference sets are under `examples/stage2_unity_refs/`. Each set
must provide:

- eight yaw views at `0,45,90,135,180,225,270,315`, pitch `0`
- `900x700` PNGs with a non-empty binary Alpha silhouette
- exporter metadata with the Unity version, prefab path, projection, view
  mapping, current-pose bounds, renderer inventory, and bone transforms
- no absolute path dependency on the exporter's machine

Run `material_fit.experiments.material_cross_engine_stage2_intake` before any
optimization. Structural validity and geometry readiness are separate results.

## Stage 2 pipeline

1. **Reference intake** validates file names, dimensions, Alpha, metadata, view
   order, yaw mirroring, clipping, and hashes.
2. **Geometry calibration** uses silhouettes only. It resolves view mapping,
   global orthographic scale, and per-view translation caused by pivot
   differences. The calibrated transforms are written to an audit artifact and
   then frozen.
3. **Scorer validation** checks independent repeated Laya renders, identity
   scoring, tiny material perturbations, and deliberately shifted geometry.
   Material score must not improve by changing a frozen geometry transform.
4. **Material optimization** searches the existing legal discrete state and 40
   continuous material coordinates. It receives aligned PNG score and residual
   vectors, not Unity parameters or metadata-derived material hints.
5. **Acceptance** uses the original full-resolution Unity PNGs, frozen geometry
   calibration, eight real Laya PNGs, per-view alignment diagnostics, material
   component scores, timing, and process cleanup.

Geometry calibration is a nuisance-variable fit, not part of the material
search. Allowing every material proposal to choose a new translation or scale
would let the optimizer hide material and silhouette errors.

## Initial intake result

The 2026-07-18 archives contain valid reference sets for 1503, 1504, and 1506.
All 24 PNGs are `900x700`, use binary Alpha, and match their metadata.

Canvas-edge audit:

| Asset | Clipped views | Geometry-ready input |
| --- | --- | --- |
| 1503 crocodile | 0, 135, 180 | no |
| 1504 fish | 135, 180, 225 | no |
| 1506 turtle | none | yes |

The first fish comparison against the corrected static Laya human render failed
the unregistered geometry gate: mean foreground IoU `0.251`, minimum IoU
`0.019`, minimum overlap coefficient `0.045`, and mean symmetric edge distance
`59.8 px`. The material score was invalid because the trusted foreground
overlap was insufficient. This is expected evidence that geometry calibration
must precede material fitting; it is not an optimizer result.

The metadata explains the dominant failure. The Unity 1504 current-pose bounds
center is offset from the selected model root pivot by approximately
`(-2.37,-0.27,0.03)` in exported Laya coordinates. Rotating that root moves the
model across the fixed camera and clips the 135-225 degree views.

## Next acceptance gate

The first maintained Stage 2 experiment should use 1506 or a recaptured 1504
set with a centered capture pivot. Before material search starts, the geometry
calibration must satisfy all eight views:

- foreground overlap coefficient at least `0.80`
- normalized centroid error at most `0.02`
- bounding-box scale error at most `0.15`
- at least `1000` trusted intersection pixels per view
- no unrecorded image flip, crop, warp, or per-proposal registration

Only after this gate passes should Stage 1's material policy be reused against
Unity references.
