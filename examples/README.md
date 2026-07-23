# Example assets

This directory contains the runtime scenes used by the maintained experiments.

| Directory | Role |
| --- | --- |
| `fish_laya_project/` | fish source scene, materials, textures, shader, bundle |
| `fish_unity_refs/` | static eight-view Unity reference PNGs for Pattern16 |
| `turtle_laya_project/` | turtle Stage 1 source and human-adjusted materials |
| `crocodile_laya_project/` | crocodile Stage 1 source and human-adjusted materials |
| `holiday_1613_laya_project/` | 1613 runtime intake with its original one-material, one-texture appearance space |
| `stage2_unity_refs/` | tracked Unity eight-view references by model ID |

These are runtime packages, not full editor workspaces. LayaAirIDE cache,
machine-local layouts, screenshots, and experiment output are intentionally
excluded. The headless renderer loads them directly through Playwright.

Run `python -m material_fit.doctor` from the repository root to validate all
required files before an experiment. See
[`material_fit/docs/ASSETS.md`](../material_fit/docs/ASSETS.md) for the adapter
contract and the steps for adding another model.

For 1613, use `scripts/run_1613_fit.*` to optimize and
`scripts/package_1613_result.*` to build a validated handoff ZIP. The tracked
experimental best remains outside `examples/` under
`material_fit/assets/material_starts/1613/`; generated runs and delivery ZIPs
remain under ignored `artifacts/`.
