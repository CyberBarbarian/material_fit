# Assets

## Packaged examples

The repository contains runtime-only Laya projects for four models:

- `examples/fish_laya_project/`
- `examples/turtle_laya_project/`
- `examples/crocodile_laya_project/`
- `examples/holiday_1613_laya_project/`

Direct Unity Stage 2 references for the same model IDs are stored separately:

- `examples/stage2_unity_refs/1503/`
- `examples/stage2_unity_refs/1504/`
- `examples/stage2_unity_refs/1506/`
- `examples/stage2_unity_refs/1613/`

They contain source assets, the required compiled project bundle, and no IDE
cache or experiment output. The fish Unity reference PNGs are in
`examples/fish_unity_refs/`. Stage 1 start and target materials live with each
project, except the fish start/target copies, which are versioned under
`material_fit/assets/material_starts/1504/`.

Profiles under `material_fit/assets/profiles/` identify the scene, target node,
material node, viewport, and runtime compatibility options. The asset adapter
normalizes every profile to the shared static eight-view contract before use.
Stage 2 reference metadata is loaded by
`material_fit.assets.stage2_unity_references`; it does not alter the Laya asset
adapter or the Stage 1 target material.

The maintained 1613 experiment sends any non-empty reference subset through
one shared-parameter material optimizer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_1613_fit.ps1
```

```bash
bash scripts/run_1613_fit.sh
```

`--view-ids` selects any non-empty subset of the tracked set. Input count does
not select a policy branch: the renderer evaluates one shared parameter vector
at every requested view and aggregates those residuals. The output is one
ordinary `.lmat` using the delivered 1024x1024 texture and unmodified
`Custom_low.shader`; reference images are observations only.

The older one-versus-eight runner is retained only as a diagnostic ablation; it
is not the maintained 1613 optimizer.

The current parameter-only best is tracked under
`material_fit/assets/material_starts/1613/`. It scores
`0.8841877893703689` on the independent eight-view comparison and is explicitly
unaccepted against the `0.98` gate. Create a complete friend-facing ZIP from a
run with `scripts/package_1613_result.*`; omit the run argument to package this
tracked snapshot. The packager copies the entire runtime project, installs the
selected `.lmat`, includes its parameter JSON, and fails if texture UUIDs do not
resolve. Run-backed packages additionally require all eight best renders and a
contact sheet.

## Adding an asset

1. Create a runtime-only project under `examples/<asset>_laya_project/`.
2. Keep the scene or prefab, meshes, materials, textures, shader, and compiled
   `bin/js/bundles/bundle.js`. Exclude IDE caches, `local/`, editor layouts,
   screenshots, and generated browser assets. If the exported runtime resolves
   an opaque binary only through `library/`, keep that individual file and list
   it in the asset manifest; do not commit the rest of the cache.
3. Provide distinct original and human-adjusted materials with identical
   texture bindings.
4. Add a profile under `material_fit/assets/profiles/`.
5. Add path resolution in `material_phase05.py` and `material_stage1.py` only.
   Do not add asset-name branches to optimizer code.
6. Extend `material_fit.doctor` and the adapter tests.
7. Run two fresh target captures and require near-1.0 cross-run score and
   foreground IoU before starting optimization.

An asset is not supported merely because it opens in LayaAirIDE. The headless
scene, shader dependencies, static pose, camera framing, material target, and
cleanup behavior all belong to the runtime contract.
