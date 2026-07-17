# Assets

## Packaged examples

The repository contains runtime-only Laya projects for three models:

- `examples/fish_laya_project/`
- `examples/turtle_laya_project/`
- `examples/crocodile_laya_project/`

They contain source assets, the required compiled project bundle, and no IDE
cache or experiment output. The fish Unity reference PNGs are in
`examples/fish_unity_refs/`. Stage 1 start and target materials live with each
project, except the fish start/target copies, which are versioned under
`material_fit/assets/material_starts/1504/`.

Profiles under `material_fit/assets/profiles/` identify the scene, target node,
material node, viewport, and runtime compatibility options. The asset adapter
normalizes every profile to the shared static eight-view contract before use.

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
